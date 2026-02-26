@echo off
echo ══════════════════════════════════════════════════════════════
echo   Universal SLR Automation Tool — Quick Setup
echo ══════════════════════════════════════════════════════════════
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

REM Create virtual environment if it doesn't exist
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate and install
call .venv\Scripts\activate.bat
echo Installing all dependencies...
pip install -r requirements.txt

echo.
echo Setup complete! Run launch_gui.bat to start the tool.
echo.
pause
