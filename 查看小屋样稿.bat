@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "ROOM_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%ROOM_PY%" (
  start "" "%ROOM_PY%" "%~dp0room_preview_viewer.py"
  exit /b
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0room_preview_viewer.py"
  exit /b
)
start "" py -3 -w "%~dp0room_preview_viewer.py"
