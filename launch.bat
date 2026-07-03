@echo off
cd /d "%~dp0"

if not exist .venv\Scripts\pythonw.exe (
    echo ERROR: Virtual environment not found.
    echo Please run install.bat first.
    pause
    exit /b 1
)

start "" .venv\Scripts\pythonw.exe main.py
