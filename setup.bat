@echo off
setlocal
cd /d "%~dp0"
echo === StepFable setup ===

rem 1) Python launcher with 3.12 or 3.13
set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY (
    py -3.13 -c "import sys" >nul 2>nul && set "PY=py -3.13"
)
if defined PY goto :venv

rem 2) Anaconda
set "CONDA="
if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not defined CONDA if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if defined CONDA goto :conda

echo Could not find Python 3.12/3.13 or Anaconda.
echo Install Python 3.12 from https://www.python.org/downloads/ and run setup.bat again.
goto :fail

:conda
echo Creating a Python 3.12 environment with Anaconda in .\env ...
"%CONDA%" create -y -p "%~dp0env" python=3.12 || goto :fail
set "PYEXE=%~dp0env\python.exe"
goto :install

:venv
echo Creating a virtual environment in .\env with %PY% ...
%PY% -m venv env || goto :fail
set "PYEXE=%~dp0env\Scripts\python.exe"

:install
"%PYEXE%" -m pip install --upgrade pip || goto :fail
"%PYEXE%" -m pip install -r requirements.txt || goto :fail
echo.
echo Setup finished. Double-click StepFable.bat to start the app.
pause
exit /b 0

:fail
echo.
echo Setup failed - see the messages above.
pause
exit /b 1
