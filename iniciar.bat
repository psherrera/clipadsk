@echo off
cd /d "%~dp0"
title Clipadsk

echo ==========================================
echo   Clipadsk - Descargador Local
echo ==========================================
echo.

:: ── Verificar Python ─────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no encontrado. Instalalo desde https://python.org
    pause
    exit /b 1
)

:: ── Verificar FFmpeg ─────────────────────────────────────────
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [AVISO] FFmpeg no encontrado. La descarga de audio puede fallar.
    echo         Descargalo desde https://ffmpeg.org/download.html
    echo.
)

:: ── Instalar dependencias si hace falta ──────────────────────
if not exist "backend\venv" (
    echo [+] Creando entorno virtual... Esto solo ocurre la primera vez.
    python -m venv backend\venv
    echo [+] Instalando dependencias basicas...
    backend\venv\Scripts\python.exe -m pip install --upgrade pip
    echo [+] Instalando PyTorch CPU... Este es un archivo grande y tardara unos minutos.
    backend\venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    echo [+] Instalando el resto de dependencias: Whisper, FastAPI, etc...
    backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
    echo [+] Dependencias instaladas correctamente.
    echo.
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
start "" "%~dp0frontend\index.html"

echo.
echo ==========================================
echo   ¡Todo listo! 
echo   Backend : http://127.0.0.1:5000
echo   Frontend: archivo local (index.html)
echo.
echo   Cierra la ventana "Clipadsk Backend"
echo   para apagar el servidor.
echo ==========================================
echo.
pause
