"""Flow compilation + validation.

Two problems fixed here:
1. `save_flow`/`import_flow` used to persist any JSON the browser sent and the
   engine executed it blindly. `validate_flow` now rejects unknown node types,
   dangling edges and callback_data beyond Telegram's 64 byte limit at save time.
2. The engine re-parsed the whole flow JSON on *every* incoming update. A
   `FlowPlan` is compiled once per (flow_id, version) and cached, so an update
   costs a dict lookup instead of hundreds of KB of JSON parsing.
"""

import json
import logging
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TELEGRAM_CALLBACK_DATA_LIMIT = 64
MAX_CACHED_PLANS = 128


class FlowValidationError(ValueError):
    """Raised when a flow graph cannot be accepted."""


def _node_id(node: Dict[str, Any]) -> str:
    return str(node.get("id") or node.get("node_id") or "")


def _node_type(node: Dict[str, Any]) -> str:
    return str(node.get("type") or node.get("node_type") or "")


def validate_flow(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]],
                  known_types: Optional[set] = None) -> List[str]:
    """Returns a list of human readable problems; empty list means the flow is valid."""
    problems: List[str] = []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["nodes and edges must both be arrays"]

    seen_ids = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            problems.append(f"node #{index} is not an object")
            continue
        nid = _node_id(node)
        ntype = _node_type(node)
        if not nid:
            problems.append(f"node #{index} has no id")
        elif nid in seen_ids:
            problems.append(f"duplicate node id '{nid}'")
        else:
            seen_ids.add(nid)
        if not ntype:
            problems.append(f"node '{nid or index}' has no type")
        elif known_types and ntype not in known_types:
            problems.append(f"node '{nid or index}' uses unknown type '{ntype}'")

        data = node.get("data") or {}
        if not isinstance(data, dict):
            problems.append(f"node '{nid or index}' has a non-object data block")
            continue
        for button in (data.get("buttons") or []):
            if not isinstance(button, dict):
                continue
            callback = str(button.get("callback_data") or "")
            if callback and len(callback.encode("utf-8")) > TELEGRAM_CALLBACK_DATA_LIMIT:
                problems.append(
                    f"node '{nid or index}' button callback_data is "
                    f"{len(callback.encode('utf-8'))} bytes (max {TELEGRAM_CALLBACK_DATA_LIMIT})"
                )

    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            problems.append(f"edge #{index} is not an object")
            continue
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source not in seen_ids:
            problems.append(f"edge #{index} points from missing node '{source}'")
        if target not in seen_ids:
            problems.append(f"edge #{index} points to missing node '{target}'")

    if known_types and nodes and not any(
        _node_type(n).startswith("trigger_") for n in nodes if isinstance(n, dict)
    ):
        problems.append("flow has no trigger node, nothing will ever start it")

    return problems


class FlowPlan:
    """Pre-indexed flow graph handed to the DAG runner."""

    __slots__ = ("flow_id", "version", "nodes", "edges", "node_map", "adj_list", "incoming_edges",
                 "triggers")

    def __init__(self, flow_id: Any, version: int, nodes: List[Dict[str, Any]],
                 edges: List[Dict[str, Any]]) -> None:
        self.flow_id = flow_id
        self.version = version
        self.nodes = nodes
        self.edges = edges
        self.node_map: Dict[str, Dict[str, Any]] = {}
        for node in nodes:
            self.node_map[_node_id(node)] = node
        self.adj_list: Dict[str, List[Dict[str, Any]]] = {}
        self.incoming_edges: Dict[str, List[Dict[str, Any]]] = {}
        for edge in edges:
            self.adj_list.setdefault(str(edge.get("source")), []).append(edge)
            self.incoming_edges.setdefault(str(edge.get("target")), []).append(edge)
        self.triggers: Dict[str, List[Dict[str, Any]]] = {}
        for node in nodes:
            ntype = _node_type(node)
            if ntype.startswith("trigger_"):
                self.triggers.setdefault(ntype, []).append(node)


_plans: "OrderedDict[Tuple[int, int], FlowPlan]" = OrderedDict()


def compile_plan(flow_id: Any, version: int, nodes_raw: Any, edges_raw: Any) -> FlowPlan:
    nodes = json.loads(nodes_raw) if isinstance(nodes_raw, (str, bytes)) else (nodes_raw or [])
    edges = json.loads(edges_raw) if isinstance(edges_raw, (str, bytes)) else (edges_raw or [])
    return FlowPlan(flow_id, int(version or 0), nodes, edges)


def get_plan(bot_id: int, flow_id: Any, version: int, nodes_raw: Any, edges_raw: Any) -> FlowPlan:
    key = (int(bot_id), int(version or 0))
    plan = _plans.get(key)
    if plan is not None and plan.flow_id == flow_id:
        _plans.move_to_end(key)
        return plan
    plan = compile_plan(flow_id, version, nodes_raw, edges_raw)
    _plans[key] = plan
    while len(_plans) > MAX_CACHED_PLANS:
        _plans.popitem(last=False)
    return plan


def invalidate(bot_id: Optional[int] = None) -> None:
    if bot_id is None:
        _plans.clear()
        return
    for key in [k for k in _plans if k[0] == int(bot_id)]:
        _plans.pop(key, None)


def cached_plan_count() -> int:
    return len(_plans)
