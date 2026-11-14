# Activa o desactiva el uso de Clipadsk desde el celular (misma red Wi-Fi).
#   celular.ps1            -> activa: HOST=0.0.0.0, crea un PIN, abre el puerto en el firewall y reinicia
#   celular.ps1 -Desactivar -> vuelve a HOST=127.0.0.1 y cierra el puerto
# Solo ASCII a proposito (PowerShell 5.1 lee mal los acentos de un script sin BOM).
param([switch]$Desactivar)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
$regla = 'Clipadsk celular'
$puerto = 5000
$utf8 = New-Object System.Text.UTF8Encoding $false

function Leer-Env {
    if (Test-Path $envFile) { return [string[]][System.IO.File]::ReadAllLines($envFile, $utf8) }
    return [string[]]@()
}
function Poner-Var([string[]]$lineas, [string]$nombre, [string]$valor) {
    $salida = New-Object System.Collections.Generic.List[string]
    $hallada = $false
    foreach ($l in $lineas) {
        if ($l -match ('^\s*' + [regex]::Escape($nombre) + '\s*=')) {
            if (-not $hallada) { $salida.Add($nombre + '=' + $valor) }
            $hallada = $true
        } else { $salida.Add($l) }
    }
    if (-not $hallada) { $salida.Add($nombre + '=' + $valor) }
    return [string[]]$salida.ToArray()
}
function Valor-Env([string[]]$lineas, [string]$nombre) {
    foreach ($l in $lineas) {
        if ($l -match ('^\s*' + [regex]::Escape($nombre) + '\s*=\s*(.*)$')) { return $Matches[1].Trim() }
    }
    return ''
}
function Firewall-Admin([string]$orden) {
    $esAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($esAdmin) { Invoke-Expression $orden; return }
    Write-Host '  Windows va a pedir permiso de administrador para el firewall. Acepta.' -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $orden)
}

function Regla-Existe {
    # Leer las reglas no necesita permisos de administrador. Si falla, se asume que no existe.
    try {
        $r = Get-NetFirewallRule -DisplayName $regla -ErrorAction Stop | Select-Object -First 1
        return ($null -ne $r -and [string]$r.Enabled -eq 'True')
    } catch { return $false }
}

$lineas = Leer-Env
if ($Desactivar) {
    $lineas = Poner-Var $lineas 'HOST' '127.0.0.1'
    [System.IO.File]::WriteAllLines($envFile, $lineas, $utf8)
    # La regla del firewall se deja creada: con HOST=127.0.0.1 nadie escucha en la red, asi no hay que pedir
    # permiso de administrador de nuevo al volver a activar.
    Write-Host '  Acceso desde el celular DESACTIVADO.' -ForegroundColor Green
} else {
    $pin = Valor-Env $lineas 'ACCESS_PIN'
    if ($pin.Length -lt 6) { $pin = [string](Get-Random -Minimum 100000 -Maximum 999999) }
    $lineas = Poner-Var $lineas 'HOST' '0.0.0.0'
    $lineas = Poner-Var $lineas 'ACCESS_PIN' $pin
    [System.IO.File]::WriteAllLines($envFile, $lineas, $utf8)
    if (Regla-Existe) {
        Write-Host '  El puerto ya estaba abierto en el firewall: no hace falta pedir permiso.'
    } else {
        $orden = "Remove-NetFirewallRule -DisplayName '$regla' -ErrorAction SilentlyContinue; New-NetFirewallRule -DisplayName '$regla' -Direction Inbound -Protocol TCP -LocalPort $puerto -Action Allow -Profile Private | Out-Null"
        try { Firewall-Admin $orden } catch { Write-Host '  No se pudo abrir el puerto en el firewall: el celular puede no conectar.' -ForegroundColor Yellow }
    }
    Write-Host '  Acceso desde el celular ACTIVADO.' -ForegroundColor Green
}

Write-Host '  Reiniciando Clipadsk...'
& cmd /c (Join-Path $root 'REINICIAR.bat')
if (-not $Desactivar) {
    Start-Sleep -Seconds 8
    try {
        $info = Invoke-RestMethod ('http://127.0.0.1:' + $puerto + '/api/mobile/info') -TimeoutSec 5
        Write-Host ''
        foreach ($u in $info.urls) { Write-Host ('  Desde el celular abri: ' + $u) -ForegroundColor Cyan }
        Write-Host ('  PIN: ' + $info.pin) -ForegroundColor Cyan
        Write-Host '  (el QR esta en Configuracion > Usar desde el celular)'
        Write-Host '  El celular tiene que estar en el mismo Wi-Fi, y la red de la PC como "Privada".'
    } catch {
        Write-Host '  Clipadsk todavia esta arrancando: mira Configuracion > Usar desde el celular en unos segundos.'
    }
}
