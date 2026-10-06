@echo off
setlocal enabledelayedexpansion

:: ======================================================================
:: ATSITS -- Algorithmic Trading Strategy Iteration & Teaching System
:: Windows Startup Launcher for Local Web GUI
:: ======================================================================
:: Purpose:
:: 1. Ensures working directory is set to the ATSITS project root.
:: 2. Resolves active virtual environment (.venv / venv) or system Python.
:: 3. Spawns an asynchronous readiness probe that polls http://127.0.0.1:8000.
:: 4. Automatically opens the user's default browser once the server is ready.
:: 5. Keeps this terminal window active to display real-time logs and errors.
:: ======================================================================

cd /d "%~dp0"

:: 1. Resolve Python executable
set "PYTHON_EXEC=python"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXEC=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXEC=%~dp0venv\Scripts\python.exe"
)

:: 2. Verify Python availability
"%PYTHON_EXEC%" --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Python was not found or is not executable.
    echo Please install Python 3.10+ and ensure it is available on your PATH.
    echo.
    pause
    exit /b 1
)

echo ======================================================================
echo   ATSITS LOCAL WEB GUI LAUNCHER
echo ======================================================================
echo   Target URL:  http://127.0.0.1:8000
echo   Directory:   %CD%
echo   Python:      %PYTHON_EXEC%
echo   Status:      Starting server... (browser will open automatically)
echo ======================================================================

:: 3. Asynchronous readiness poller: waits until server responds before opening browser
start /b "" powershell -NoProfile -Command "$url = 'http://127.0.0.1:8000/api/health'; $timeout = 30; $start = [DateTime]::UtcNow; while (([DateTime]::UtcNow - $start).TotalSeconds -lt $timeout) { try { $res = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 1 -ErrorAction Stop; if ($res.status -eq 'HEALTHY' -or $res.ready -eq $true) { Start-Process 'http://127.0.0.1:8000'; break } } catch { Start-Sleep -Milliseconds 100 } }"

:: 4. Start ATSITS local web server in foreground to maintain log visibility
"%PYTHON_EXEC%" -m atsits web --port 8000 --host 127.0.0.1

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] ATSITS server exited with error code %ERRORLEVEL%.
    pause
)
