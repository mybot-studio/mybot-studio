import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _csv(value: str) -> list:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    APP_NAME: str = "MyBot Engine"
    VERSION: str = "0.3.0"
    # Never default to a debug/verbose posture: a production install that forgets
    # the env var must not get OpenAPI docs, permissive CORS and stack traces.
    DEBUG: bool = False

    # Server & Secret Admin Path
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    ADMIN_SECRET_PATH: str = os.getenv("ADMIN_SECRET_PATH", "panel_adm_x9a2k")
    # When False the panel serves nothing unless the request carries the secret
    # path prefix. Set True only for local development on loopback.
    ALLOW_ROOT_PANEL: bool = os.getenv("ALLOW_ROOT_PANEL", "false").lower() in ("1", "true", "yes")

    # Database
    DATABASE_PATH: str = str(DATA_DIR / "mybot.db")

    # Security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    # Shared secret Telegram must present in X-Telegram-Bot-Api-Secret-Token.
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
    # Comma separated list of allowed browser origins for the panel.
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:23568,http://127.0.0.1:23568")
    # Brute force protection for the single admin account.
    LOGIN_MAX_ATTEMPTS: int = 8
    LOGIN_LOCKOUT_SECONDS: int = 300
    # Flow/plugin HTTP nodes and the proxy tester may not reach internal networks
    # unless the operator explicitly opts in.
    ALLOW_PRIVATE_URLS: bool = os.getenv("ALLOW_PRIVATE_URLS", "false").lower() in ("1", "true", "yes")
    # Explicit opt-in before the panel will shell out to deploy/update.sh.
    ENABLE_SELF_UPDATE: bool = os.getenv("ENABLE_SELF_UPDATE", "false").lower() in ("1", "true", "yes")

    # Roles: "panel" serves the studio only, "engine" only polls Telegram, "all" does both.
    ROLE: str = os.getenv("ROLE", "all")

    # Admin Credentials (Default on first launch)
    DEFAULT_ADMIN_USER: str = os.getenv("DEFAULT_ADMIN_USER", "admin")
    DEFAULT_ADMIN_PASS: str = os.getenv("DEFAULT_ADMIN_PASS", "")

    # Telegram & Network Proxies
    CF_PROXY_URL: str = os.getenv("CF_PROXY_URL", "")  # e.g., https://your-worker.workers.dev
    HTTP_PROXY: str = os.getenv("HTTP_PROXY", "")     # e.g., socks5://127.0.0.1:1080 or http://127.0.0.1:8080

    # Locales & Fonts Directory
    LOCALES_DIR: str = str(BASE_DIR / "locales")
    FONTS_DIR: str = str(BASE_DIR / "fonts")
    PLUGINS_DIR: str = str(BASE_DIR / "plugins")
    # Language used for backend messages when the caller sends no Accept-Language.
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")

    # Execution log retention (rows kept per bot)
    EXECUTION_LOG_RETENTION: int = 500

    @property
    def cors_origin_list(self) -> list:
        return _csv(self.CORS_ORIGINS)

    @property
    def is_engine(self) -> bool:
        return self.ROLE in ("engine", "all")

    @property
    def is_panel(self) -> bool:
        return self.ROLE in ("panel", "all")

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()

if not settings.JWT_SECRET:
    # A blank secret would let anyone forge an admin token. Refuse to boot
    # instead of silently running with a guessable signing key.
    raise RuntimeError(
        "JWT_SECRET is not configured. Generate one "
        "(e.g. `openssl rand -hex 32`) and put it in .env before starting MyBot Engine."
    )

