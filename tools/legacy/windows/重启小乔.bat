@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/4] 结束正在运行的小乔...
powershell -NoProfile -Command ^
 "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*pet.py*' -and $_.Name -like 'python*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo [2/4] 恢复存档(旧版退出时会把它清空)...
for %%A in (pet_settings.json) do if %%~zA LSS 5 (
  if exist pet_settings.restore.json copy /y pet_settings.restore.json pet_settings.json >nul
)

echo [3/4] 找 Python...
set "PYW="
if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe" set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
if not defined PYW for /f "delims=" %%P in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%P"
if not defined PYW (
  echo    没找到 pythonw.exe,改用 py -w
  start "" py -3 -w "%~dp0pet.py"
) else (
  echo    用 %PYW%
  start "" "%PYW%" "%~dp0pet.py"
)

echo [4/4] 已启动。3 秒后自动关闭这个窗口。
timeout /t 3 /nobreak >nul
