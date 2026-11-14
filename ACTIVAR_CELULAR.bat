@echo off
rem Doble clic: permite usar Clipadsk desde el celular (mismo Wi-Fi), con un PIN.
cd /d "%~dp0"
title Clipadsk en el celular
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\celular.ps1"
echo.
pause
