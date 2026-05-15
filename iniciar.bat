@echo off
cd /d "%~dp0"
title Clipadsk

echo ==========================================
echo   Clipadsk - Descargador Local
echo ==========================================
echo.

:: ── Verificar Actualizaciones (Git) ──────────────────────────
if exist ".git" (
    echo [+] Buscando actualizaciones en el repositorio...
    git pull origin main
    echo.
)

:: ── Actualizar yt-dlp ────────────────────────────────────────
if exist "yt-dlp.exe" (
    echo [+] Verificando version del motor de descarga...
    yt-dlp.exe -U
    echo.
)


:: ── Verificar Python ─────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [+] Python no encontrado. Intentando instalar automaticamente ^(Windows 10/11^)...
    winget --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Tu Windows no soporta auto-instalacion. Instala Python desde https://python.org
        pause
        exit /b 1
    )
    winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    echo.
    echo ==============================================================
    echo  PYTHON INSTALADO. Por favor, CIERRA esta ventana y vuelve a
    echo  abrir iniciar.bat para continuar.
    echo ==============================================================
    pause
    exit /b 0
)

:: ── Verificar FFmpeg ─────────────────────────────────────────
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [+] FFmpeg no encontrado. Intentando instalar automaticamente...
    winget --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [AVISO] Tu Windows no soporta auto-instalacion. Descargalo desde https://ffmpeg.org/download.html
        echo.
    ) else (
        winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        echo.
        echo ==============================================================
        echo  FFMPEG INSTALADO. Por favor, CIERRA esta ventana y vuelve a
        echo  abrir iniciar.bat para continuar.
        echo ==============================================================
        pause
        exit /b 0
    )
)

:: ── Verificar yt-dlp.exe ─────────────────────────────────────
if not exist "yt-dlp.exe" (
    echo [+] yt-dlp.exe no encontrado. Descargando ultima version...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile 'yt-dlp.exe'"
    if %errorlevel% neq 0 (
        echo [ERROR] No se pudo descargar yt-dlp.exe. Verifica tu conexion a internet.
        pause
        exit /b 1
    )
)

:: ── Instalar dependencias si hace falta ──────────────────────
if not exist "backend\venv" (
    echo [+] Creando entorno virtual... Esto solo ocurre la primera vez.
    python -m venv backend\venv
    echo [+] Instalando dependencias basicas...
    backend\venv\Scripts\python.exe -m pip install --upgrade pip
    
    :: No instalamos PyTorch completo si solo usamos Groq/Whisper-API, 
    :: pero pydub y yt-dlp python wrapper son necesarios.
    echo [+] Instalando dependencias del backend...
    backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    
    echo [+] Dependencias instaladas correctamente.

    echo.
    set FIRST_RUN=1
)


:: ── Copiar cookies si existen ────────────────────────────────
if exist "cookies.txt" (
    echo [+] Copiando cookies.txt al backend...
    copy "cookies.txt" "backend\cookies.txt" >nul
)

:: ── Arrancar backend en segundo plano ────────────────────────
echo [+] Iniciando backend en http://127.0.0.1:5000 ...
start "Clipadsk Backend" /min "backend\venv\Scripts\python.exe" "backend\main.py"

:: ── Esperar a que levante ────────────────────────────────────
echo [+] Esperando al servidor...
timeout /t 6 >nul

:: ── Verificar si el backend está activo ──────────────────────
curl -s http://127.0.0.1:5000/api/video-info >nul
if %errorlevel% neq 0 (
    echo [ERROR] El servidor no parece haber arrancado. 
    echo Revisa la ventana "Clipadsk Backend" para ver errores.
    pause
    exit /b 1
)

:: ── Abrir frontend directamente (sin nginx) ──────────────────
echo [+] Abriendo interfaz...
if "%FIRST_RUN%"=="1" (
    start http://127.0.0.1:5000/setup.html
) else (
    start http://127.0.0.1:5000
)

echo.
echo ==========================================
echo   ¡Todo listo! 
echo   Backend : http://127.0.0.1:5000
echo   Frontend: http://127.0.0.1:5000
echo.
echo   Cierra la ventana "Clipadsk Backend"
echo   para apagar el servidor.
echo ==========================================
echo.
pause
