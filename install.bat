@echo off
echo EDChronicle - Install
echo =====================

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Creating virtual environment...
if exist .venv rmdir /s /q .venv >nul 2>&1
python -m venv .venv >nul 2>&1
if not exist .venv\Scripts\python.exe (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

echo Installing dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo Installation complete. Run launch.bat to start EDChronicle.
pause
