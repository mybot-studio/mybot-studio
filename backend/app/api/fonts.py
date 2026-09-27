import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File

from app.config import settings
from app.core.i18n import language_from_request, t
from app.core.security import require_admin

router = APIRouter(prefix="/api/fonts", tags=["fonts"])
FONTS_DIR = Path(settings.FONTS_DIR)
FONTS_DIR.mkdir(parents=True, exist_ok=True)
FONTS_CONFIG = FONTS_DIR / "fonts.json"
ALLOWED_FONT_EXTENSIONS = (".woff2", ".woff", ".ttf", ".otf")

DEFAULT_FONTS = [
    {
        "id": "arad",
        "name": "Arad (آراد)",
        "family": "'Arad', 'Vazirmatn', sans-serif",
        "category": "persian",
        "css_url": "/fonts/AradVF.woff2"
    },
    {
        "id": "vazirmatn",
        "name": "Vazirmatn (وزیرمتن)",
        "family": "'Vazirmatn', -apple-system, BlinkMacSystemFont, sans-serif",
        "category": "persian",
        "css_url": "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css"
    },
    {
        "id": "inter",
        "name": "Inter",
        "family": "'Inter', sans-serif",
        "category": "latin",
        "css_url": "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap"
    },
    {
        "id": "jetbrains-mono",
        "name": "JetBrains Mono",
        "family": "'JetBrains Mono', monospace",
        "category": "monospace",
        "css_url": "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
    }
]

def load_fonts() -> List[Dict[str, Any]]:
    if not FONTS_CONFIG.exists():
        with open(FONTS_CONFIG, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_FONTS, f, ensure_ascii=False, indent=2)
        return DEFAULT_FONTS
    try:
        with open(FONTS_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_FONTS

@router.get("", response_model=List[Dict[str, Any]])
async def list_fonts():
    """Returns the list of installed and available fonts for the entire studio UI."""
    return load_fonts()

@router.post("/upload")
async def upload_font(
    request: Request,
    file: UploadFile = File(...),
    admin: str = Depends(require_admin),
):
    """Installs a custom font (.woff2, .woff, .ttf, .otf) for the studio UI.

    `file.filename` is attacker controlled, so it used to be joined straight
    onto FONTS_DIR; `../../etc/cron.d/x` style names wrote files anywhere the
    service could write. The name is now reduced to a safe slug inside
    FONTS_DIR, and the endpoint needs an authenticated admin.
    """
    lang = language_from_request(request)
    original = Path(file.filename or "").name
    ext = original.suffix.lower()
    if ext not in ALLOWED_FONT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=t("api.fonts.bad_type", lang))

    slug = re.sub(r"[^a-z0-9._-]+", "-", original.rsplit(".", 1)[0].lower()).strip("-.")
    if not slug:
        raise HTTPException(status_code=400, detail=t("api.fonts.bad_name", lang))

    safe_name = f"{slug}{ext}"
    dest_path = FONTS_DIR / safe_name
    if dest_path.resolve().parent != FONTS_DIR.resolve():
        raise HTTPException(status_code=400, detail=t("api.fonts.bad_name", lang))

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    fonts = load_fonts()
    # Check if already exists
    exists = any(f["id"] == slug for f in fonts)
    if not exists:
        fonts.append({
            "id": slug,
            "name": slug.capitalize(),
            "family": f"'{slug}', sans-serif",
            "category": "custom",
            "file_name": safe_name
        })
        with open(FONTS_CONFIG, "w", encoding="utf-8") as f:
            json.dump(fonts, f, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "font_id": slug,
        "name": slug.capitalize(),
        "message": t("api.fonts.installed", lang, name=slug.capitalize()),
    }
