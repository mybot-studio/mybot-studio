"""Authentication and request-authorization primitives.

Before this module existed a JWT was minted on login but never verified, and
`api.js` never sent it — every /api endpoint (including the one that shells out
to deploy/update.sh) was reachable anonymously. `require_admin` is now the
single gate used by every admin router.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings
from app.core.i18n import language_from_request, t

bearer_scheme = HTTPBearer(auto_error=False)

# Paths that must stay reachable without a token: the login form needs the
# language list/dictionary, and Telegram needs the webhook + media URLs.
PUBLIC_GET_PATHS = {"/api/fonts", "/api/system/health", "/healthz"}
PUBLIC_GET_PREFIXES = ("/api/i18n/",)
PUBLIC_POST_PATHS = {"/api/auth/login"}
PUBLIC_ANY_PREFIXES = ("/api/webhook", "/webhook", "/media", "/docs", "/openapi.json")


def is_public_path(path: str, method: str = "GET") -> bool:
    if method == "OPTIONS":
        return True
    if method == "GET":
        if path in PUBLIC_GET_PATHS:
            return True
        if any(path.startswith(prefix) for prefix in PUBLIC_GET_PREFIXES):
            return True
    if method == "POST" and path in PUBLIC_POST_PATHS:
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in PUBLIC_ANY_PREFIXES)


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
        "iss": settings.APP_NAME,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def message(key: str, request: Optional[Request] = None, **params: Any) -> str:
    """Resolves an `api.*` locale key for the caller's language."""
    return t(key, language_from_request(request) if request is not None else None, **params)


def decode_access_token(token: str, lang: Optional[str] = None) -> str:
    """Returns the subject, or raises 401 for anything not validly signed."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("api.auth.expired", lang),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("api.auth.expired", lang),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return str(subject)


async def require_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """FastAPI dependency: every admin endpoint depends on this."""
    lang = language_from_request(request)
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=t("api.auth.required", lang),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(credentials.credentials, lang)


class LoginAttemptTracker:
    """Small in-memory throttle; the panel has exactly one admin account."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)
        self._state: Dict[str, Tuple[int, float]] = {}

    def _key(self, username: str, client_ip: str) -> str:
        return f"{(username or '').strip().lower()}|{client_ip or 'unknown'}"

    def locked_out_seconds(self, username: str, client_ip: str) -> int:
        fails, first_at = self._state.get(self._key(username, client_ip), (0, 0.0))
        if fails < self.max_attempts:
            return 0
        remaining = self.window_seconds - (time.time() - first_at)
        return max(0, int(remaining))

    def register_failure(self, username: str, client_ip: str) -> None:
        key = self._key(username, client_ip)
        fails, first_at = self._state.get(key, (0, time.time()))
        if fails == 0 or (time.time() - first_at) > self.window_seconds:
            self._state[key] = (1, time.time())
        else:
            self._state[key] = (fails + 1, first_at)

    def reset(self, username: str, client_ip: str) -> None:
        self._state.pop(self._key(username, client_ip), None)

    def prune(self) -> None:
        cutoff = time.time() - self.window_seconds
        for key in [k for k, (_, first_at) in self._state.items() if first_at < cutoff]:
            self._state.pop(key, None)


login_attempts = LoginAttemptTracker(settings.LOGIN_MAX_ATTEMPTS, settings.LOGIN_LOCKOUT_SECONDS)


def client_ip_of(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
