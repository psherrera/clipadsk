<#
    Instalador de Clipadsk para Windows 10 / 11
    ===========================================

    Forma 1 (recomendada): abrir PowerShell y pegar esta linea:

        irm https://raw.githubusercontent.com/psherrera/clipadsk/main/instalar.ps1 | iex

    Forma 2: descargar el ZIP del repositorio, descomprimirlo y hacer doble clic
             en INSTALAR.bat

    Que hace:
      1. Verifica Windows y la conexion a internet
      2. Instala Python 3.12 si no esta (sin permisos de administrador)
      3. Descarga Clipadsk (con git si esta instalado; si no, el ZIP de GitHub)
      4. Descarga FFmpeg dentro de la carpeta de Clipadsk
      5. Crea el entorno de Python e instala las dependencias
      6. Crea accesos directos en el Escritorio y en el menu Inicio
      7. Abre Clipadsk

    Volver a ejecutarlo ACTUALIZA la app sin tocar .env, cookies ni el historial.
    Registro de la instalacion: %TEMP%\clipadsk-instalacion.log

    (Este archivo esta escrito sin acentos a proposito: Windows PowerShell 5.1
     lee los .ps1 sin BOM como ANSI y los acentos se romperian.)
#>
param(
    [string]$Destino = ""
)

$ErrorActionPreference = 'Continue'      # los errores se controlan a mano (ver Fallar)
$ProgressPreference = 'SilentlyContinue' # Invoke-WebRequest es mucho mas rapido sin barra
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$Repo          = 'psherrera/clipadsk'
$Rama          = 'main'
$PythonVersion = '3.12.7'
$FFmpegZipUrl  = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'

function Titulo($texto) {
    Write-Host ""
    Write-Host "  ============================================" -ForegroundColor Magenta
    Write-Host "    $texto" -ForegroundColor Magenta
    Write-Host "  ============================================" -ForegroundColor Magenta
}
function Paso($n, $texto) { Write-Host ""; Write-Host "  [$n/7] $texto" -ForegroundColor Cyan }
function Ok($texto)       { Write-Host "        OK  $texto" -ForegroundColor Green }
function Info($texto)     { Write-Host "            $texto" -ForegroundColor Gray }
function Aviso($texto)    { Write-Host "        !   $texto" -ForegroundColor Yellow }
function Fallar($texto)   { throw $texto }

function Actualizar-Path {
    # Toma el PATH nuevo del registro (para no tener que cerrar y abrir la consola)
    $maquina = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $usuario = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$maquina;$usuario"
}

function Probar-Python([string[]]$comando) {
    # Devuelve la ruta a python.exe si el comando es Python 3.10 o mas nuevo
    try {
        $exe = $comando[0]
        $extra = @()
        if ($comando.Count -gt 1) { $extra = $comando[1..($comando.Count - 1)] }
        $salida = & $exe @extra -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $salida) {
            $ruta = ("$salida").Trim()
            if ($ruta -and (Test-Path $ruta) -and ($ruta -notmatch 'WindowsApps')) { return $ruta }
        }
    } catch {}
    return $null
}

function Buscar-Python {
    $candidatos = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @('3.12', '3.11', '3.13', '3.10')) { $candidatos += , @('py', "-$v") }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    # El "python" de WindowsApps es un atajo a la Microsoft Store, no un Python real
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $candidatos += , @($cmd.Source) }
    foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles")) {
        foreach ($v in @('312', '311', '313', '310')) {
            $p = Join-Path $base "Python$v\python.exe"
            if (Test-Path $p) { $candidatos += , @($p) }
        }
    }
    foreach ($c in $candidatos) {
        $ruta = Probar-Python $c
        if ($ruta) { return $ruta }
    }
    return $null
}

function Instalar-Python {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "Instalando Python 3.12 con winget..."
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
        Actualizar-Path
        $py = Buscar-Python
        if ($py) { return $py }
    }
    Info "Descargando Python $PythonVersion desde python.org..."
    $instalador = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe" -OutFile $instalador -UseBasicParsing -ErrorAction Stop
    Info "Instalando Python (puede tardar un minuto)..."
    Start-Process -FilePath $instalador -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0' -Wait
    Remove-Item $instalador -ErrorAction SilentlyContinue
    Actualizar-Path
    return Buscar-Python
}

