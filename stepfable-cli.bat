@echo off
rem Command line use, e.g.:
rem   stepfable-cli remesh model.fbx model.step model.stl --preset "presets\01 Sculpt to CNC - smooth STEP.json"
set "PYEXE=%~dp0env\Scripts\python.exe"
if not exist "%PYEXE%" set "PYEXE=%~dp0env\python.exe"
pushd "%~dp0"
"%PYEXE%" -m stepfable %*
popd
