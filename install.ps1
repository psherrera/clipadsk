# install.ps1 — Instalador de Clipadsk para Windows
# Ejecutar una sola vez en una PC nueva: .\install.ps1
# Luego usar iniciar.bat para arrancar la app.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  ==========================================" -ForegroundColor Cyan
Write-Host "    Clipadsk  |  Instalador" -ForegroundColor Cyan
Write-Host "  ==========================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Verificar Python ────────────────────────────────────────────────────────
Write-Host "  [1/5] Verificando Python..." -ForegroundColor White
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "  [!] Python no encontrado. Intentando instalar con winget..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    Write-Host ""
    Write-Host "  [OK] Python instalado. Cerrá y volvé a ejecutar install.ps1." -ForegroundColor Green
    exit 0
}
$pyVersion = & python --version 2>&1
Write-Host "  [OK] $pyVersion" -ForegroundColor Green

# ── 2. Verificar FFmpeg ────────────────────────────────────────────────────────
Write-Host "  [2/5] Verificando FFmpeg..." -ForegroundColor White
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ff) {
    Write-Host "  [!] FFmpeg no encontrado. Instalando con winget..." -ForegroundColor Yellow
    winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    Write-Host "  [OK] FFmpeg instalado." -ForegroundColor Green
} else {
    Write-Host "  [OK] FFmpeg encontrado." -ForegroundColor Green
}

# ── 3. Descargar yt-dlp ────────────────────────────────────────────────────────
Write-Host "  [3/5] Verificando yt-dlp..." -ForegroundColor White
$ytdlp = Join-Path $root "yt-dlp.exe"
if (-not (Test-Path $ytdlp)) {
    Write-Host "  [!] Descargando yt-dlp.exe..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -OutFile $ytdlp
    Write-Host "  [OK] yt-dlp.exe descargado." -ForegroundColor Green
} else {
    Write-Host "  [OK] yt-dlp.exe ya existe." -ForegroundColor Green
}

# ── 4. Crear entorno virtual e instalar dependencias ──────────────────────────
Write-Host "  [4/5] Instalando dependencias Python..." -ForegroundColor White
$venvPy = Join-Path $root "backend\venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "  [+] Creando entorno virtual..." -ForegroundColor Gray
    python -m venv (Join-Path $root "backend\venv")
}
Write-Host "  [+] Actualizando pip..." -ForegroundColor Gray
& $venvPy -m pip install --upgrade pip --quiet
Write-Host "  [+] Instalando requirements.txt..." -ForegroundColor Gray
& $venvPy -m pip install -r (Join-Path $root "backend\requirements.txt")
Write-Host "  [OK] Dependencias instaladas." -ForegroundColor Green

# ── 5. Configurar .env ────────────────────────────────────────────────────────
Write-Host "  [5/5] Configurando variables de entorno..." -ForegroundColor White
$envFile = Join-Path $root ".env"
$envTemplate = Join-Path $root ".env.template"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envTemplate) {
        Copy-Item $envTemplate $envFile
        Write-Host "  [OK] .env creado desde .env.template." -ForegroundColor Green
        Write-Host "       Editá .env y agrega tu GROQ_API_KEY si queres transcripcion por IA." -ForegroundColor Cyan
    } else {
        @"
# Variables de entorno de Clipadsk
# Consegui tu clave gratis en https://console.groq.com/keys
GROQ_API_KEY=
"@ | Out-File -Encoding UTF8 $envFile
        Write-Host "  [OK] .env creado con valores por defecto." -ForegroundColor Green
    }
} else {
    Write-Host "  [OK] .env ya existe, no se sobreescribio." -ForegroundColor Green
}

# ── Resultado final ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ==========================================" -ForegroundColor Green
Write-Host "    Instalacion completada exitosamente!" -ForegroundColor Green
Write-Host "  ==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Para usar Clipadsk, hace doble clic en:" -ForegroundColor White
Write-Host "    iniciar.bat" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Para habilitar transcripcion con IA (opcional):" -ForegroundColor White
Write-Host "    1. Ve a https://console.groq.com/keys" -ForegroundColor Gray
Write-Host "    2. Crea una clave gratuita" -ForegroundColor Gray
Write-Host "    3. Pegala en el archivo .env (GROQ_API_KEY=...)" -ForegroundColor Gray
Write-Host "    4. O cargala directamente desde la app en Config > API Key" -ForegroundColor Gray
Write-Host ""
