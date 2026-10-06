@echo off
rem 双机会话灯同步:把 Mac 上 AIQuota 的会话状态拉给小乔(常驻,最小化)
rem 开机自启想加的话:shell:startup 里放一个指向本脚本的快捷方式
set "PYW=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
start "ai-session-sync" /min "%PYW%" "%~dp0mac_session_sync.py" --loop
