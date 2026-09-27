"""Locale guardrail: every user-visible string must live in backend/locales/*.json.

Checks (run before pushing any change that touches a message or a locale file):

1. Key usage  - every `t("...")` / `message("...")` key used in backend/app
   exists in every shipped language pack, so no language ever renders a raw key.
2. Parity     - language packs stay key-identical against en.json, so adding a
   string to one file is caught the same day.
3. `--scan`   - reports hardcoded user-facing string literals (the text must be
   a locale key instead). Prompt/tool-definition modules are exempt: their
   literals are LLM instructions, not UI text (see AGENTS.md "Prompt language").

Usage:
    python scripts/check_i18n.py
    python scripts/check_i18n.py --scan                # whole backend/app
    python scripts/check_i18n.py --scan backend/app/core/security.py
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "backend" / "app"
LOCALES_DIR = ROOT / "backend" / "locales"
REFERENCE = "en"
# reply_clear.json is a reply-template pack, not a UI dictionary.
IGNORED_FILES = {"reply_clear.json"}

KEY_USAGE = re.compile(r"\b(?:t|message|translate)\(\s*[\"']([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)[\"']")

# Modules whose literals are prompt text for the LLM rather than UI copy.
PROMPT_FILE_MARKERS = ("flow_plan", "prompts", "tool_defs", "adapters" + "/")
# Slugs, ids, mime types, header names: never translatable copy.
NOT_PROSE = re.compile(r"[A-Za-z0-9_.:/+@~#()\[\]{}<>%$^*|=-]+")
# Keyword arguments whose string values are metadata (Pydantic field docs, logging
# formats, multipart media types) rather than text the admin panel displays.
METADATA_KWARGS = {
    "alias", "default", "description", "example", "examples", "format",
    "initial", "media_type", "name", "pattern", "title",
}
# Single lowercase tokens ("ok", "success", "pending") are status/protocol values.
STATUS_TOKEN = re.compile(r"[a-z][a-z0-9_]*")
# Documented exceptions: values that are stored *data* (a default flow name the admin
# can rename in the panel), not strings the interface renders as chrome.
DATA_DEFAULTS = {"Main Flow"}


def flatten(node: Any, prefix: str = "") -> Iterator[Tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict):
                yield from flatten(value, path + ".")
            else:
                yield path, value


def load_locales() -> Dict[str, Dict[str, Any]]:
    packs: Dict[str, Dict[str, Any]] = {}
    for path in sorted(LOCALES_DIR.glob("*.json")):
        if path.name in IGNORED_FILES:
            continue
        packs[path.stem] = dict(flatten(json.loads(path.read_text(encoding="utf-8"))))
    return packs


def used_keys() -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for key in KEY_USAGE.findall(path.read_text(encoding="utf-8")):
            files = found.setdefault(key, [])
            if rel not in files:
                files.append(rel)
    return found


def check_keys(packs: Dict[str, Dict[str, Any]]) -> List[str]:
    problems: List[str] = []
    if not packs:
        return [f"no language files found in {LOCALES_DIR}"]
    if REFERENCE not in packs:
        problems.append(f"{REFERENCE}.json is missing - it is the reference pack")

    reference: Set[str] = set(packs.get(REFERENCE, {}))
    for name, data in packs.items():
        for missing in sorted(reference - set(data)):
            problems.append(f"{name}.json: missing key '{missing}' (present in {REFERENCE}.json)")
        for extra in sorted(set(data) - reference):
            problems.append(f"{name}.json: key '{extra}' exists only in this pack")

    for key, files in sorted(used_keys().items()):
        for name, data in packs.items():
            if key not in data:
                where = ", ".join(files[:3])
                problems.append(f"{name}.json: code uses '{key}' but the key is absent ({where})")
    return problems


def _is_user_facing(text: str, key_name: Optional[str]) -> bool:
    """True for literals that end up on screen and are not identifiers."""
    if not text.strip():
        return False
    if re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z0-9_]+)+", text):  # already a locale key
        return False
    if STATUS_TOKEN.fullmatch(text.strip()):  # status / protocol token
        return False
    if key_name and re.fullmatch(r"__?[a-z][a-z0-9_]*_?_", key_name.replace("__", "_x_")):
        return False
    if key_name and key_name.isupper():  # module constant (limit, path, header name)
        return False
    if NOT_PROSE.fullmatch(text):  # slug / id / URL / header / mime type
        return False
    if text.strip() in DATA_DEFAULTS:
        return False
    return True


def _string_constants(node: ast.AST) -> Iterator[Tuple[ast.Constant, Optional[str]]]:
    """String values that a reader would treat as copy for this statement."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        name = target.id if isinstance(target, ast.Name) else None
        if isinstance(node.value, ast.Constant):
            yield node.value, name
        elif isinstance(node.value, ast.Dict):
            for value in node.value.values:
                if isinstance(value, ast.Constant):
                    yield value, name
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        if isinstance(node.value, ast.Constant):
            yield node.value, node.target.id
    elif isinstance(node, ast.keyword):
        if isinstance(node.value, ast.Constant) and node.arg not in METADATA_KWARGS:
            yield node.value, node.arg
    elif isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
        yield node.value, None


def check_literals(files: List[Path]) -> List[str]:
    problems: List[str] = []
    for path in files:
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        if any(marker in rel for marker in PROMPT_FILE_MARKERS):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for value, key_name in _string_constants(node):
                if isinstance(value.value, str) and _is_user_facing(value.value, key_name):
                    snippet = value.value.strip().replace("\n", " ")[:70]
                    problems.append(f"{rel}:{value.lineno}: hardcoded text: {snippet!r}")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="locale key + hardcoded-string guardrail")
    parser.add_argument("--scan", nargs="*", default=None, metavar="FILE",
                        help="also report hardcoded user-facing literals")
    args = parser.parse_args(argv)

    packs = load_locales()
    problems = check_keys(packs)
    if args.scan is not None:
        files = [Path(item) for item in args.scan] or sorted(APP_DIR.rglob("*.py"))
        problems += check_literals(files)

    if problems:
        print(f"I18N CHECK FAILED ({len(problems)} problem(s)):")
        for problem in problems:
            print("  - " + problem)
        return 1

    scope = "keys + literals" if args.scan is not None else "keys"
    print(f"I18N CHECK OK: {scope} consistent across {', '.join(packs)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

