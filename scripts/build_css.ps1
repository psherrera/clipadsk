# Regenera frontend\vendor\tailwind.css y tailwind-setup.css (el CSS de Tailwind ya compilado).
# Hace falta correrlo SOLO si agregas o cambias clases de Tailwind en frontend\index.html,
# frontend\setup.html o frontend\main.js. Requiere Node.js (https://nodejs.org).
# Uso (desde cualquier carpeta):  powershell -ExecutionPolicy Bypass -File scripts\build_css.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'No se encontro Node.js/npm. Instalalo desde https://nodejs.org y volve a correr este script.'
    }
    npm install --prefix scripts --no-audit --no-fund --loglevel=error
    if ($LASTEXITCODE -ne 0) { throw 'Fallo npm install' }
    $tw = Join-Path $PSScriptRoot 'node_modules\.bin\tailwindcss.cmd'
    & $tw -c scripts/tailwind.config.js -i scripts/tailwind.input.css -o frontend/vendor/tailwind.css --minify
    if ($LASTEXITCODE -ne 0) { throw 'Fallo al compilar tailwind.css' }
    & $tw -c scripts/tailwind.setup.config.js -i scripts/tailwind.input.css -o frontend/vendor/tailwind-setup.css --minify
    if ($LASTEXITCODE -ne 0) { throw 'Fallo al compilar tailwind-setup.css' }
    Write-Host 'Listo: CSS de Tailwind regenerado. Subi tambien los cambios de frontend\vendor.'
} finally {
    Pop-Location
}
