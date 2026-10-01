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

rem --- Cerrar el Clipadsk que este usando el puerto 5000 (de esta carpeta o de una version
rem     anterior instalada en otra). Se usa PowerShell porque netstat dice LISTENING o
rem     ESCUCHANDO segun el idioma de Windows.
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue; if ($p -and $p.ProcessName -match '^pythonw?$') { Stop-Process -Id $p.Id -Force } }" >nul 2>&1
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }" >nul 2>&1
if !errorlevel! neq 0 (
    echo   [AVISO] El puerto 5000 esta ocupado por otro programa. Cerralo o reinicia la PC.
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
rem     (se verifica que responda la version NUEVA: la vieja no tiene /api/health)
powershell -NoProfile -Command "try { $r = Invoke-RestMethod 'http://127.0.0.1:5000/api/health' -TimeoutSec 2; if ($r.status -eq 'ok') { exit 0 } } catch {}; exit 1" >nul 2>&1
if !errorlevel! equ 0 goto listo
set /a intentos+=1
if !intentos! lss 20 goto esperar
echo   [AVISO] El servidor tarda mas de lo normal. Si no abre, mira el registro en backend\clipadsk.log
:listo

echo   [OK] Abriendo http://127.0.0.1:5000
start "" "http://127.0.0.1:5000"
exit
