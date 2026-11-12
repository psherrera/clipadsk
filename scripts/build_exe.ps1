# build_exe.ps1 - Genera Clipa.exe con PyInstaller usando la instalacion de backend\venv.
# Se ejecuta con CREAR_EXE.bat (doble clic). Tarda 2-5 minutos.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$py = Join-Path $root 'backend\venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'Primero hay que instalar Clipadsk: ejecuta INSTALAR.bat' -ForegroundColor Red
    exit 1
}

Write-Host 'Instalando dependencias y PyInstaller...' -ForegroundColor Cyan
& $py -m pip install -q --disable-pip-version-check -r backend\requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Host 'No se pudieron instalar las dependencias.' -ForegroundColor Red; exit 1 }

# Si Clipa.exe esta abierto no se puede reemplazar
Get-Process -Name 'Clipa' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host 'Armando Clipa.exe (paciencia, tarda unos minutos)...' -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm --clean --log-level WARN --distpath build\dist --workpath build\work Clipa.spec
if ($LASTEXITCODE -ne 0) { Write-Host 'PyInstaller fallo. Mira los mensajes de arriba.' -ForegroundColor Red; exit 1 }

if (Test-Path Clipa.exe) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmm'
    Move-Item Clipa.exe "build\Clipa-anterior-$stamp.exe" -Force
}
Move-Item build\dist\Clipa.exe Clipa.exe -Force
$size = [math]::Round((Get-Item Clipa.exe).Length / 1MB)
Write-Host ''
Write-Host "Listo: Clipa.exe ($size MB) en $root" -ForegroundColor Green
Write-Host 'El exe anterior quedo guardado en la carpeta build.' -ForegroundColor DarkGray
