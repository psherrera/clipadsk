@echo off
rem Doble clic: crea el acceso directo "Clipadsk" en el Escritorio.
cd /d "%~dp0"
set "DESTINO=%~dp0Clipa.exe"
if not exist "%DESTINO%" set "DESTINO=%~dp0iniciar.bat"
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath(Desktop); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d Clipadsk.lnk)); $s.TargetPath=$env:DESTINO; $s.WorkingDirectory=(Get-Location).Path; $s.IconLocation=(Join-Path (Get-Location).Path clipa.ico); $s.WindowStyle=7; $s.Description=Clipadsk; $s.Save(); Write-Host (  Listo: acceso directo creado en  + $d)"
echo.
pause
