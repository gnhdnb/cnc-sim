@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
py -3.14 -m venv .venv314
if errorlevel 1 (
  echo Install 64-bit Python 3.14 from https://www.python.org/downloads/windows/ and run this again.
  exit /b 1
)
".venv314\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv314\Scripts\python.exe" -m pip install ".[viewer]"
if errorlevel 1 exit /b 1
echo Installed. Run demo_viewer.cmd or use .venv314\Scripts\python.exe -m cnc_sim --help
