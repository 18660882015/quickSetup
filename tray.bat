@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM MVP AI Deploy Assistant - System Tray Startup (optional)
REM Requires: pip install pystray pillow
REM Falls back to console mode if pystray is not installed.
REM ============================================================

title MVP AI Deploy Assistant (Tray)

set "PROJECT_ROOT=%~dp0"
set "AGENT_DIR=%PROJECT_ROOT%mvp-agent"

set "PYTHON_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    set "PYTHON_CMD=py"
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
        pause
        exit /b 1
    )
)

if not exist "%AGENT_DIR%\data\db" mkdir "%AGENT_DIR%\data\db"
if not exist "%AGENT_DIR%\data\deployments" mkdir "%AGENT_DIR%\data\deployments"
if not exist "%AGENT_DIR%\data\backups" mkdir "%AGENT_DIR%\data\backups"
if not exist "%AGENT_DIR%\data\logs" mkdir "%AGENT_DIR%\data\logs"

echo [tray] Starting MVP AI Deploy Assistant with tray icon...
echo [tray] URL: http://localhost:8080

pushd "%AGENT_DIR%"
!PYTHON_CMD! tray.py
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Tray startup failed, exit code: %EXIT_CODE%
    pause
)

endlocal
exit /b %EXIT_CODE%
