@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ================================
echo   Быстрая установка BOT_TOKEN
echo ================================
echo.
set /p TOKEN=Вставь токен бота и нажми Enter: 
if "%TOKEN%"=="" (
  echo Токен не введен.
  pause
  exit /b 1
)
if not exist .env (
  copy .env.example .env >nul
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='.env'; $t=$env:TOKEN; $c=Get-Content $p -Raw; if ($c -match '(?m)^BOT_TOKEN=.*$') { $c=$c -replace '(?m)^BOT_TOKEN=.*$', ('BOT_TOKEN=' + $t) } else { $c=('BOT_TOKEN=' + $t + [Environment]::NewLine + $c) }; Set-Content -Path $p -Value $c -Encoding UTF8"
echo.
echo Готово. Токен записан в .env
echo Теперь можно запускать START_BOT.bat
echo.
pause
