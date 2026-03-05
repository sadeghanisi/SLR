@echo off
REM SLR Web Application — Launch Script
REM Activates the project virtual environment and starts the Flask server.

cd /d "%~dp0"

REM Check for .venv in parent directory
IF EXIST "..\\.venv\\Scripts\\activate.bat" (
    echo [INFO] Activating virtual environment...
    call "..\\.venv\\Scripts\\activate.bat"
) ELSE (
    echo [WARN] No .venv found — using system Python.
    echo [WARN] If you get module errors, run:  pip install flask flask-cors
)

echo [INFO] Starting SLR Web App at http://127.0.0.1:5000
echo [INFO] Press Ctrl+C to stop.
echo.
python app.py
