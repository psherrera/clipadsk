@echo off
rem Doble clic para generar Clipa.exe (usa la instalacion de esta carpeta).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_exe.ps1"
echo.
pause
