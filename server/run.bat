@echo off
REM 启动 dePixPin 伪有道 API 服务（HTTPS:443，仅监听本机）
cd /d "%~dp0.."
python -X utf8 server\app.py --https
pause
