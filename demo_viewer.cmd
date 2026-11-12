@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv314\Scripts\python.exe" (
  call setup_windows.cmd
  if errorlevel 1 exit /b 1
)
".venv314\Scripts\python.exe" -m cnc_sim examples\demo.nc --stock 30 20 6 --tools examples\tools.json --machine examples\machine.template.json --start 0 0 5 --output demo_result.npy --visualize
exit /b %errorlevel%
