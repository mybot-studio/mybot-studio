# Changelog

## v0.3-BETA — Prerelease (API hardening, full localization, import validation)

Application metadata: `0.3.0` (backend `VERSION` and `frontend/package.json` aligned). Published as a GitHub prerelease; not a stable release.

### Security

- **Every `/api` route now requires a backend-issued `Bearer` token.** A default-deny guard in `app/main.py` runs before route code; only `/api/health`, `/api/auth/login`, the webhook/media paths and the i18n read endpoints stay public. Forged, expired or anonymous requests get HTTP 401 with `WWW-Authenticate: Bearer`. Each admin router also carries an explicit `require_admin` dependency, so a route added later is protected even if the middleware is bypassed.
- **Fail-closed configuration.** `config.py` no longer ships a guessable default `JWT_SECRET` or a `DEFAULT_ADMIN_PASS`; a blank signing key raises `RuntimeError` at boot instead of running on a shared secret. CORS is now an explicit origin list (`CORS_ORIGINS`), never `["*"]` with credentials.
- **Outbound SSRF guard.** `app/core/net.py` adds `validate_outbound_url` + `UrlPolicyError`: scheme, host, private/loopback IP and the `ALLOW_PRIVATE_URLS` opt-in are enforced for proxy and Cloudflare-Worker settings before any connection.
- **Password handling moved to `app/core/passwords.py`** (bcrypt, `needs_upgrade`), replacing ad-hoc `hmac`/`hashlib` in `auth.py`.
- **Login throttling.** `LoginAttemptTracker` in `app/core/security.py` rate-limits the single admin account by username + client IP (`LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_SECONDS`).
- **Self-update is opt-in.** `ENABLE_SELF_UPDATE` defaults to false; the update endpoint returns 403 unless enabled, and now shells out with `DEVNULL` stdout/stderr and `start_new_session=True`.
- **Upload path-traversal fixes.** `i18n.py` and `fonts.py` validate the language-code / font-id, resolve the destination and reject anything outside the target directory; `fonts.py` restricts extensions and sanitizes the stored `font_id`.
- **`ADMIN_SECRET_PATH` is no longer returned** by login or read by the panel; it only selects the accepted account name server-side.
- **Installers generate a random `JWT_SECRET`** instead of a repo-visible constant: `start-local.py` uses `secrets.token_hex(32)`; `install.bat` uses a PowerShell `RandomNumberGenerator`; `install.sh` was already random; `deploy/docker-compose.yml` now fails closed with no fallback key.

### API & internationalization

- **All user-visible API copy is localized** from `backend/locales/<code>.json` (the `api` namespace) across `en`, `fa`, `ar`, `ru` for the auth, bot, flow, font, language-pack, system, simulator and webhook endpoints, resolved via `t(key, language_from_request(request), ...)`.
- **Errors no longer leak Python internals.** `simulator.py` logs the traceback server-side and returns a translated `api.simulator.failed` sentence; `language_code` is taken from the request, not hardcoded.
- **New localization core.** `app/core/i18n.py` (`t`, `language_from_request`, `reload_locales`, `supported_languages`); `Accept-Language` drives the pack, with a fixed fallback chain.

### Flow import validation

- **`POST /api/flows/{bot}/import` validates before writing.** `app/core/flow_plan.py::validate_flow` rejects unknown node types, dangling or duplicate edges, a graph without a trigger, and `callback_data` longer than Telegram's 64-byte limit (HTTP 422). A rejected template leaves the stored flow and its `version` untouched. Canvas saves are deliberately unrestricted, since a half-finished graph is a normal editing state. A compiled `FlowPlan` is cached per `(flow_id, version)` so an incoming update costs a lookup, not a full re-parse.

### Panel & frontend

- **`authFetch` wraps every request** with the bearer token, `Accept-Language` and credentials; the token/language live under the exact keys the UI reads. The first 401 clears the session and dispatches `mybot:unauthorized` (the `App` listener logs out) instead of retrying a dead token.
- **Frontend `package.json` test script** added so `npm test` runs the three `.test.mjs` audits (locale audit, token/language header, 401 handling).

