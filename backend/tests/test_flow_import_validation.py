"""A flow file is executable input, not a document.

`POST /api/flows/{bot}/import` used to write any uploaded JSON straight into the
active flow and answer with a bare English string even when parsing failed. An
imported template is executed by the engine with the bot's privileges, so it is
validated first, and the answer comes back in the language the panel asked for.
"""
import json

import pytest

from app.core.flow_plan import TELEGRAM_CALLBACK_DATA_LIMIT, validate_flow
from app.core.security import create_access_token
from app.engine.core_nodes import NODE_CATALOG

KNOWN = set(NODE_CATALOG)


def node(node_id, node_type="trigger_message", **data):
    return {"id": node_id, "type": node_type, "data": data}


def test_a_template_with_a_trigger_and_connected_edges_is_accepted():
    nodes = [node("start", "trigger_message"), node("reply", "action_send_message", text="hello")]
    assert validate_flow(nodes, [{"source": "start", "target": "reply"}], known_types=KNOWN) == []


def test_unknown_node_type_is_named_in_the_report():
    problems = validate_flow([node("start", "exec_remote_code")], [], known_types=KNOWN)
    assert any("exec_remote_code" in problem for problem in problems), problems


def test_dangling_edge_is_rejected():
    problems = validate_flow([node("start")], [{"source": "start", "target": "ghost"}], known_types=KNOWN)
    assert any("ghost" in problem for problem in problems), problems


def test_duplicate_and_untyped_nodes_are_rejected():
    problems = validate_flow([node("start"), node("start"), {"id": "x"}], [], known_types=KNOWN)
    assert any("duplicate node id 'start'" in problem for problem in problems), problems
    assert any("no type" in problem for problem in problems), problems


def test_callback_data_beyond_telegrams_limit_is_rejected():
    too_long = "ب" * 40  # legal Python string, illegal callback_data: 80 UTF-8 bytes
    assert len(too_long.encode("utf-8")) > TELEGRAM_CALLBACK_DATA_LIMIT
    nodes = [node("start", "trigger_callback", buttons=[{"text": "pay", "callback_data": too_long}])]
    problems = validate_flow(nodes, [], known_types=None)
    assert any("callback_data" in problem for problem in problems), problems


def test_flow_without_trigger_reports_that_nothing_can_start_it():
    problems = validate_flow([node("reply", "action_send_message")], [], known_types=KNOWN)
    assert any("trigger" in problem for problem in problems), problems


def test_non_array_graph_is_reported_instead_of_raising():
    assert validate_flow({"id": "start"}, None) == ["nodes and edges must both be arrays"]


@pytest.fixture
async def import_fixture():
    """The real app on an in-memory DB holding one bot with one active flow."""
    import aiosqlite
    from httpx import ASGITransport, AsyncClient

    from app.database import get_db
    from app.main import app

    async with aiosqlite.connect(":memory:") as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""CREATE TABLE flows (
            id INTEGER PRIMARY KEY, bot_id INTEGER, name TEXT, is_active INTEGER,
            version INTEGER DEFAULT 1, nodes TEXT, edges TEXT, viewport TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("INSERT INTO flows (id, bot_id, name, is_active, version, nodes, edges) "
                         "VALUES (1, 1, 'Main Flow', 1, 3, ?, ?)",
                         (json.dumps([node("start", "trigger_message")]), "[]"))
        await db.commit()

        async def override_get_db():
            return db

        app.dependency_overrides[get_db] = override_get_db
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http, db
        app.dependency_overrides.clear()


async def upload(http, template, lang="en"):
    payload = template if isinstance(template, (str, bytes)) else json.dumps(template)
    return await http.post(
        "/api/flows/1/import",
        files={"file": ("flow.json", payload, "application/json")},
        headers={"Authorization": f"Bearer {create_access_token('admin')}", "Accept-Language": lang},
    )


async def stored_flow(db):
    cursor = await db.execute("SELECT nodes, version FROM flows WHERE id = 1")
    row = await cursor.fetchone()
    return json.loads(row["nodes"]), row["version"]


async def test_unparseable_template_is_reported_in_the_requested_language(import_fixture):
    http, _db = import_fixture
    response = await upload(http, "{ this is not json", lang="fa")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert any("\u0600" <= char <= "\u06ff" for char in detail), detail


async def test_json_that_is_not_an_object_is_rejected(import_fixture):
    http, _db = import_fixture
    response = await upload(http, [{"id": "start"}])
    assert response.status_code == 400
    assert "expected a JSON object" in response.json()["detail"]


async def test_rejected_template_never_replaces_the_active_flow(import_fixture):
    http, db = import_fixture
    before_nodes, before_version = await stored_flow(db)

    response = await upload(http, {"nodes": [{"id": "evil", "type": "exec_remote_code"}], "edges": []})
    assert response.status_code == 422
    assert "exec_remote_code" in response.json()["detail"]

    after_nodes, after_version = await stored_flow(db)
    assert after_nodes == before_nodes and after_version == before_version, \
        "an invalid import must leave the running flow untouched"


async def test_valid_template_import_is_confirmed_in_the_requested_language(import_fixture):
    http, db = import_fixture
    template = {
        "nodes": [node("start", "trigger_message"), node("reply", "action_send_message", text="ok")],
        "edges": [{"source": "start", "target": "reply"}],
    }
    response = await upload(http, template, lang="ru")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True and body["nodes_count"] == 2
    assert any("\u0400" <= char <= "\u04ff" for char in body["message"]), body["message"]

    stored_nodes, version = await stored_flow(db)
    assert [entry["id"] for entry in stored_nodes] == ["start", "reply"]
    assert version == 4, "importing must bump the version the engine cache keys on"
