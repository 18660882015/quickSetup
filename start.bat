@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM MVP AI Deploy Assistant - Windows Startup Script
REM ============================================================

title MVP AI Deploy Assistant

REM Project root directory (mvp\)
set "PROJECT_ROOT=%~dp0"
set "AGENT_DIR=%PROJECT_ROOT%mvp-agent"
set "FRONTEND_DIR=%PROJECT_ROOT%mvp-frontend"
set "DATA_DIR=%AGENT_DIR%\data"

echo.
echo ============================================================
echo   MVP AI Deploy Assistant - Starting...
echo ============================================================
echo.
echo Project Root: %PROJECT_ROOT%
echo.

REM ------------------------------------------------------------
REM 1. Check Python environment
REM ------------------------------------------------------------
echo [1/7] Checking Python environment...

set "PYTHON_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    set "PYTHON_CMD=py"
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
        echo         Download: https://www.python.org/downloads/
        goto :error_exit
    )
)

for /f "tokens=2 delims= " %%v in ('!PYTHON_CMD! --version 2^>^&1') do set "PY_VERSION=%%v"
echo       Python Version: %PY_VERSION%

for /f "tokens=1,2 delims=." %%a in ("%PY_VERSION%") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)

if not "%PY_MAJOR%"=="3" (
    echo [ERROR] Requires Python 3.10+, current is %PY_VERSION%
    goto :error_exit
)
if %PY_MINOR% LSS 10 (
    echo [ERROR] Requires Python 3.10+, current is %PY_VERSION%
    goto :error_exit
)
echo       Python check passed.
echo.

REM ------------------------------------------------------------
REM 2. Check Node.js environment
REM ------------------------------------------------------------
echo [2/7] Checking Node.js environment...
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+ and add to PATH.
    echo         Download: https://nodejs.org/
    goto :error_exit
)

for /f "delims=" %%v in ('node --version 2^>^&1') do set "NODE_VERSION=%%v"
echo       Node.js Version: %NODE_VERSION%

set "NODE_VERSION_NUM=%NODE_VERSION:~1%"
for /f "tokens=1 delims=." %%a in ("%NODE_VERSION_NUM%") do set "NODE_MAJOR=%%a"

for /f "tokens=* delims=0123456789" %%a in ("!NODE_MAJOR!") do (
    set "NON_NUM=%%a"
)
if defined NON_NUM (
    echo       Node.js version parse skipped strict check.
) else (
    if !NODE_MAJOR! LSS 18 (
        echo [ERROR] Requires Node.js 18+, current is %NODE_VERSION%
        goto :error_exit
    )
)
echo       Node.js check passed.
echo.

REM ------------------------------------------------------------
REM 3. Install Python dependencies
REM ------------------------------------------------------------
echo [3/7] Installing Python dependencies...
if not exist "%AGENT_DIR%\requirements.txt" (
    echo [ERROR] Not found: %AGENT_DIR%\requirements.txt
    goto :error_exit
)

!PYTHON_CMD! -m pip install -r "%AGENT_DIR%\requirements.txt" -q
if errorlevel 1 (
    echo [WARN] Some dependencies may have failed, trying to continue...
) else (
    echo       Python dependencies installed.
)
echo.

REM ------------------------------------------------------------
REM 4. Install frontend dependencies and build
REM ------------------------------------------------------------
echo [4/7] Building frontend...
if not exist "%FRONTEND_DIR%\package.json" (
    echo [ERROR] Not found: %FRONTEND_DIR%\package.json
    goto :error_exit
)

pushd "%FRONTEND_DIR%"

if not exist "node_modules" (
    echo       Running npm install...
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed
        popd
        goto :error_exit
    )
) else (
    echo       node_modules exists, skipping npm install.
)

echo       Running npm run build...
call npm run build
if errorlevel 1 (
    echo [ERROR] Frontend build failed
    popd
    goto :error_exit
)
popd
echo       Frontend build complete.
echo.

REM ------------------------------------------------------------
REM 5. Initialize .env config file
REM ------------------------------------------------------------
echo [5/7] Checking .env config file...
if not exist "%AGENT_DIR%\.env" (
    if exist "%AGENT_DIR%\.env.example" (
        copy "%AGENT_DIR%\.env.example" "%AGENT_DIR%\.env" >nul
        echo       Created .env from .env.example.
        echo       NOTE: Replace AES_SECRET_KEY and JWT_SECRET with random keys.
        echo       Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ) else (
        echo [WARN] .env.example not found, please create .env manually.
    )
) else (
    echo       .env file exists, skipping.
)
echo.

REM ------------------------------------------------------------
REM 6. Create data directories
REM ------------------------------------------------------------
echo [6/7] Creating data directories...
if not exist "%DATA_DIR%\db" mkdir "%DATA_DIR%\db"
if not exist "%DATA_DIR%\deployments" mkdir "%DATA_DIR%\deployments"
if not exist "%DATA_DIR%\backups" mkdir "%DATA_DIR%\backups"
if not exist "%DATA_DIR%\logs" mkdir "%DATA_DIR%\logs"
if not exist "%DATA_DIR%\chunks" mkdir "%DATA_DIR%\chunks"
if not exist "%PROJECT_ROOT%\data\deployments" mkdir "%PROJECT_ROOT%\data\deployments"
echo       Data directories ready.
echo.

REM ------------------------------------------------------------
REM 7. Start FastAPI service
REM ------------------------------------------------------------
echo [7/7] Starting FastAPI service...
echo.
echo ============================================================
echo   Starting service, please wait...
echo ============================================================
echo.
echo   URL:           http://localhost:8080
echo   Swagger Docs:  http://localhost:8080/docs
echo   ReDoc Docs:    http://localhost:8080/redoc
echo.
echo   Username:      admin
echo   Password:      admin123
echo.
echo   First start will auto-init database (--init-db).
echo   Press Ctrl+C to stop the service.
echo ============================================================
echo.

pushd "%AGENT_DIR%"
!PYTHON_CMD! run.py --init-db
if errorlevel 1 (
    echo [ERROR] Database init failed
    popd
    goto :error_exit
)
popd

pushd "%AGENT_DIR%"
!PYTHON_CMD! run.py --host 0.0.0.0 --port 8080
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Service start failed, exit code: %EXIT_CODE%
    goto :error_exit
)

goto :success_exit

:error_exit
echo.
echo ============================================================
echo   Startup failed. Please check the errors above.
echo ============================================================
echo.
endlocal
exit /b 1

:success_exit
echo.
echo ============================================================
echo   Service stopped.
echo ============================================================
echo.
endlocal
exit /b 0
