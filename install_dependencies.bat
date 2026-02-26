@echo off
echo ══════════════════════════════════════════════════════════════
echo   Universal SLR Automation Tool — Dependency Installer
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
    if %errorlevel% neq 0 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created successfully.
    echo.
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

echo Installing dependencies from requirements.txt...
echo.
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo WARNING: Some packages may have failed to install.
    echo The tool will still work with available packages.
    echo Missing optional packages will show a warning at runtime.
    echo.
)

echo.
echo ══════════════════════════════════════════════════════════════
echo   Installation complete!
echo ══════════════════════════════════════════════════════════════
echo.
echo To start the tool, double-click: launch_gui.bat
echo   or run: python slr_gui.py
echo.
pause