function Descargar-Zip-Repo([string]$destino) {
    # Descarga el codigo de GitHub como ZIP y lo copia encima de $destino
    $zip = Join-Path $env:TEMP 'clipadsk-main.zip'
    $tmp = Join-Path $env:TEMP 'clipadsk-main'
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/$Rama.zip" -OutFile $zip -UseBasicParsing -ErrorAction Stop
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force -ErrorAction Stop
    $raiz = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (-not $raiz -or -not (Test-Path (Join-Path $raiz.FullName 'backend\main.py'))) {
        Fallar "El ZIP descargado de GitHub no tiene el formato esperado."
    }
    New-Item -ItemType Directory -Path $destino -Force | Out-Null
    Copy-Item -Path (Join-Path $raiz.FullName '*') -Destination $destino -Recurse -Force -ErrorAction Stop
    Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

function Obtener-Codigo([string]$dir, [bool]$enLugar) {
    $hayGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
    $yaInstalado = Test-Path (Join-Path $dir 'backend\main.py')

    if ($enLugar) {
        Ok "Usando los archivos de esta carpeta"
        return
    }
    if ($yaInstalado -and (Test-Path (Join-Path $dir '.git')) -and $hayGit) {
        Info "Actualizando con git..."
        git -C $dir pull --ff-only origin $Rama 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok "Codigo actualizado"; return }
        Aviso "git pull no pudo actualizar (hay cambios locales?). Se sigue con la version actual."
        return
    }
    if ($yaInstalado) {
        Info "Actualizando desde GitHub (ZIP)..."
        Descargar-Zip-Repo $dir
        Ok "Codigo actualizado"
        return
    }
    if ($hayGit) {
        Info "Descargando con git..."
        git clone --depth 1 -b $Rama "https://github.com/$Repo.git" $dir 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Ok "Codigo descargado en $dir"; return }
        Aviso "git clone fallo, se prueba con el ZIP..."
    }
    Info "Descargando el ZIP de GitHub..."
    Descargar-Zip-Repo $dir
    Ok "Codigo descargado en $dir"
}

function Asegurar-FFmpeg([string]$dir) {
    if (Test-Path (Join-Path $dir 'ffmpeg.exe')) { Ok "FFmpeg ya esta en la carpeta de Clipadsk"; return }
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Ok "FFmpeg ya esta instalado en el sistema"; return }
    Info "Descargando FFmpeg (unos 100 MB, solo esta vez)..."
    $zip = Join-Path $env:TEMP 'ffmpeg-clipadsk.zip'
    $tmp = Join-Path $env:TEMP 'ffmpeg-clipadsk'
    try {
        Invoke-WebRequest $FFmpegZipUrl -OutFile $zip -UseBasicParsing -ErrorAction Stop
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        Get-ChildItem $tmp -Recurse -Include 'ffmpeg.exe', 'ffprobe.exe' | Copy-Item -Destination $dir -Force
        Ok "FFmpeg listo"
    } catch {
        Aviso "No se pudo descargar FFmpeg: $($_.Exception.Message)"
        Aviso "Clipadsk funciona, pero sin convertir audio ni descargar MP3. Se puede reintentar ejecutando el instalador de nuevo."
    } finally {
        Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Preparar-Entorno([string]$dir, [string]$py) {
    $venv   = Join-Path $dir 'backend\venv'
    $venvPy = Join-Path $venv 'Scripts\python.exe'

    # Un venv creado con un Python que ya no existe queda roto: se recrea
    if (Test-Path $venvPy) {
        & $venvPy -c "import sys" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Aviso "El entorno de Python estaba roto, se vuelve a crear"
            Remove-Item $venv -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path $venvPy)) {
        Info "Creando entorno de Python..."
        & $py -m venv $venv
        if ($LASTEXITCODE -ne 0) { Fallar "No se pudo crear el entorno de Python en $venv" }
    }
    Info "Instalando dependencias (la primera vez tarda 2-3 minutos)..."
    & $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check 2>$null | Out-Null
    $req = Join-Path $dir 'backend\requirements.txt'
    & $venvPy -m pip install -r $req --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { Fallar "Fallo la instalacion de dependencias. Revisa la conexion a internet y volve a ejecutar el instalador." }
    # Marca para que iniciar.bat sepa que las dependencias estan al dia
    Copy-Item $req (Join-Path $venv '.requirements.installed') -Force
    Ok "Dependencias instaladas"
}

