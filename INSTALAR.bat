@echo off
rem Doble clic para instalar (o actualizar) Clipadsk en esta carpeta.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
