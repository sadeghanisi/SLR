@echo off
echo Starting Universal SLR Automation Tool...
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Activate virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo Note: Virtual environment not found. Running with system Python.
    echo Run install_dependencies.bat first for best results.
    echo.
)

REM Check if required modules are installed
python -c "import tkinter" >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: tkinter is not available
    echo Please install Python with tkinter support
    pause
    exit /b 1
)

REM Start the GUI application
python slr_gui.py

if %errorlevel% neq 0 (
    echo.
    echo Error: Failed to start the application
    echo Try running: install_dependencies.bat
    pause
)
