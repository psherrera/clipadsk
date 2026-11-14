@echo off
rem Doble clic: Clipadsk vuelve a funcionar solo en esta PC.
cd /d "%~dp0"
title Clipadsk solo en esta PC
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\celular.ps1" -Desactivar
echo.
pause
