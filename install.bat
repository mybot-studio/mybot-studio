@echo off
setlocal enabledelayedexpansion
title MyBot Studio - Production Installer

echo ==============================================================================
echo       MyBot Studio ^& Engine — Production Windows Installer
echo ==============================================================================
echo Self-Hosted Visual Telegram Bot Builder (Unreal Engine ^& n8n Style)
echo.

cd /d "%~dp0"

REM 1. Check Docker
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Docker not detected. Please install Docker Desktop for Windows.
    echo If you want to run locally without Docker, use start-local.bat instead.
    echo.
)

REM 2. Prompts
set /p PANEL_PORT="Enter Panel HTTP Port [default: 80]: "
if "%PANEL_PORT%"=="" set PANEL_PORT=80

set /p ADMIN_SECRET_PATH="Enter secret admin panel path [default: panel_adm_x9a2k]: "
if "%ADMIN_SECRET_PATH%"=="" set ADMIN_SECRET_PATH=panel_adm_x9a2k

set /p ADMIN_USER="Enter Admin Username [default: admin]: "
if "%ADMIN_USER%"=="" set ADMIN_USER=admin

set /p ADMIN_PASS="Enter Admin Password [default: admin123456]: "
if "%ADMIN_PASS%"=="" set ADMIN_PASS=admin123456

set /p CF_PROXY_URL="Enter Cloudflare Worker Proxy URL [optional]: "

REM Generate a random per-install JWT signing key so no two installs share it.
REM (A fixed secret would let anyone who reads this repo forge an admin token.)
for /f "usebackq delims=" %%R in (`powershell -NoProfile -Command "$b=New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [BitConverter]::ToString($b)"`) do set "JWT_SECRET=%%R"

(
echo PANEL_PORT=%PANEL_PORT%
echo ADMIN_SECRET_PATH=%ADMIN_SECRET_PATH%
echo DEFAULT_ADMIN_USER=%ADMIN_USER%
echo DEFAULT_ADMIN_PASS=%ADMIN_PASS%
echo JWT_SECRET=%JWT_SECRET%
echo CF_PROXY_URL=%CF_PROXY_URL%
echo HTTP_PROXY=
) > .env

echo.
echo [1/2] Building and launching Docker containers...
docker compose -f deploy/docker-compose.yml up -d --build

echo.
echo ==============================================================================
echo  MyBot Studio ^& Engine successfully installed!
echo ==============================================================================
echo  Admin Panel URL: http://localhost:%PANEL_PORT%/%ADMIN_SECRET_PATH%
echo  Username:        %ADMIN_USER%
echo  Password:        %ADMIN_PASS%
echo ==============================================================================
pause