function Crear-Accesos([string]$dir) {
    $ws = New-Object -ComObject WScript.Shell
    $carpetas = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
    foreach ($carpeta in $carpetas) {
        if (-not $carpeta -or -not (Test-Path $carpeta)) { continue }
        $lnk = $ws.CreateShortcut((Join-Path $carpeta 'Clipadsk.lnk'))
        $lnk.TargetPath       = Join-Path $dir 'iniciar.bat'
        $lnk.WorkingDirectory = $dir
        $lnk.WindowStyle      = 7   # minimizada
        $lnk.Description      = 'Clipadsk - descargar y transcribir videos para periodistas'
        $icono = Join-Path $dir 'clipa.ico'
        if (Test-Path $icono) { $lnk.IconLocation = "$icono,0" }
        $lnk.Save()
    }
    Ok "Accesos directos 'Clipadsk' en el Escritorio y en el menu Inicio"
}

function Instalar {
    Titulo "Clipadsk  |  Instalador"

    # Carpeta de instalacion: la del script si ya trae el codigo (ZIP descomprimido),
    # si no %LOCALAPPDATA%\Clipadsk (no necesita permisos de administrador)
    $enLugar = $false
    if (-not $Destino) {
        if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'backend\main.py'))) {
            $Destino = $PSScriptRoot
            $enLugar = $true
        } else {
            $Destino = Join-Path $env:LOCALAPPDATA 'Clipadsk'
        }
    }
    Info "Carpeta de instalacion: $Destino"

    Paso 1 "Verificando el sistema"
    if ([Environment]::OSVersion.Version.Major -lt 10) { Fallar "Clipadsk necesita Windows 10 u 11." }
    try {
        Invoke-WebRequest "https://github.com" -Method Head -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop | Out-Null
        Ok "Windows y conexion a internet"
    } catch {
        Fallar "No hay conexion a internet (o GitHub esta bloqueado en esta red)."
    }

    Paso 2 "Python"
    $py = Buscar-Python
    if ($py) { Ok "Python encontrado: $py" }
    else {
        $py = Instalar-Python
        if (-not $py) { Fallar "No se pudo instalar Python. Instalalo a mano desde https://www.python.org/downloads/ (marcando 'Add python.exe to PATH') y volve a ejecutar el instalador." }
        Ok "Python instalado: $py"
    }

    Paso 3 "Codigo de Clipadsk"
    Obtener-Codigo $Destino $enLugar
    # Archivos bajados de internet: quitar la marca para que Windows no los bloquee
    Get-ChildItem $Destino -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\backend\\venv\\' } |
        Unblock-File -ErrorAction SilentlyContinue

    Paso 4 "FFmpeg (conversion de audio y video)"
    Asegurar-FFmpeg $Destino

    Paso 5 "Dependencias de Python"
    Preparar-Entorno $Destino $py

    Paso 6 "Configuracion y accesos directos"
    $envFile = Join-Path $Destino '.env'
    if (-not (Test-Path $envFile)) {
        $plantilla = Join-Path $Destino '.env.template'
        if (Test-Path $plantilla) { Copy-Item $plantilla $envFile; Ok "Archivo .env creado" }
    } else {
        Ok ".env existente conservado"
    }
    Crear-Accesos $Destino

    Paso 7 "Abriendo Clipadsk"
    Start-Process -FilePath (Join-Path $Destino 'iniciar.bat') -WorkingDirectory $Destino -WindowStyle Minimized
    Ok "Se abre en el navegador en unos segundos"

    Titulo "Listo! Clipadsk quedo instalado"
    Write-Host ""
    Write-Host "  Para abrirlo de nuevo: icono 'Clipadsk' en el Escritorio." -ForegroundColor White
    Write-Host "  La primera vez te va a pedir una API Key gratis de Groq (console.groq.com)." -ForegroundColor White
    Write-Host "  Para actualizar: Configuracion > Actualizar aplicacion (o ejecutar este instalador de nuevo)." -ForegroundColor White
    Write-Host ""
}

$log = Join-Path $env:TEMP 'clipadsk-instalacion.log'
try { Start-Transcript -Path $log -Force | Out-Null } catch {}
try {
    Instalar
} catch {
    Write-Host ""
    Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Si no se resuelve, mandale este archivo a quien te paso Clipadsk:" -ForegroundColor Yellow
    Write-Host "  $log" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Presiona Enter para cerrar"
} finally {
    try { Stop-Transcript | Out-Null } catch {}
}
