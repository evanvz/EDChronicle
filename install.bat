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
python -m venv .venv

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt

echo.
echo Installation complete. Run launch.bat to start EDChronicle.
pause
