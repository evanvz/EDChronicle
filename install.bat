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
rem Our own copy of the voice packages (github.com/evanvz/EDChronicle-models), used if PyPI no
rem longer has them. Relies on GitHub's expanded_assets page; if that ever breaks, pip only warns.
set EDC_PACKAGES=https://github.com/evanvz/EDChronicle-models/releases/expanded_assets/packages-2026-10
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt --find-links %EDC_PACKAGES%

echo.
echo Downloading voice models (speech voices and voice commands)...
.venv\Scripts\python.exe download_models.py
if errorlevel 1 (
    echo WARNING: A voice model download failed. Without the Kokoro voices, callouts
    echo use the Windows voice; without the Vosk model, voice commands are unavailable.
    echo Re-run install.bat to retry.
)

echo.
echo Creating desktop shortcut...
powershell -NoProfile -Command "try { $ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\EDChronicle.lnk'); $s.TargetPath = '%~dp0launch.bat'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%~dp0assets\edc_icon.ico'; $s.WindowStyle = 7; $s.Save() } catch { exit 1 }"
if errorlevel 1 (
    echo WARNING: Could not create desktop shortcut. You can still run EDChronicle via launch.bat.
) else (
    echo Desktop shortcut created.
)

echo.
echo Installation complete. Run launch.bat to start EDChronicle.
pause
