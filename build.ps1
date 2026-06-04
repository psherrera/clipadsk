# build.ps1 - Genera Clipa.exe portable (todo-en-uno)
# Ejecutar desde la raiz del proyecto: .\build.ps1

$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv   = Join-Path $root "backend\venv"
$python = Join-Path $venv "Scripts\python.exe"
$pip    = Join-Path $venv "Scripts\pip.exe"

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   Clipa - Build de ejecutable portable"   -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# -- 1. Verificar que existe el venv ------------------------------------------
if (-not (Test-Path $python)) {
    Write-Host "[ERROR] No se encontro el venv en backend\venv."       -ForegroundColor Red
    Write-Host "        Ejecuta primero iniciar.bat para crearlo."      -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Python del venv encontrado." -ForegroundColor Green

# -- 2. Instalar / actualizar PyInstaller en el venv --------------------------
Write-Host ""
Write-Host "[+] Verificando PyInstaller..." -ForegroundColor Cyan
$pyiVersion = & $python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
if (-not $pyiVersion) {
    Write-Host "[+] Instalando PyInstaller..." -ForegroundColor Yellow
    & $pip install pyinstaller --quiet
    Write-Host "[OK] PyInstaller instalado." -ForegroundColor Green
} else {
    Write-Host "[OK] PyInstaller $pyiVersion ya instalado." -ForegroundColor Green
}

# -- 3. Limpiar builds anteriores ---------------------------------------------
Write-Host ""
Write-Host "[+] Limpiando builds anteriores..." -ForegroundColor Cyan
foreach ($d in @("build", "dist")) {
    $p = Join-Path $root $d
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "    Eliminado: $p" -ForegroundColor Gray
    }
}

# -- 4. Ejecutar PyInstaller --------------------------------------------------
Write-Host ""
Write-Host "[+] Compilando Clipa.exe..." -ForegroundColor Cyan
Write-Host "    (esto puede tardar 2-5 minutos la primera vez)" -ForegroundColor Gray
Write-Host ""

$specFile = Join-Path $root "clipa.spec"
& $python -m PyInstaller $specFile --noconfirm --clean

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] PyInstaller fallo. Revisa los mensajes arriba." -ForegroundColor Red
    exit 1
}

# -- 5. Mover el .exe a la raiz -----------------------------------------------
$distExe = Join-Path $root "dist\Clipa.exe"
$finalExe = Join-Path $root "Clipa.exe"

if (Test-Path $distExe) {
    if (Test-Path $finalExe) { Remove-Item -Force $finalExe }
    Move-Item -Path $distExe -Destination $finalExe

    $size = [math]::Round((Get-Item $finalExe).Length / 1MB, 1)

    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host "   BUILD EXITOSO"                           -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "   Archivo : Clipa.exe"                     -ForegroundColor White
    Write-Host "   Tamano  : ${size} MB"                    -ForegroundColor White
    Write-Host ""
    Write-Host "   Para distribuir el usuario solo necesita:"  -ForegroundColor Cyan
    Write-Host "   - Clipa.exe"                               -ForegroundColor White
    Write-Host "   - cookies.txt (opcional, al lado del .exe)" -ForegroundColor White
    Write-Host ""
    Write-Host "   Doble clic en Clipa.exe para arrancar."   -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[ERROR] No se encontro dist\Clipa.exe tras el build." -ForegroundColor Red
    exit 1
}

# -- 6. Limpiar carpetas temporales -------------------------------------------
Write-Host "[+] Limpiando archivos temporales..." -ForegroundColor Gray
foreach ($d in @("build", "dist")) {
    $p = Join-Path $root $d
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
Write-Host "[OK] Listo." -ForegroundColor Green
