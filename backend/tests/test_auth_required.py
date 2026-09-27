"""A JWT is only decoration until some code verifies it.

The panel API used to answer every request anonymously: a token was minted at
login, sent by the browser, and never checked, including on the endpoint that
shells out to deploy/update.sh. These tests pin both halves of the fix: the
guard middleware in `app.main` that refuses every non-public /api request that
carries no valid bearer token, and the `require_admin` dependency that protects
each router even if somebody mounts it without the middleware.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.config import settings
from app.core.security import create_access_token, is_public_path, require_admin
from app.main import app


def auth_headers(lang="en", token=None):
    return {"Authorization": f"Bearer {token or create_access_token('admin')}", "Accept-Language": lang}


async def get(path, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.get(path, **kwargs)


PROTECTED_CALLS = [
    ("GET", "/api/bots"),
    ("POST", "/api/system/update"),
    ("POST", "/api/i18n/upload"),
    ("DELETE", "/api/bots/1"),
]


@pytest.mark.parametrize("method,path", PROTECTED_CALLS)
async def test_protected_endpoints_refuse_anonymous_callers(method, path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.request(method, path)
    assert response.status_code == 401, f"{method} {path} answered {response.status_code} to an anonymous caller"
    assert isinstance(response.json().get("detail"), str)


@pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c", ""])
async def test_forged_or_expired_token_is_rejected(token):
    response = await get("/api/bots", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_token_signed_with_another_secret_is_rejected():
    forged = jwt.encode(
        {"sub": "admin", "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
         "iss": settings.APP_NAME},
        "attacker-chosen-secret",
        algorithm=settings.JWT_ALGORITHM,
    )
    response = await get("/api/bots", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401, "the signature, not the claim text, has to decide access"


async def test_expired_token_is_rejected():
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    stale = jwt.encode(
        {"sub": "admin", "iat": int(expired_at.timestamp()),
         "exp": int((expired_at + timedelta(minutes=1)).timestamp()), "iss": settings.APP_NAME},
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    response = await get("/api/bots", headers={"Authorization": f"Bearer {stale}"})
    assert response.status_code == 401


async def test_valid_token_grants_access():
    response = await get("/api/flows/catalog", headers=auth_headers())
    assert response.status_code == 200, "a freshly minted token must be accepted by the guard"


async def test_401_detail_follows_accept_language():
    english = await get("/api/bots", headers={"Accept-Language": "en"})
    persian = await get("/api/bots", headers={"Accept-Language": "fa"})
    assert english.status_code == persian.status_code == 401
    english_text, persian_text = english.json()["detail"], persian.json()["detail"]
    assert english_text != persian_text, "the same auth rejection must be answered in the caller's language"
    assert any("\u0600" <= char <= "\u06ff" for char in persian_text), persian_text


def test_public_paths_stay_reachable_without_a_token():
    # Telegram and the login screen cannot sign requests, so these stay open.
    assert is_public_path("/api/auth/login", "POST")
    assert is_public_path("/api/webhook/7/secret", "POST")
    assert is_public_path("/api/i18n/languages", "GET")
    assert is_public_path("/media/avatars/x.png", "GET")
    # Everything the panel does must not be.
    assert not is_public_path("/api/bots", "GET")
    assert not is_public_path("/api/system/update", "POST")
    assert not is_public_path("/api/flows/1/import", "POST")
    assert not is_public_path("/api/system/info", "GET")


async def test_router_dependency_protects_endpoints_without_middleware():
    """`require_admin` must work even on an app mounted without the guard middleware."""
    bare = FastAPI()

    @bare.get("/protected", dependencies=[Depends(require_admin)])
    async def protected():
        return {"ok": True}

    transport = ASGITransport(app=bare)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        anonymous = await http.get("/protected")
        authorized = await http.get("/protected", headers=auth_headers())
    assert anonymous.status_code == 401
    assert authorized.status_code == 200
