#!/usr/bin/env python3
"""
MyBot Studio — Local Runner (cross-platform).
This is the robust launcher. start-local.bat / start-local.sh are thin
wrappers that invoke this script, so Windows "cmd parenthesis hell" is
completely avoided.

Windows / Linux / macOS with a single code path.
"""
import os
import sys
import subprocess
import time
import shutil
import socket
import json
import webbrowser
import secrets
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / (".venv/Scripts" if os.name == "nt" else ".venv/bin")
PY = VENV / ("python.exe" if os.name == "nt" else "python")
PIP = VENV / ("python.exe" if os.name == "nt" else "python")

HOST = "127.0.0.1"
PORT = 23567
FE_PORT = 23568
SECRET_PATH = "panel_adm_x9a2k"
ADMIN_USER = "admin"
ADMIN_PASS = "admin1234"


def info(msg: str):
    print(f"[INFO] {msg}")


def ok(msg: str):
    print(f"[OK]   {msg}")


def warn(msg: str):
    print(f"[WARN] {msg}")


def err(msg: str):
    print(f"[ERR]  {msg}")


def run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def run_check(cmd, **kw) -> bool:
    try:
        r = run(cmd, **kw)
        return r.returncode == 0
    except FileNotFoundError:
        return False


def require(cmd: list, msg: str) -> bool:
    if run_check(cmd):
        ok(msg)
        return True
    err("Missing / broken: " + msg)
    return False


