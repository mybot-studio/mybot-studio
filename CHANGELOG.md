# Changelog

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
