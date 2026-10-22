@echo off
setlocal
cd /d "%~dp0"
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" goto configure

echo First run: preparing the local Python environment.
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul
    if errorlevel 1 goto no_python
    py -3 -m venv .venv
) else (
    where python >nul 2>nul
    if errorlevel 1 goto no_python
    python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul
    if errorlevel 1 goto no_python
    python -m venv .venv
)
if errorlevel 1 goto setup_failed
if not exist "%VENV_PYTHON%" goto setup_failed

:configure
if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    if errorlevel 1 goto setup_failed
)

"%VENV_PYTHON%" -c "import bs4, chromadb, fastapi, httpx, openai, pydantic_settings, dotenv, sqlalchemy, uvicorn" >nul 2>nul
if errorlevel 1 (
    echo Installing required packages. This may take a few minutes on first run...
    "%VENV_PYTHON%" -m pip install -e .
    if errorlevel 1 goto setup_failed
)

echo Starting AI PM Learning Copilot. Keep this window open while using it.
echo The browser will open automatically when the app is ready.
"%VENV_PYTHON%" "scripts\start_local.py"
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" pause
exit /b %APP_EXIT_CODE%

:no_python
echo Python 3.11 or newer was not found. Install Python, then double-click this file again.
echo During installation, enable the option to add Python to PATH.
pause
exit /b 1

:setup_failed
echo Setup or startup failed. Read the message above, then try this file again.
pause
exit /b 1
