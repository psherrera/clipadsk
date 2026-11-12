@echo off
rem Doble clic: cierra el servidor de Clipadsk que quedo abierto (aunque no se vea) y lo vuelve a abrir.
cd /d "%~dp0"
title Reiniciar Clipadsk
echo.
echo   Cerrando el Clipadsk que estaba abierto...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":5000 .*LISTENING"') do taskkill /F /PID %%p >nul 2>&1
timeout /t 2 /nobreak >nul
echo   Abriendo Clipadsk de nuevo...
if exist "%~dp0Clipa.exe" (
    start "" "%~dp0Clipa.exe"
) else (
    start "" "%~dp0iniciar.bat"
)
timeout /t 3 /nobreak >nul
