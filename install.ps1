# install.ps1 - Instalador interactivo para Clipadsk
Write-Host "Instalador interactivo Clipadsk" -ForegroundColor Cyan

function Ask-Yes($text, $default = $true) {
    $yn = $default ? "[Y/n]" : "[y/N]"
    while ($true) {
        $r = Read-Host "$text $yn"
        if ([string]::IsNullOrWhiteSpace($r)) { return $default }
        if ($r -match '^[Yy]') { return $true }
        if ($r -match '^[Nn]') { return $false }
    }
}

Write-Host "\nResumen: Este script te guía para levantar Clipadsk en Windows." -ForegroundColor Yellow

# Lista de comprobación rápida (se mostrará al usuario)
Write-Host "\nArchivos recomendados para copiar al pendrive:" -ForegroundColor Cyan
Write-Host " - docker-compose.yml" -ForegroundColor Green
Write-Host " - carpeta frontend/ completa" -ForegroundColor Green
Write-Host " - carpeta backend/ completa (sin .venv ni backend/downloads ni backend/model)" -ForegroundColor Green
Write-Host " - backend/requirements.txt" -ForegroundColor Green
Write-Host " - install.ps1 (este script)" -ForegroundColor Green
Write-Host " - .env.template" -ForegroundColor Green

# 1) Detectar Docker
$hasDocker = (Get-Command docker -ErrorAction SilentlyContinue) -ne $null
if ($hasDocker) {
    if (Ask-Yes "Docker detectado. ¿Deseas levantar con Docker Compose ahora? (recomendado)") {
        Write-Host "Ejecutando: docker compose up --build" -ForegroundColor Green
        docker compose up --build
        exit
    }
}

# 2) Comprobar Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python no encontrado en PATH. Instala Python 3.11+ y vuelve a ejecutar este script." -ForegroundColor Yellow
    if (-not (Ask-Yes "¿Deseas continuar y mostrar solo instrucciones (sin instalar dependencias)?" $false)) { exit }
}

# 3) Crear y activar venv
if (-not (Test-Path -Path ".venv")) {
    Write-Host "Creando virtualenv en .venv..." -ForegroundColor Green
    python -m venv .venv
}
Write-Host "Activando .venv..." -ForegroundColor Green
& .\.venv\Scripts\Activate.ps1

# 4) Crear .env a partir de .env.template
if (Test-Path -Path ".env.template" -and -not (Test-Path -Path ".env")) {
    Copy-Item .env.template .env
    Write-Host ".env creado desde .env.template. Edita .env si necesitas claves." -ForegroundColor Cyan
} elseif (-not (Test-Path -Path ".env")) {
    Write-Host "No se encontró .env.template; creando .env mínimo..." -ForegroundColor Yellow
    @"
# Variables de entorno mínimas
GROQ_API_KEY=
FRONTEND_DIR=../frontend
WHISPER_MODEL=small
"@ | Out-File -Encoding UTF8 .env
}

# 5) Instalar dependencias
if (Test-Path -Path "backend/requirements.txt") {
    if (Ask-Yes "Instalar dependencias desde backend/requirements.txt ahora? (requiere internet)") {
        Write-Host "Instalando dependencias..." -ForegroundColor Green
        pip install -r backend/requirements.txt
    } else {
        Write-Host "Omitida instalación de dependencias. Instálalas manualmente más tarde." -ForegroundColor Yellow
    }
} else {
    Write-Host "No se encontró backend/requirements.txt; salta instalación de pip." -ForegroundColor Yellow
}

# 6) Dependencias opcionales pesadas
if (Ask-Yes "¿Instalar extras opcionales (faster-whisper)? Solo si deseas transcripción local") {
    Write-Host "Instalando faster-whisper (puede requerir Torch y recursos adicionales)..." -ForegroundColor Green
    pip install faster-whisper || Write-Host "Instalación de faster-whisper fallida. Instálala manualmente." -ForegroundColor Red
}

# 7) Crear carpetas necesarias
if (-not (Test-Path -Path "backend/downloads")) { New-Item -ItemType Directory -Path "backend/downloads" | Out-Null }
if (-not (Test-Path -Path "backend/model")) { New-Item -ItemType Directory -Path "backend/model" | Out-Null }

# 8) Opciones de ejecución
Write-Host "\nOpciones para ejecutar la aplicación:" -ForegroundColor Cyan
Write-Host "1) Ejecutar backend local con uvicorn (uvicorn main:app --host 0.0.0.0 --port 5000)" -ForegroundColor Green
Write-Host "2) Ejecutar backend\main.py directamente" -ForegroundColor Green
Write-Host "3) Salir" -ForegroundColor Gray
$opt = Read-Host "Elige 1/2/3"
if ($opt -eq "1") {
    Push-Location backend
    Write-Host "Iniciando uvicorn..." -ForegroundColor Green
    uvicorn main:app --host 0.0.0.0 --port 5000
    Pop-Location
} elseif ($opt -eq "2") {
    Write-Host "Ejecutando backend\main.py..." -ForegroundColor Green
    python backend\main.py
} else {
    Write-Host "Instalación/Configuración finalizada (parcial). Revisa README para pasos adicionales." -ForegroundColor Cyan
}
