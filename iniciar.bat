@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Clipadsk

rem ===========================================================================
rem  Clipadsk - arranque diario
rem  Si todavia no esta instalado en esta carpeta, ejecuta el instalador.
rem  (Sin acentos a proposito: cmd.exe los muestra mal.)
rem ===========================================================================

if not exist "backend\venv\Scripts\python.exe" (
    echo.
    echo   Clipadsk todavia no esta instalado en esta carpeta.
    echo   Iniciando el instalador...
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
    exit /b
)

echo.
echo   Clipadsk ^| Iniciando...
echo.

rem --- Cerrar una instancia anterior (solo el proceso que ESCUCHA en el puerto 5000)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr /r /c:":5000 .*LISTENING" 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

rem --- Reinstalar dependencias solo si cambio requirements.txt (por ejemplo, tras actualizar)
fc /b "backend\requirements.txt" "backend\venv\.requirements.installed" >nul 2>&1
if !errorlevel! neq 0 (
    echo   [+] Actualizando dependencias...
    backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt --quiet --disable-pip-version-check
    if !errorlevel! equ 0 (
        copy /y "backend\requirements.txt" "backend\venv\.requirements.installed" >nul
    ) else (
        echo   [AVISO] No se pudieron actualizar las dependencias. Se arranca igual.
    )
)

rem --- Cookies opcionales en la carpeta principal
if exist "cookies.txt" copy /y "cookies.txt" "backend\cookies.txt" >nul
if exist "cookies_ig.txt" copy /y "cookies_ig.txt" "backend\cookies_ig.txt" >nul

rem --- Arrancar el servidor en segundo plano (sin ventana)
echo   [+] Iniciando servidor...
powershell -NoProfile -WindowStyle Hidden -Command ^
    "Start-Process '%~dp0backend\venv\Scripts\python.exe' -ArgumentList '\"%~dp0backend\main.py\"' -WorkingDirectory '%~dp0backend' -WindowStyle Hidden"

rem --- Esperar a que responda (hasta 40 segundos)
set /a intentos=0
:esperar
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "try { $null = Invoke-WebRequest 'http://127.0.0.1:5000/api/health' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1
if !errorlevel! equ 0 goto listo
set /a intentos+=1
if !intentos! lss 20 goto esperar
echo   [AVISO] El servidor tarda mas de lo normal. Si no abre, mira el registro en backend\clipadsk.log
:listo

echo   [OK] Abriendo http://127.0.0.1:5000
start "" "http://127.0.0.1:5000"
exit
