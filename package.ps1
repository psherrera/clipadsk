# package.ps1 - Crea un ZIP listo para copiar al pendrive usando un temp dir y robocopy
# Ejecución: desde la raíz del repo (PowerShell)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Creando ZIP desde: $root" -ForegroundColor Cyan

$defaultName = Join-Path -Path $root -ChildPath "clipadsk-package.zip"
$destInput = Read-Host "Ruta destino para el ZIP (enter para usar $defaultName)"
if ([string]::IsNullOrWhiteSpace($destInput)) {
    $dest = $defaultName
} else {
    if ([System.IO.Path]::IsPathRooted($destInput)) {
        $dest = [System.IO.Path]::GetFullPath($destInput)
    } else {
        $dest = [System.IO.Path]::GetFullPath((Join-Path $root $destInput))
    }
}

$temp = Join-Path -Path $env:TEMP -ChildPath ("clipadsk_pkg_" + [System.Guid]::NewGuid().ToString())
Write-Host "Usando directorio temporal: $temp" -ForegroundColor Gray
New-Item -ItemType Directory -Path $temp | Out-Null

function Safe-RoboCopy($src, $dst, $excludeDirs=@(), $excludeFiles=@()) {
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    $xd = $excludeDirs | ForEach-Object { "/XD `"$($_)`"" } | Out-String
    $xf = $excludeFiles | ForEach-Object { "/XF `"$($_)`"" } | Out-String
    $xd = $xd -replace "\r?\n"," "
    $xf = $xf -replace "\r?\n"," "
    $cmd = "robocopy `"$src`" `"$dst`" /E /COPYALL /R:2 /W:1 $xd $xf"
    Write-Host "Running: $cmd" -ForegroundColor DarkGray
    cmd.exe /c $cmd | Out-Null
}

# Copiar frontend completo
if (Test-Path (Join-Path $root 'frontend')) {
    Safe-RoboCopy (Join-Path $root 'frontend') (Join-Path $temp 'frontend')
}

# Copiar backend excluyendo downloads y model
if (Test-Path (Join-Path $root 'backend')) {
    Safe-RoboCopy (Join-Path $root 'backend') (Join-Path $temp 'backend') @('downloads','model') @('clipadsk.db','transcripts_cache.json','transcripts_cache.json.migrated')
}

# Copiar ficheros sueltos
$toCopy = @('docker-compose.yml','install.ps1','.env.template','README.md')
foreach ($f in $toCopy) {
    $src = Join-Path $root $f
    if (Test-Path $src) { Copy-Item -Path $src -Destination (Join-Path $temp $f) -Force }
}

Write-Host "Creando zip en: $dest" -ForegroundColor Green
try {
    Compress-Archive -Path (Join-Path $temp '*') -DestinationPath $dest -Force
    Write-Host "ZIP creado: $dest" -ForegroundColor Cyan
} catch {
    Write-Host "Error creando ZIP: $_" -ForegroundColor Red
    Remove-Item -Recurse -Force $temp
    exit 1
}

# Limpiar
Remove-Item -Recurse -Force $temp
Write-Host "Directorio temporal eliminado." -ForegroundColor Gray
