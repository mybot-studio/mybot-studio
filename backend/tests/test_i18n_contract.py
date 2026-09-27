"""Locale packs must stay mergeable, or a GitHub translation PR cannot be merged.

`scripts/check_i18n.py` enforces the same contract from the command line; this
test keeps it inside the suite so a contributor who only runs pytest cannot ship
a locale file that breaks a release. A duplicate key inside a JSON object is the
worst case: Python's parser silently keeps the last value, so a translation
review looks clean while one string quietly disappears from the panel.
"""
import ast
import json
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
LOCALES = BACKEND_ROOT / "locales"
LANGUAGES = ["en", "fa", "ar", "ru"]
PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
UNTRANSLATED = re.compile(r"\bTODO: translate\b")


def raw_DUPLICATE_pairs(language):
    """Duplicate keys in a locale file, which `json.loads` silently discards."""
    problems = []

    def hook(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                problems.append(f"{language}.json: duplicate key '{key}'")
            seen.add(key)
        return dict(pairs)

    json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"), object_pairs_hook=hook)
    return problems


def loaded(language):
    return json.loads((LOCALES / f"{language}.json").read_text(encoding="utf-8"))


def flatten(nested, prefix=""):
    flat = {}
    for key, value in nested.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten(value, path))
        else:
            flat[path] = value
    return flat


def test_no_duplicate_keys_in_any_locale():
    problems = [problem for language in LANGUAGES for problem in raw_DUPLICATE_pairs(language)]
    assert not problems, "\n".join(problems)


def test_all_languages_expose_the_same_keys_as_english():
    reference = set(flatten(loaded("en")))
    missing = [f"{language}.json: missing {key}"
               for language in LANGUAGES
               for key in sorted(reference - set(flatten(loaded(language))))]
    extra = [f"{language}.json: key '{key}' is not in en.json"
             for language in LANGUAGES
             for key in sorted(set(flatten(loaded(language))) - reference)]
    assert not missing + extra, "\n".join(missing + extra)


def test_every_pack_declares_its_writing_direction():
    for language in LANGUAGES:
        direction = loaded(language).get("_meta", {}).get("dir")
        assert direction in {"ltr", "rtl"}, f"{language}.json has no usable _meta.dir"
    assert loaded("en")["_meta"]["dir"] == "ltr"
    for language in ("fa", "ar"):
        assert loaded(language)["_meta"]["dir"] == "rtl"


def test_placeholders_survive_translation():
    reference = flatten(loaded("en"))
    problems = []
    for language in LANGUAGES:
        for key, value in flatten(loaded(language)).items():
            if key not in reference or not isinstance(value, str):
                continue
            source = set(PARAM.findall(reference[key]))
            translated = set(PARAM.findall(value)) if isinstance(reference[key], str) else set()
            if source != translated:
                problems.append(f"{language}.json: {key} expects {sorted(source)}, found {sorted(translated)}")
    assert not problems, "\n".join(problems)


def test_no_placeholder_text_ships_in_a_release_pack():
    offenders = [f"{language}.json: {key} still says TODO"
                 for language in LANGUAGES
                 for key, value in flatten(loaded(language)).items()
                 if isinstance(value, str) and UNTRANSLATED.search(value)]
    assert not offenders, "\n".join(offenders)


def test_admin_api_reports_status_messages_through_the_locale_pack():
    """No user-facing English literals may come out of the panel API any more."""
    offenders = []
    for path in sorted((BACKEND_ROOT / "app" / "api").glob("*.py")) + [BACKEND_ROOT / "app" / "core" / "security.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            keyword = getattr(node, "keyword", None)
            value = getattr(node, "value", None)
            if keyword in {"detail", "message"} and isinstance(value, ast.Constant) and isinstance(value.value, str):
                if not value.value.strip():
                    continue
                if re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)+", value.value):
                    continue  # already a locale key, not prose
                offenders.append(f"app/api/{path.name}:{node.lineno}: hardcoded '{value.value[:40]}'")
    assert not offenders, "translate through t() instead:\n" + "\n".join(offenders)
