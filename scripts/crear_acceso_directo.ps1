# Crea el acceso directo "Clipadsk" en el Escritorio.
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path
$destino = Join-Path $carpeta 'Clipa.exe'
if (-not (Test-Path $destino)) { $destino = Join-Path $carpeta 'iniciar.bat' }
$escritorio = [Environment]::GetFolderPath('Desktop')
$atajo = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $escritorio 'Clipadsk.lnk'))
$atajo.TargetPath = $destino
$atajo.WorkingDirectory = $carpeta
$icono = Join-Path $carpeta 'clipa.ico'
if (Test-Path $icono) { $atajo.IconLocation = $icono }
$atajo.Description = 'Clipadsk'
$atajo.Save()
Write-Host ''
Write-Host ('  Listo: acceso directo "Clipadsk" creado en ' + $escritorio)
