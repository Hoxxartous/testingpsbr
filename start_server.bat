@echo off
REM Restaurant POS - Windows Startup Script
REM Starts the application with Eventlet (Windows Compatible)

echo Starting Restaurant POS with Eventlet Server (Windows Compatible)...
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if virtual environment should be activated
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Install requirements if needed
echo Checking Python requirements...
pip install -r requirements.txt --quiet

REM Start the server with eventlet (Windows compatible)
echo.
echo Starting server...
echo Choose mode:
echo 1. Production Mode (default)
echo 2. Debug Mode (with auto-reload)
echo.
set /p choice="Enter choice (1 or 2, default=1): "

if "%choice%"=="2" (
    echo Starting in DEBUG mode...
    python start_eventlet_server.py --debug %*
) else (
    echo Starting in PRODUCTION mode...
    python start_eventlet_server.py %*
)

pause