def port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Conflict detection includes non-HTTP listeners and unhealthy services."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ready(host: str, port: int, *, backend=False, timeout=2.0) -> bool:
    """Probe loopback directly, ignoring system/environment HTTP proxies."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://{host}:{port}/", timeout=timeout) as response:
            if response.status != 200:
                return False
            if not backend:
                return True
            if response.headers.get_content_type() != "application/json":
                return False
            payload = json.loads(response.read(65536))
            return isinstance(payload, dict) and payload.get("status") == "online"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main():
    print("=" * 80)
    print("  MyBot Studio - Local Runner")
    print("=" * 80)

    # --------------------------------------------------------------
    # STEP 0: Prerequisites
    # --------------------------------------------------------------
    print()
    info("Checking prerequisites...")

    python3 = None
    for cand in (["python3", "--version"], ["python", "--version"]):
        if run_check(cand, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
            python3 = cand[0]
            break
    if not python3:
        err("Python 3 is not installed or not in PATH.")
        err("Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add to PATH').")
        input("\nPress Enter to close...")
        return 1
    ok("Python detected.")

    if not run_check([python3, "-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL):
        err("pip is not available.")
        input("\nPress Enter to close...")
        return 1
    ok("pip detected.")

    if not shutil.which("node"):
        err("Node.js is not installed or not in PATH (https://nodejs.org/).")
        input("\nPress Enter to close...")
        return 1
    ok("Node.js detected.")

    if not shutil.which("npm"):
        err("npm is not available.")
        input("\nPress Enter to close...")
        return 1
    ok("npm detected.")

    use_uv = shutil.which("uv") is not None
    ok(f"uv {'detected (fast installs)' if use_uv else 'not found (using pip)'}.")

    # --------------------------------------------------------------
    # STEP 1: Create .env
    # --------------------------------------------------------------
    if not (ROOT / ".env").exists():
        info("Creating .env configuration...")
        jwt_key = secrets.token_hex(32)
        (ROOT / ".env").write_text(
            "PANEL_PORT=" + str(FE_PORT) + "\n"
            "ADMIN_SECRET_PATH=" + SECRET_PATH + "\n"
            "DEFAULT_ADMIN_USER=" + ADMIN_USER + "\n"
            "DEFAULT_ADMIN_PASS=" + ADMIN_PASS + "\n"
            "JWT_SECRET=" + jwt_key + "\n"
            "CF_PROXY_URL=\n"
            "HTTP_PROXY=\n",
            encoding="utf-8",
        )
        ok(".env created.")
    else:
        ok(".env found.")

    # --------------------------------------------------------------
    # STEP 2: Create venv
    # --------------------------------------------------------------
    if not PY.exists():
        info("Creating Python virtual environment...")
        if use_uv:
            run_check(["uv", "venv", str(BACKEND / ".venv")])
        else:
            run_check([python3, "-m", "venv", str(BACKEND / ".venv")])
        if not PY.exists():
            err("Failed to create virtual environment.")
            input("\nPress Enter to close...")
            return 1
    ok("Virtual environment ready.")

    # --------------------------------------------------------------
    # STEP 3: Install Python dependencies
    # --------------------------------------------------------------
    info("Installing Python dependencies...")
    installed = False
    if use_uv:
        installed = run_check(
            ["uv", "pip", "install", "-r", str(BACKEND / "requirements.txt"),
             "--python", str(PY)],
            stdout=subprocess.DEVNULL,
        )
    if not installed:
        run_check([str(PIP), "-m", "pip", "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL)
        installed = run_check(
            [str(PIP), "-m", "pip", "install", "-r", str(BACKEND / "requirements.txt")],
        )
    if not installed:
        err("Python dependency installation failed.")
        input("\nPress Enter to close...")
        return 1
    ok("Python dependencies installed.")

    # --------------------------------------------------------------
    # STEP 4: Smoke-test backend imports
    # --------------------------------------------------------------
    info("Verifying backend imports...")
    if not run_check([str(PY), "-c", "from app.main import app; print('BACKEND_OK')"],
                     cwd=str(BACKEND), stdout=subprocess.DEVNULL):
        err("Backend import check failed.")
        input("\nPress Enter to close...")
        return 1
    ok("Backend imports verified.")

    # --------------------------------------------------------------
    # STEP 5: Frontend dependencies
    # --------------------------------------------------------------
    if not (FRONTEND / "node_modules").exists():
        info("Installing frontend dependencies (npm install)...")
        if not run_check(["npm", "install"], cwd=str(FRONTEND), shell=(os.name == "nt")):
            err("npm install failed.")
            input("\nPress Enter to close...")
            return 1
    ok("Frontend dependencies ready.")

    if "--check" in sys.argv or "--dry-run" in sys.argv:
        print()
        ok("All prerequisites, dependencies, and imports verified successfully!")
        return 0

    # --------------------------------------------------------------
    # STEP 6: Never stop services we did not start.
    # --------------------------------------------------------------
    for port in (PORT, FE_PORT):
        if port_open(HOST, port, timeout=0.5):
            err(f"Port {port} is already in use. Stop that service yourself or use its existing UI.")
            return 1

    return start_services()


def start_services():
    """Own only these children; always clean up on startup/runtime failure."""
    procs = []

    def spawn(cmd, cwd, name, shell=False):
        info(f"Starting {name}...")
        kw = {"cwd": str(cwd), "shell": shell}
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        else:
            kw["start_new_session"] = True
        process = subprocess.Popen(cmd, **kw)
        procs.append((name, process))
        return process

    def check_children():
        for name, process in procs:
            code = process.poll()
            if code is not None:
                raise RuntimeError(f"{name} exited unexpectedly (code {code}).")

    def wait_ready(port, name, backend=False):
        info(f"Waiting for {name} HTTP readiness...")
        for attempt in range(15):
            check_children()
            if http_ready(HOST, port, backend=backend):
                check_children()
                return
            time.sleep(2)
        raise RuntimeError(f"{name} did not become healthy within 15 checks.")

    try:
        # app.main lifespan owns polling workers; bot_worker is not a CLI.
        info("Bot polling is managed by the Backend API.")
        spawn([str(PY), "-m", "uvicorn", "app.main:app", "--host", HOST,
               "--port", str(PORT), "--reload"], BACKEND, "Backend API")
        wait_ready(PORT, "Backend", backend=True)
        # strictPort prevents Vite silently selecting a different URL.
        spawn(["npm", "run", "dev", "--", "--host", HOST,
               "--port", str(FE_PORT), "--strictPort"], FRONTEND, "Frontend",
              shell=(os.name == "nt"))
        wait_ready(FE_PORT, "Frontend")
        ok("MyBot Studio is ready!")
        info(f"UI: http://{HOST}:{FE_PORT}")
        info("Use the administrator credentials configured in .env. Ctrl+C stops services.")
        try:
            webbrowser.open(f"http://{HOST}:{FE_PORT}")
        except Exception:
            warn("Could not open a browser; use the UI URL above.")
        while True:
            check_children()
            time.sleep(1)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError) as exc:
        err(str(exc))
        return 1
    finally:
        info("Stopping launcher-owned services...")
        for name, process in reversed(procs):
            try:
                if os.name == "nt":
                    # Limit tree cleanup to the PIDs returned by our own Popen.
                    if process.poll() is None:
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    process.kill()
                    process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                warn(f"Could not fully stop {name}; check its console.")


if __name__ == "__main__":
    sys.exit(main())