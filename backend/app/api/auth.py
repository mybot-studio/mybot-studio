import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import settings
from app.core.i18n import language_from_request, t
from app.core.passwords import hash_password, needs_upgrade, verify_password
from app.core.security import (
    client_ip_of,
    create_access_token,
    login_attempts,
    require_admin,
)
from app.database import get_db
from app.models.schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ChangeCredentialsRequest(BaseModel):
    current_password: str
    new_username: str = Field(min_length=3)
    new_password: str = Field(min_length=8)


async def _find_admin(db: aiosqlite.Connection, username: str):
    cursor = await db.execute(
        "SELECT id, username, password_hash FROM admin_users WHERE username = ?", (username,)
    )
    return await cursor.fetchone()


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, db: aiosqlite.Connection = Depends(get_db)):
    """Issues the JWT that every other /api route now verifies.

    The old code accepted `DEFAULT_ADMIN_PASS` as an always-valid fallback
    password, which turned the shipped default into a permanent backdoor. Only a
    hash stored in `admin_users` (seeded once by `init_db`) is honoured here.
    """
    lang = language_from_request(request)
    username = (req.username or "").strip()
    password = (req.password or "").strip()
    ip = client_ip_of(request)

    login_attempts.prune()
    locked_for = login_attempts.locked_out_seconds(username, ip)
    if locked_for:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=t("api.auth.locked", lang, seconds=locked_for),
            headers={"Retry-After": str(locked_for)},
        )

    user = await _find_admin(db, username)
    if not user:
        login_attempts.register_failure(username, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=t("api.auth.invalid", lang)
        )

    stored_hash = user["password_hash"]
    if not verify_password(password, stored_hash, settings.JWT_SECRET):
        login_attempts.register_failure(username, ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=t("api.auth.invalid", lang)
        )

    # Transparently replace pre-scrypt hashes with a properly salted one.
    if needs_upgrade(stored_hash):
        await db.execute(
            "UPDATE admin_users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user["id"]),
        )
        await db.commit()

    login_attempts.reset(username, ip)
    token = create_access_token(user["username"])
    return TokenResponse(access_token=token)


@router.post("/change-credentials")
async def change_credentials(
    req: ChangeCredentialsRequest,
    request: Request,
    admin: str = Depends(require_admin),
    db: aiosqlite.Connection = Depends(get_db),
):
    lang = language_from_request(request)
    cursor = await db.execute(
        "SELECT id, username, password_hash FROM admin_users WHERE username = ?", (admin,)
    )
    user = await cursor.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail=t("api.auth.not_configured", lang))

    if not verify_password((req.current_password or "").strip(), user["password_hash"], settings.JWT_SECRET):
        raise HTTPException(status_code=400, detail=t("api.auth.current_password_wrong", lang))

    new_username = (req.new_username or "").strip()
    if new_username != user["username"] and await _find_admin(db, new_username):
        raise HTTPException(status_code=409, detail=t("api.auth.username_taken", lang))

    await db.execute(
        "UPDATE admin_users SET username = ?, password_hash = ? WHERE id = ?",
        (new_username, hash_password((req.new_password or "").strip()), user["id"]),
    )
    await db.commit()
    return {"success": True, "message": t("api.auth.credentials_updated", lang)}

