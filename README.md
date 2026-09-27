# MyBot Studio

A self-hosted visual Telegram bot builder with a ReactFlow canvas, FastAPI backend and Aiogram runtime.

[English](README.md) · [فارسی](README.fa.md) · [العربية](docs/README.ar.md) · [Русский](docs/README.ru.md)

> **v0.3-BETA — prerelease, not stable.** Clone from the `master` default branch. Back up existing data before testing.

## What's new in v0.3

This release is a **security and correctness pass** over the v0.2 feature set. The canvas, keyboard and simulator behaviour are unchanged; what changes is how the panel API authenticates, localizes and validates.

- **Default-deny API authentication.** Every `/api` route now requires a backend-issued `Bearer` token, enforced by middleware before route code and by an explicit `require_admin` dependency on every admin router. Only the health, login, webhook, media and i18n-read paths stay public.
- **Fail-closed configuration.** `config.py` no longer ships a guessable `JWT_SECRET` or a `DEFAULT_ADMIN_PASS`; a blank signing key refuses to boot. Installers generate a unique key per install.
- **Localized API responses.** All user-visible API copy resolves from `backend/locales/<code>.json` (`en`, `fa`, `ar`, `ru`) through the caller's `Accept-Language`. Python exception text no longer reaches the browser.
- **Validated flow imports.** `POST /api/flows/{bot}/import` rejects unknown node types, dangling or duplicate edges, a graph without a trigger, and over-long `callback_data` (HTTP 422) before writing; a rejected template leaves the stored flow untouched.
- **SSRF + upload hardening.** Outbound URLs pass a private/loopback guard; language-pack and font uploads validate the derived name and cannot escape their target directory.
- **Test + CI infrastructure.** New backend suites, `pytest.ini`, `requirements-dev.txt`, a `conftest.py` for the fail-closed config, and a CI workflow running the locale guardrail, the backend suite, the frontend audits and the Vite build on every push/PR. See [release notes](docs/releases/v0.3.md).

## Telegram keyboard rules

Each send has **one `reply_markup`**: inline and reply markup cannot be combined in the same request. A reply keyboard already visible in Telegram may remain below a later inline-keyboard message; this does not mean that message contains both. The Keyboard node attaches to its executed message predecessor, not an unrelated message from another branch.

**Message edits support inline keyboards only.** Reply keyboards cannot be attached through Telegram edit methods. Text edits, media-caption edits and inline-markup-only edits use different Telegram methods; a markup-only edit must not send empty text. The simulator is a local approximation, not proof of successful Telegram delivery.

## Installation

### Get the prerelease source

Install Git, then clone the `master` default branch:

```bash
git clone --branch master https://github.com/mybot-studio/mybot-studio.git
cd mybot-studio
```

### Local development — no Docker

Run from the **repository root**, not `backend/` or `frontend/`:

**Windows (CMD / PowerShell)**
```bat
.\start-local.bat
```

**Linux / macOS**
```bash
bash start-local.sh
```

Requirements: Python **3.10+** with `pip` and `venv`, and Node.js **18+** with npm (Vite 5 requirement); a current supported Node LTS is recommended. Put the tools on PATH. `uv` is optional, with pip as fallback. Downloads need network access; live bots need access to Telegram. Self-hosted does not mean Telegram works offline.

Both wrappers invoke **`start-local.py`**. It creates `.env` if absent, prepares `backend/.venv`, installs Python dependencies, smoke-checks backend imports and installs frontend dependencies if `node_modules` is absent. Normal startup launches the API, waits for it at `127.0.0.1:23567`, then starts Vite (normally `http://localhost:23568`). Read terminal errors if startup fails; do not start only the frontend to bypass an API failure.

Dependency/import check only:

```bat
.\start-local.bat --check
```
```bash
bash start-local.sh --check
```

**`--check` does not launch the worker, API or frontend and does not prove service health.** It can create configuration/virtualenv files, install dependencies and import backend code; it is not read-only. The launcher does not fully validate installed dependency versions when `node_modules` already exists.

