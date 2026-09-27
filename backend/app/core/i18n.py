"""Locale backed messages for everything the backend says out loud.

No user visible string is hardcoded in Python: they live in
`backend/locales/<code>.json` under the `api` namespace (bot authored texts use
the same directory), so a language pack can be translated without touching code.
`frontend/src/locales/i18nAudit.test.mjs` enforces the same rule for the panel.
"""

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

PLACEHOLDER = re.compile(r"\{(\w+)\}")
# A missing/unknown language falls back to English, then to the studio default.
FALLBACK_CHAIN = ("en",)

_cache: Dict[str, Dict[str, Any]] = {}
_mtimes: Dict[str, float] = {}
_lock = threading.Lock()


def locales_dir() -> Path:
    return Path(settings.LOCALES_DIR)


def available_languages() -> List[str]:
    return sorted(path.stem for path in locales_dir().glob("*.json") if not path.name.startswith("_"))


def _load(code: str) -> Dict[str, Any]:
    path = locales_dir() / f"{code}.json"
    if not path.exists():
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _cache.get(code, {})

    with _lock:
        if _cache.get(code) and _mtimes.get(code) == mtime:
            return _cache[code]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.error("Locale file %s is unreadable: %s", path, error)
            return _cache.get(code, {})
        if not isinstance(data, dict):
            logger.error("Locale file %s is not a JSON object", path)
            return {}
        _cache[code] = data
        _mtimes[code] = mtime
        return data


def reload_locales() -> None:
    with _lock:
        _cache.clear()
        _mtimes.clear()


def lookup(key: str, code: str) -> Optional[str]:
    """Resolves a dotted key (e.g. 'api.auth.invalid') inside one language pack."""
    node: Any = _load(code)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def interpolate(text: str, params: Dict[str, Any]) -> str:
    if not params:
        return text
    return PLACEHOLDER.sub(lambda match: str(params.get(match.group(1), match.group(0))), text)


def t(key: str, lang: Optional[str] = None, **params: Any) -> str:
    """Translates `key`, falling back to English then to the configured default."""
    chain: List[str] = []
    for candidate in (lang, *FALLBACK_CHAIN, settings.DEFAULT_LANGUAGE):
        code = (candidate or "").strip().split("-")[0].lower()
        if code and code not in chain:
            chain.append(code)

    for code in chain:
        text = lookup(key, code)
        if text is not None:
            return interpolate(text, params)

    logger.warning("Missing locale key '%s' in %s", key, "/".join(chain) or "any language")
    return key


def language_from_header(accept_language: Optional[str]) -> Optional[str]:
    """Picks the first Accept-Language tag we actually ship a pack for."""
    if not accept_language:
        return None
    known = set(available_languages())
    for raw in accept_language.split(","):
        tag = raw.split(";")[0].strip().split("-")[0].lower()
        if tag in known:
            return tag
    return None


def language_from_request(request) -> str:
    """Precedence: ?lang= > Accept-Language > bot default > configured default."""
    query_lang = request.query_params.get("lang")
    return (
        language_from_header(query_lang)
        or language_from_header(request.headers.get("accept-language"))
        or settings.DEFAULT_LANGUAGE
    )
