# AGENTS.md

Rules for AI agents (and humans) working in this repository. These are the conventions the CI guardrails enforce; when a rule and a script disagree, the script wins and this file is wrong — fix the file, don't disable the script.

## 1. No hardcoded language — the one rule that matters most

**A language code is data, not a decision.** Nothing in the backend may hardcode a language. The active pack is always chosen from the request:

- Backend: resolve every user-visible string as `t(key, language_from_request(request), **params)`. `language_from_request` reads `?lang=` then `Accept-Language` then the configured default; the agent must not substitute a literal `"en"`/`"fa"` for it.
- The `Accept-Language` header is the source of truth the panel sends on every request (`frontend/src/services/api.js` sets it from the selected language). Do not add a second language channel.
- `DEFAULT_LANGUAGE` is a *fallback*, not a choice: it only applies when a caller sends nothing. A response that must read in the caller's language must go through `language_from_request`.

If you write a string that a person will read, it is not a string literal — it is a **locale key** (see §2). A hardcoded English, Persian, Arabic or Russian sentence is a defect even when the UI is "in English mode": the guardrail fails on it because another pack will not have it.

## 2. Where copy lives and how it is added

| Surface | Pack location | Resolver |
| --- | --- | --- |
| Backend API + bot-facing messages | `backend/locales/<code>.json` (`api` namespace) | `app/core/i18n.py::t` |
| Panel UI | `frontend/src/locales/<code>.json` | `translate` / `t` / `label` in `frontend/src/locales` |

To add or change a user-facing string:

1. Put the text under the `api` namespace in **every shipped pack** (`en`, `fa`, `ar`, `ru`) with identical `{placeholders}`.
2. Reference it by key, never inline.
3. Run `python scripts/check_i18n.py --scan` (backend) and `cd frontend && npm test` (panel). Both fail on a key missing from one pack, on mismatched placeholders, or on a literal that should be a key.

`en` is the reference pack: a key present in `en` but absent from another pack is an error, and a key present only in one pack is an error. `reply_clear.json` is a reply-template pack and is intentionally ignored by the guardrail.

To add a language: drop `<code>.json` into both `backend/locales/` and `frontend/src/locales/`, then re-run both audits. The backend pack can also be installed at runtime through `POST /api/i18n/upload` (admin only).

## 3. API conventions

- **Authentication is default-deny.** A route that a person uses is not public unless it is on the `is_public_path` allow-list (`app/core/security.py`): the health/login/webhook/media paths and the i18n read endpoints. Every admin router also declares `require_admin`; a newly added route is protected even if the middleware is bypassed. When you add a `/api` route, decide explicitly whether it is public and say why in a comment; otherwise it gets a token.
- **Errors are localized sentences, not Python text.** Raise `HTTPException(status_code=…, detail=t("api.<ns>.<key>", lang))`. Tracebacks go to the server log (`logger.exception`); the caller gets a translated one-liner. Never put `str(exception)` or a `traceback` in a response body.
- **Outbound URLs go through the SSRF guard** (`app/core/net.py::validate_outbound_url`). Proxy and Cloudflare-Worker settings are validated before any connection; private/loopback targets require `ALLOW_PRIVATE_URLS`.
- **Uploads validate the derived name** (language code `^[a-z]{2,5}$`, font id sanitized), resolve the destination and reject anything outside the target directory.
- **`ADMIN_SECRET_PATH` only selects the accepted account name server-side.** It is not returned by login, not stored by the panel, and not a substitute for authentication.

## 4. Security invariants

- **Never ship a secret in the repository.** No default `JWT_SECRET`, no `DEFAULT_ADMIN_PASS` fallback that boots. `config.py` is fail-closed: a blank signing key raises `RuntimeError`. The launchers (`start-local.py`, `install.bat`, `install.sh`) each generate a unique key; `deploy/docker-compose.yml` has no fallback key.
- **CORS is an explicit origin list** (`CORS_ORIGINS`), never `["*"]` with credentials.
- **Self-update is opt-in** (`ENABLE_SELF_UPDATE`, default off) and shells out with stdout/stderr to `DEVNULL` and `start_new_session=True`.
- **Passwords use `app/core/passwords.py`** (bcrypt, `needs_upgrade`). Do not reintroduce ad-hoc `hmac`/`hashlib` hashing.

## 5. Prompt language (LLM-facing modules are exempt)

Modules that build **instructions for a language model** — `flow_plan`, prompt templates, tool/definition files and their adapters — are exempt from the hardcoded-copy scan: their string literals are model input, not UI copy. This is recorded in `scripts/check_i18n.py` (`PROMPT_FILE_MARKERS`) and that file is the authority; do not copy the marker list here so it cannot drift.

The rule for those modules:

- **Do not translate prompts.** A prompt written in English must stay in English (or its authored language) across all releases. Translating an LLM instruction is not localization — it changes model behaviour — and the four-language parity audit does not apply to it.
- **Do put user-facing strings from those modules into the `api` namespace.** A prompt module may still *return* text a person reads; that text is a locale key like everywhere else. The exemption covers instructions to the model, not copy to the user.

## 6. Testing

- `backend/pytest.ini` + `requirements-dev.txt` make `cd backend && python -m pytest -q` work standalone. `backend/tests/conftest.py` seeds a throwaway `JWT_SECRET` so the fail-closed config does not crash collection in a clean environment (CI included). If you add a test that imports `app`, it must pass with no environment variables set — add the missing seed to `conftest.py`, not to the test.
- **`test_*.py` = collected unit tests.** Live, out-of-ASGI harnesses are named **without** the `test_` prefix and live alongside them: `launcher_live_smoke.py`, `sim_live_smoke.py`, `run_tests.py`. If you rename a live smoke back to `test_*`, pytest will collect and execute its module-level `asyncio.run()` — that is the bug this split exists to prevent.
- The panel has three audit files run by `npm test` (locale audit, token/language header, 401 handling). `npm run build` must stay green.
- CI (`.github/workflows/ci.yml`) runs the locale guardrail, the backend suite, the frontend audits and the Vite build on every push/PR. A green local run that did not run these is not evidence of a green PR.

## 7. Flow versions and imports

`validate_flow` (unknown node types, dangling/duplicate edges, missing trigger, `callback_data` > 64 bytes) runs on **import** and refuses with HTTP 422; a rejected template leaves the stored flow and its `version` counter untouched. Canvas saves are deliberately unrestricted — a half-finished graph is a normal editing state. A compiled `FlowPlan` is cached per `(flow_id, version)`, so an incoming update is a dict lookup, not a re-parse; if you change flow compilation, keep that cache key correct.

## 8. Repository layout (what is real, what is not)

- `backend/locales/` is the **only** backend pack location; the app reads it via `settings.LOCALES_DIR` (`backend/locales`). A copy at `backend/app/locales/` is dead — do not create or edit it.
- `backend/app/plugins/` holds the bundled plugin folders (`broadcast`, `zarinpal`); the community directory is a separate repository: the MyBot Plugins index under the `mybot-studio` organization.
- Docker mounts `../backend/locales` to `/app/locales` in both the panel and the engine containers; changing the pack path requires updating `deploy/docker-compose.yml` in lockstep.
