# Genera backend/requirements-pinned.txt con versiones exactas, desde un entorno limpio.
# Uso (desde cualquier carpeta): powershell -ExecutionPolicy Bypass -File scripts\pin_requirements.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$venv = Join-Path $root ".venv-pin"
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
python -m venv $venv
$py = Join-Path $venv "Scripts\python.exe"
& $py -m pip install --upgrade pip -q
& $py -m pip install -r backend\requirements.txt -q

$lines = @("# Versiones exactas probadas. Instalar con: pip install -r backend/requirements-pinned.txt")
$lines += & $py -m pip freeze --exclude-editable
# UTF-8 sin BOM (PowerShell 5 usa UTF-16 con '>' y pip no lo lee bien en todos lados)
[System.IO.File]::WriteAllLines((Join-Path $root "backend\requirements-pinned.txt"), $lines, (New-Object System.Text.UTF8Encoding $false))

Remove-Item -Recurse -Force $venv
Write-Host "Listo: backend/requirements-pinned.txt"
