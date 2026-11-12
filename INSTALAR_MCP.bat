@echo off
rem Doble clic: conecta Clipadsk con Claude Desktop (servidor MCP "clipa").
cd /d "%~dp0"
title Clipa para Claude
if not exist "backend\venv\Scripts\python.exe" (
    echo.
    echo   Primero hay que instalar Clipadsk: ejecuta INSTALAR.bat
    echo.
    pause
    exit /b 1
)
echo.
echo   Instalando lo necesario...
backend\venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r clipa_mcp\requirements.txt
if errorlevel 1 (
    echo   No se pudo instalar. Revisa la conexion a internet.
    pause
    exit /b 1
)
echo   Registrando Clipa en Claude Desktop...
backend\venv\Scripts\python.exe clipa_mcp\instalar.py
echo.
echo   Listo. Cerra Claude Desktop del todo (tambien desde el icono junto al reloj)
echo   y volvelo a abrir. En un chat nuevo vas a ver las herramientas de "clipa".
echo.
pause