### Linux VPS / Docker

Use the complete checkout above, review `install.sh`, then run from its root:

```bash
sudo bash install.sh
```

The installer expects sibling `deploy/` and `backend/` files; do not execute a standalone downloaded script through a curl pipe. It prompts for bindings, admin settings and optional proxy configuration and builds Docker services. Its domain/SSL question alone does **not** provision a certificate: configure and verify HTTPS separately. On Windows with Docker/Compose available, review and run `install.bat`; for ordinary local development use `start-local.bat` instead.

This prerelease is not production-hardened. Replace default admin credentials and signing secrets, verify the effective configuration, restrict panel access and back up `.env`, databases and uploads before exposing or upgrading a deployment. Do not publish credentials, bot tokens or private logs. A split worker container is not a zero-downtime guarantee; runtime changes require updating the worker too. See [release notes](docs/releases/v0.3.md) for upgrade caveats.

## Studio workflow

1. Add a bot using your own BotFather token, then open its Studio.
2. Connect a trigger to Send Message and then to Keyboard. Select inline or reply mode; use inline mode after Edit Message.
3. Edit text and keyboards, save, and try commands/callbacks in the simulator. Verify real delivery separately with a test bot.
4. Enable user-variable storage in bot settings before using gated variable/database nodes.

| Action | Shortcut |
| --- | --- |
| Undo graph edit | Ctrl+Z (Cmd+Z on macOS) |
| Redo graph edit | Ctrl+Shift+Z / Ctrl+Y (Cmd equivalents supported) |
| Save flow snapshot | Ctrl+S / Ctrl+Shift+S (Cmd equivalents supported) |

Graph-editor fields share graph history; unrelated settings and simulator text fields retain native text undo. A reload warning depends on browser behavior and is not autosave.

## Architecture, languages and extensions

The panel uses React/Vite and ReactFlow; the Python API and Aiogram worker execute flows with per-bot SQLite storage (`bot_{id}.db`). Docker separates panel and worker services. JSON user variables do not require a separate database server. Proxy configuration can help in restricted networks but does not guarantee connectivity.

English, Persian, Arabic and Russian locale files live in `frontend/src/locales/` for the panel and `backend/locales/` for API and bot-facing messages. The floating preview supports editing and simulation, with minimize/restore controls. Treat preview appearance as approximate.

[MyBot Plugins Directory](https://github.com/mybot-studio/mybot-plugins) contains community extensions and templates. Review third-party code and its permissions before installation.

## Contributing and verification

Open an issue with reproduction steps and redacted logs before proposing a feature. AI agents working in this repository follow the rules in [`AGENTS.md`](AGENTS.md); `scripts/check_i18n.py` is the authority on the localization contract and `AGENTS.md` documents, not overrides, it. CI (`.github/workflows/ci.yml`) runs the same checks listed below; publish actual results, not assumed pass counts. A successful build or dependency check does not verify browser interactions or Telegram delivery.

```bash
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python scripts/check_i18n.py --scan   # locale key parity + no hardcoded API strings
cd backend && python -m pytest -q    # auth guard, locale contract, flow import validation
cd frontend && npm ci && npm test    # token storage, language header, locale audit
cd frontend && npm run build
```

Two rules apply to every API change:

- Every string a person reads is a key under the `api` namespace of `backend/locales/<code>.json`, returned through `t(key, language_from_request(request), ...)`. `scripts/check_i18n.py --scan` fails on a hardcoded English response, a key missing from any of the four languages, or mismatched `{placeholders}`.
- Every `/api` route except `/api/health` and `/api/auth/login` requires a `Bearer` token issued by this backend; the guard middleware enforces this before route code runs, so a newly added route is protected by default. `ADMIN_SECRET_PATH` only selects which account name the login form accepts and never appears in an API response or in the browser.


Maintained by [AradPhpProgrammer](https://github.com/AradPhpProgrammer). Licensed under [AGPL-3.0 with the MyBot Extension & Plugin Exception](LICENSE); modifications to the core remain under AGPL. See the license text for the exception's scope.
