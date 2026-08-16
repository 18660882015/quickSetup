@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM MVP AI Deploy Assistant - Stop Service Script
REM ============================================================

title MVP AI Deploy Assistant - Stop

set "TARGET_PORT=8080"

echo.
echo ============================================================
echo   MVP AI Deploy Assistant - Stop Service
echo ============================================================
echo.
echo Looking for processes on port %TARGET_PORT%...
echo.

REM ------------------------------------------------------------
REM Find PIDs listening on target port
REM ------------------------------------------------------------
set "FOUND_PID="

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%TARGET_PORT% " ^| findstr "LISTENING"') do (
    set "CURRENT_PID=%%p"
    if not "!CURRENT_PID!"=="0" (
        if "!FOUND_PID!"=="" (
            set "FOUND_PID=!CURRENT_PID!"
        ) else (
            set "FOUND_PID=!FOUND_PID! !CURRENT_PID!"
        )
    )
)

if "!FOUND_PID!"=="" (
    echo No process found on port %TARGET_PORT%, service may not be running.
    echo.
    goto :check_uvicorn
)

echo Found process PID(s) on port %TARGET_PORT%: !FOUND_PID!
echo.

REM ------------------------------------------------------------
REM Kill each process
REM ------------------------------------------------------------
for %%p in (!FOUND_PID!) do (
    echo Killing process PID: %%p
    for /f "tokens=1" %%n in ('tasklist /fi "PID eq %%p" /nh /fo csv 2^>nul ^| findstr %%p') do (
        echo   Process: %%n
    )
    taskkill /F /PID %%p >nul 2>&1
    if errorlevel 1 (
        echo   [WARN] Failed to kill process %%p, may need admin privileges.
    ) else (
        echo   Process %%p terminated.
    )
)

echo.

:check_uvicorn
REM ------------------------------------------------------------
REM Fallback: find and kill all uvicorn-related processes
REM ------------------------------------------------------------
echo Checking for remaining uvicorn processes...
set "UVICORN_PIDS="
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq python.exe" /nh /fo csv 2^>nul ^| findstr python.exe') do (
    set "PY_PID=%%p"
    set "PY_PID=!PY_PID:"=!"
    if not "!PY_PID!"=="" (
        for /f "delims=" %%c in ('wmic process where "ProcessId=!PY_PID!" get CommandLine /value 2^>nul ^| findstr /i "uvicorn"') do (
            echo   Found uvicorn process PID: !PY_PID!
            if "!UVICORN_PIDS!"=="" (
                set "UVICORN_PIDS=!PY_PID!"
            ) else (
                set "UVICORN_PIDS=!UVICORN_PIDS! !PY_PID!"
            )
        )
    )
)

if "!UVICORN_PIDS!"=="" (
    echo No remaining uvicorn processes found.
) else (
    for %%p in (!UVICORN_PIDS!) do (
        echo Killing uvicorn process PID: %%p
        taskkill /F /PID %%p >nul 2>&1
        if errorlevel 1 (
            echo   [WARN] Failed to kill process %%p.
        ) else (
            echo   Process %%p terminated.
        )
    )
)

echo.
echo ============================================================
echo   Service stop complete.
echo ============================================================
echo.
echo To restart, run start.bat
echo.
endlocal
exit /b 0
