import json
import re
from pathlib import Path
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File

from app.config import settings
from app.core.i18n import language_from_request, reload_locales, t
from app.core.security import require_admin

router = APIRouter(prefix="/api/i18n", tags=["i18n"])
LOCALES_DIR = Path(settings.LOCALES_DIR)
LOCALES_DIR.mkdir(parents=True, exist_ok=True)

LANG_CODE = re.compile(r"^[a-z]{2,5}$")


@router.get("/languages")
async def list_languages() -> List[Dict[str, Any]]:
    """Returns available language packages by scanning the locales directory."""
    languages = []
    for file in sorted(LOCALES_DIR.glob("*.json")):
        code = file.stem
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
                meta = data.get("_meta", {})
                languages.append({
                    "code": code,
                    "name": meta.get("name", code.upper()),
                    "dir": meta.get("dir", "rtl" if code in ("fa", "ar", "he", "ur") else "ltr"),
                    "flag": meta.get("flag", "🌐")
                })
        except Exception:
            languages.append({"code": code, "name": code.upper(), "dir": "ltr", "flag": "🌐"})
    return languages


@router.get("/{lang_code}")
async def get_language_dict(lang_code: str) -> Dict[str, Any]:
    """Serves one language pack.

    The requested code is validated before it touches the filesystem (it used to
    be interpolated into a path), and reading a pack cannot escape LOCALES_DIR.
    """
    code = (lang_code or "").lower()
    if not LANG_CODE.match(code):
        raise HTTPException(status_code=400, detail=t("api.i18n.bad_code"))

    file_path = LOCALES_DIR / f"{code}.json"
    if not file_path.exists():
        for fallback_code in (settings.DEFAULT_LANGUAGE, "fa"):
            fallback = LOCALES_DIR / f"{fallback_code}.json"
            if fallback.exists():
                file_path = fallback
                break
        else:
            raise HTTPException(status_code=404, detail=t("api.i18n.bad_code"))

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/upload")
async def upload_language_file(
    request: Request,
    file: UploadFile = File(...),
    admin: str = Depends(require_admin),
):
    """Adds a new language pack to the whole platform from one JSON file."""
    lang = language_from_request(request)
    original = Path(file.filename or "").name
    if not original.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail=t("api.i18n.only_json", lang))

    code = original.rsplit(".", 1)[0].lower()
    if not LANG_CODE.match(code):
        raise HTTPException(status_code=400, detail=t("api.i18n.bad_code", lang))

    dest = (LOCALES_DIR / f"{code}.json").resolve()
    if dest.parent != LOCALES_DIR.resolve():
        raise HTTPException(status_code=400, detail=t("api.i18n.bad_code", lang))

    content = await file.read()
    try:
        parsed = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=t("api.i18n.invalid_json", lang)) from error
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=t("api.i18n.invalid_json", lang))

    with open(dest, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    reload_locales()
    return {
        "success": True,
        "code": code,
        "message": t("api.i18n.installed", lang, code=code),
    }
