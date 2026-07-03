@echo off
cd /d "%~dp0"
echo EDChronicle - Install
echo =====================

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    pause
    exit /b 1
)

if exist .venv\Scripts\python.exe (
    echo Virtual environment already exists. Skipping creation.
) else (
    echo Creating virtual environment...
    python -m venv .venv
    if not exist .venv\Scripts\python.exe (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo Installing / updating dependencies...
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt

echo.
echo Installation complete. Run launch.bat to start EDChronicle.
pause
