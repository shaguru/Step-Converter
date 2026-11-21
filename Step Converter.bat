@echo off
cd /d "%~dp0"
set "PYEXE="
if exist "%~dp0env\Scripts\pythonw.exe" set "PYEXE=%~dp0env\Scripts\pythonw.exe"
if not defined PYEXE if exist "%~dp0env\pythonw.exe" set "PYEXE=%~dp0env\pythonw.exe"
if not defined PYEXE (
    echo StepFable is not set up yet. Run setup.bat first.
    pause
    exit /b 1
)
start "" "%PYEXE%" -m stepfable %*
