@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM dePixPin 一键安装
REM   1. hosts 指向   2. 安装根证书   3. 注册开机自启   4. 自测
REM 便携包根目录运行；开发环境在 tools\ 下也能跑
REM ============================================================

REM --- 自动提权 ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

REM --- 路径解析 ---
set "ROOT=%~dp0"
if exist "%ROOT%depixpin.exe" (
    set "RUNNER=%ROOT%depixpin.exe"
) else if exist "%ROOT%server\app.py" (
    set "RUNNER=%ROOT%server\run_silent.vbs"
) else if exist "%ROOT%..\server\app.py" (
    set "ROOT=%~dp0..\"
    set "RUNNER=%ROOT%server\run_silent.vbs"
) else (
    echo [错误] 找不到 depixpin.exe 或 server\app.py
    pause & exit /b 1
)
set "CERT=%ROOT%certs\depixpin-ca.crt"
if not exist "%CERT%" set "CERT=%ROOT%server\certs\depixpin-ca.crt"

echo ========================================
echo  dePixPin 安装程序
echo  运行器: %RUNNER%
echo ========================================

REM --- 1. hosts ---
echo [1/4] 配置 hosts...
set "HOSTS=%SystemRoot%\System32\drivers\etc\hosts"
findstr /C:"dePixPin" "%HOSTS%" >nul 2>&1
if %errorlevel%==0 (echo     已存在，跳过) else (
    copy "%HOSTS%" "%HOSTS%.bak-%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%" >nul
    (
        echo.
        echo # ^>^>^> dePixPin ^>^>^>
        echo 127.0.0.1 openapi.youdao.com
        echo # ^<^<^< dePixPin ^<^<^<
    ) >> "%HOSTS%"
    echo     已添加: 127.0.0.1 openapi.youdao.com
)

REM --- 2. 证书 ---
echo [2/4] 安装根证书...
certutil -addstore -f Root "%CERT%" >nul 2>&1
if %errorlevel%==0 (echo     dePixPin Root CA 已信任) else (echo     [警告] 证书安装失败 & goto :fail)

REM --- 3. 开机自启（任务计划程序，SYSTEM 权限）---
echo [3/4] 注册开机自启任务...
if /i "%RUNNER:~-4%"==".exe" (
    set "TASKCMD=\"%RUNNER%\" --https"
) else (
    set "TASKCMD=\"%RUNNER%\""
)
schtasks /create /tn "dePixPin" /sc onstart /ru SYSTEM /rl highest /tr "!TASKCMD!" /f >nul 2>&1
if %errorlevel% neq 0 (echo     [警告] 任务注册失败，可手动运行: %RUNNER%) else (echo     任务 dePixPin 已注册)

REM --- 4. 立即启动 + 自测 ---
echo [4/4] 启动服务并自测...
schtasks /run /tn "dePixPin" >nul 2>&1
if /i not "%RUNNER:~-4%"==".exe" if not exist "%ROOT%depixpin.exe" start "" /min "%RUNNER%" >nul 2>&1
timeout /t 3 /nobreak >nul
curl -s --ssl-no-revoke -o nul -w "HTTP %%{http_code}" --max-time 10 https://openapi.youdao.com/healthz > "%TEMP%\depixpin_test.txt" 2>nul
set /p TEST= < "%TEMP%\depixpin_test.txt"
if "%TEST%"=="HTTP 200" (echo     自测通过: 全链路 OK) else (
    echo     [警告] 自测未通过 (%TEST%)。可能 443 端口被其他程序占用，
    echo            或服务启动较慢。稍等后重试，或查看 server\logs\server.log
)

echo.
echo ========================================
echo  安装完成！PixPin 侧操作：
echo    1. 设置 -^> 系统 -^> 翻译（向下滚动）
echo    2. APP ID / 密钥随便填，点"验证"
echo    3. 贴图右键"翻译"或 Ctrl+Q 使用
echo  卸载：运行 uninstall.bat
echo ========================================
pause
exit /b 0

:fail
echo 安装中断。若多次失败请右键"以管理员身份运行"。
pause
exit /b 1
