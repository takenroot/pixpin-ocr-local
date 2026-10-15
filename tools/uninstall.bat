@echo off
setlocal
REM ============================================================
REM dePixPin 完全卸载：任务 + hosts + 证书
REM ============================================================
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo [1/3] 停止并删除自启任务...
schtasks /end /tn "dePixPin" >nul 2>&1
schtasks /delete /tn "dePixPin" /f >nul 2>&1
if %errorlevel%==0 (echo     已删除) else (echo     任务不存在，跳过)

echo [2/3] 移除 hosts 记录...
powershell -NoProfile -Command "$h='$env:SystemRoot\System32\drivers\etc\hosts'; $in=Get-Content $h; $out=@(); $skip=$false; foreach($l in $in){ if($l -match 'dePixPin'){ $skip=(!$skip -or $l -match '<<<'); continue }; if(!$skip){ $out+=$l } }; $out | Set-Content $h -Encoding ASCII"
if %errorlevel%==0 (echo     已移除) else (echo     [警告] 失败，请手动检查 hosts)

echo [3/3] 卸载根证书...
set "CERT=%~dp0..\server\certs\depixpin-ca.crt"
if not exist "%CERT%" set "CERT=%~dp0certs\depixpin-ca.crt"
for /f "tokens=2 delims=:" %%a in ('certutil -dump "%CERT%" ^| findstr /C:"Cert Hash(sha256)"') do set "HASH=%%a"
set "HASH=%HASH: =%"
if defined HASH (certutil -delstore Root %HASH% >nul 2>&1)
if %errorlevel%==0 (echo     已卸载) else (echo     未找到证书，跳过)

echo.
echo 卸载完成，需重启 PixPin 生效。
pause
