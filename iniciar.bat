@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Clipadsk

echo.
echo  ==========================================
echo    Clipadsk  ^|  Iniciando...
echo  ==========================================
echo.

:: ── Matar instancias previas en puerto 5000 ──────────────────────────────────
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000 " 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

:: ─────────────────────────────────────────────────────────────────────────────
:: 1) PYTHON
:: ─────────────────────────────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Python no encontrado. Intentando instalar con winget...
    winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo.
        echo  [ERROR] No se pudo instalar Python automaticamente.
        echo          Descargalo desde https://python.org e instala con "Add to PATH" marcado.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo  [OK] Python instalado. Cerrá esta ventana y volvé a abrir iniciar.bat.
    pause
    exit /b 0
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  [OK] %%v encontrado.

:: ─────────────────────────────────────────────────────────────────────────────
:: 2) FFMPEG
:: ─────────────────────────────────────────────────────────────────────────────
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] FFmpeg no encontrado. Intentando instalar con winget...
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo.
        echo  [AVISO] No se pudo instalar FFmpeg automaticamente.
        echo          Descargalo desde https://ffmpeg.org/download.html y agregalo al PATH.
        echo          La app funcionara pero sin conversion de audio.
        echo.
    ) else (
        echo.
        echo  [OK] FFmpeg instalado. Cerrá esta ventana y volvé a abrir iniciar.bat.
        pause
        exit /b 0
    )
) else (
    echo  [OK] FFmpeg encontrado.
)

:: ─────────────────────────────────────────────────────────────────────────────
:: 3) YT-DLP
:: ─────────────────────────────────────────────────────────────────────────────
if not exist "yt-dlp.exe" (
    echo  [!] yt-dlp.exe no encontrado. Descargando...
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile 'yt-dlp.exe'"
    if %errorlevel% neq 0 (
        echo  [ERROR] No se pudo descargar yt-dlp.exe. Verifica tu conexion a internet.
        pause
        exit /b 1
    )
    echo  [OK] yt-dlp.exe descargado.
) else (
    echo  [OK] yt-dlp.exe encontrado.
)

:: ─────────────────────────────────────────────────────────────────────────────
:: 4) ENTORNO VIRTUAL + DEPENDENCIAS (solo la primera vez)
:: ─────────────────────────────────────────────────────────────────────────────
if not exist "backend\venv\Scripts\python.exe" (
    echo.
    echo  [+] Primera vez: creando entorno virtual e instalando dependencias...
    echo      Esto puede tardar 2-3 minutos. Solo ocurre una vez.
    echo.
    python -m venv backend\venv
    if %errorlevel% neq 0 (
        echo  [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
    backend\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    if %errorlevel% neq 0 (
        echo  [ERROR] Fallo al instalar dependencias. Revisa tu conexion a internet.
        pause
        exit /b 1
    )
    echo.
    echo  [OK] Dependencias instaladas correctamente.
) else (
    echo  [OK] Entorno virtual listo.
)

:: ─────────────────────────────────────────────────────────────────────────────
:: 5) SINCRONIZAR COOKIES (si existe cookies.txt en la raiz)
:: ─────────────────────────────────────────────────────────────────────────────
if exist "cookies.txt" (
    copy /y "cookies.txt" "backend\cookies.txt" >nul
    echo  [OK] cookies.txt copiado al backend.
)

:: ─────────────────────────────────────────────────────────────────────────────
:: 6) ARRANCAR BACKEND (oculto, sin ventana)
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo  [+] Iniciando servidor backend...
powershell -NoProfile -WindowStyle Hidden -Command ^
    "Start-Process '%~dp0backend\venv\Scripts\python.exe' -ArgumentList '%~dp0backend\main.py' -WorkingDirectory '%~dp0backend' -WindowStyle Hidden"

:: ─────────────────────────────────────────────────────────────────────────────
:: 7) ESPERAR A QUE RESPONDA (hasta 30 segundos)
:: ─────────────────────────────────────────────────────────────────────────────
echo  [+] Esperando que el servidor este listo...
set /a intentos=0
:esperar
timeout /t 2 >nul
curl -s http://127.0.0.1:5000/api/health/cookies >nul 2>&1
if %errorlevel% equ 0 goto listo
set /a intentos+=1
if %intentos% lss 15 goto esperar
echo  [AVISO] El servidor tarda mas de lo esperado. Abriendo igual...

:listo
echo  [OK] Servidor activo.

:: ─────────────────────────────────────────────────────────────────────────────
:: 8) ABRIR NAVEGADOR
:: ─────────────────────────────────────────────────────────────────────────────
echo.
echo  ==========================================
echo    Abriendo Clipadsk en el navegador...
echo    http://127.0.0.1:5000
echo  ==========================================
echo.
explorer "http://127.0.0.1:5000"

:: Minimizar esta ventana
powershell -NoProfile -Command "$h=(Get-Process -Id $PID).MainWindowHandle; Add-Type -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool ShowWindow(IntPtr h,int n);' -Name W -Namespace W; [W.W]::ShowWindow($h,6)" >nul 2>&1

exit