### Testing, CI & docs

- **New backend tests:** `test_auth_required.py` (public paths, forged/expired tokens, localized 401), `test_flow_import_validation.py` (validation + "rejected import leaves the flow untouched"), `test_i18n_contract.py` (no duplicate JSON keys, key/`{placeholder}` parity, declared writing direction).
- **`backend/pytest.ini` + `requirements-dev.txt`** make `cd backend && python -m pytest` work standalone. `backend/tests/conftest.py` seeds a throwaway `JWT_SECRET` so the fail-closed config does not crash collection in a clean CI environment.
- **`test_sim_live.py` → `sim_live_smoke.py`**, fixed to the new three-argument `dispatch_simulation_event(req, request, db)` signature; it is a live, out-of-ASGI harness and is no longer collected by pytest.
- **Dead `backend/app/locales/` removed** (stale copies; the app reads `backend/locales/` via `settings.LOCALES_DIR`).
- **`.github/workflows/ci.yml`** runs the locale guardrail, the backend suite, the frontend audits and the Vite build on every push/PR. `scripts/check_i18n.py --scan` now ignores metadata kwargs, status tokens and stored data defaults, reporting only real hardcoded copy.

## Unreleased — API authentication, localized responses, locale parity

- Every `/api` route except `/api/health` and `/api/auth/login` now requires a `Bearer` token issued by this backend, enforced by middleware before route code runs; forged, expired and anonymous requests get HTTP 401.
- `admin_secret_path` is no longer returned by login or stored by the panel; it only selects the accepted account name server-side.
- Imported flow templates are validated before anything is written: unknown node types, dangling or duplicate edges, a graph without a trigger, and `callback_data` longer than Telegram accepts are refused with HTTP 422, and the stored flow keeps its previous content. Saving from the canvas is not restricted, because a half-finished graph is a normal editing state.
- Responses from the auth, bot, flow, font, language-pack, system, simulator and webhook endpoints are localized from `backend/locales/<code>.json` (the `api` namespace). Python exception text no longer reaches the browser; tracebacks go to the server log and the panel gets a translated sentence. The plugin endpoint returns manifest data only and has no messages of its own.
- The panel stores its token under the key the rest of the UI reads, sends `Accept-Language` on every request, and clears the session on the first 401 instead of retrying with a dead token.
- `scripts/check_i18n.py --scan` now ignores metadata keyword arguments, protocol status tokens and stored data defaults, so it reports real hardcoded copy instead of Pydantic field docs.
- Added `backend/tests/`: `test_auth_required.py` (public paths, forged/expired tokens, localized 401), `test_i18n_contract.py` (no duplicate JSON keys, key and `{placeholder}` parity, declared writing direction) and `test_flow_import_validation.py` (unknown types, dangling edges, callback size, rejected import leaves the stored flow untouched).
- Added `backend/pytest.ini`, `backend/requirements-dev.txt` and a CI workflow so the locale guardrail, backend tests and frontend audits run on every push.

## v0.2 — Prerelease (prepared; not a stable release)

- Dedicated Keyboard node and shared inline/reply editor with keyboard connection validation.
- Responsive layout, RTL and theme refinements for the editor and floating preview.
- Graph-wide undo/redo and snapshot-aware saves that preserve edits made during saving.
- Correct canvas insertion coordinates after zoom/pan; explicit inline-only message-edit rules.
- Updated all six existing README files across English, Persian, Arabic and Russian; documented root launchers, dependency-only `--check`, and the intended `main` migration.
- Aligned frontend and backend application version metadata to `0.2.0`; release maturity is recorded with the GitHub prerelease flag.

See [full release notes and upgrade caveats](docs/releases/v0.2.md). Publication and final execution evidence belong to the release process, not this prepared changelog.

## Earlier history

The existing v0.1 work remains in repository history. This changelog does not invent a publication date, tag or verification result for it.
