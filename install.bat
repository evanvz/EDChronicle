@echo off
cd /d "%~dp0"
echo EDChronicle - Install
echo =====================

set "PYTHON_CMD="
py --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py"
) else (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10 or later from https://www.python.org/downloads/
    echo ^(if already installed, make sure "Add python.exe to PATH" was checked^)
    pause
    exit /b 1
)

if exist .venv\Scripts\python.exe (
    echo Virtual environment already exists. Skipping creation.
) else (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv .venv
    if not exist .venv\Scripts\python.exe (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo Installing / updating dependencies...
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt

echo.
echo Downloading voice command model...
.venv\Scripts\python.exe download_models.py
if errorlevel 1 (
    echo WARNING: Voice command model download failed. Voice commands will be
    echo unavailable until you re-run install.bat successfully.
)

echo.
echo Installation complete. Run launch.bat to start EDChronicle.
pause
