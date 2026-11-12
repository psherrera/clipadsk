@echo off
rem Doble clic: crea el acceso directo "Clipadsk" en el Escritorio.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\crear_acceso_directo.ps1"
echo.
pause
