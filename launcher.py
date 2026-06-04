"""
launcher.py — Punto de entrada de Clipa.exe
Arranca el backend FastAPI en segundo plano y abre el navegador.
Modo silencioso: sin consola visible, sin ventana.
"""
import os
import sys
import time
import socket
import threading
import subprocess
import webbrowser
from pathlib import Path


# ── Detectar si corremos dentro de un .exe de PyInstaller ────────────────────
if getattr(sys, 'frozen', False):
    # Carpeta donde PyInstaller extrajo todo
    MEIPASS = Path(sys._MEIPASS)
    # Carpeta donde está el .exe (donde el usuario puso cookies.txt, etc.)
    EXE_DIR = Path(sys.executable).parent
else:
    # Desarrollo normal
    MEIPASS = Path(__file__).parent
    EXE_DIR = Path(__file__).parent

# ── Rutas clave ───────────────────────────────────────────────────────────────
BACKEND_DIR   = MEIPASS / "backend"
FRONTEND_DIR  = MEIPASS / "frontend"
FFMPEG_EXE    = MEIPASS / "ffmpeg.exe"
FFPROBE_EXE   = MEIPASS / "ffprobe.exe"
YTDLP_EXE     = MEIPASS / "yt-dlp.exe"
COOKIES_FILE  = EXE_DIR / "cookies.txt"   # el usuario lo pone al lado del .exe
DOWNLOADS_DIR = EXE_DIR / "downloads"
DB_FILE       = EXE_DIR / "clipadsk.db"
DOTENV_FILE   = EXE_DIR / ".env"

PORT = 5000
HEALTH_URL = f"http://127.0.0.1:{PORT}/api/health/cookies"
APP_URL = f"http://127.0.0.1:{PORT}/setup.html"


def patch_env():
    """Configura variables de entorno para que el backend encuentre todo."""
    # Añadir directorio de binarios al PATH
    bin_dir = str(MEIPASS)
    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    # Variables que lee main.py
    os.environ.setdefault("FRONTEND_DIR", str(FRONTEND_DIR))
    os.environ.setdefault("DOWNLOAD_DIR", str(DOWNLOADS_DIR))
    os.environ.setdefault("DB_FILE", str(DB_FILE))

    # Si hay .env al lado del .exe, cargarlo
    if DOTENV_FILE.exists():
        from dotenv import dotenv_values
        for k, v in dotenv_values(str(DOTENV_FILE)).items():
            os.environ.setdefault(k, v)

    # Silenciar logs del backend en modo portable
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    # Garantizar que el backend sepa dónde están las cookies
    if COOKIES_FILE.exists():
        os.environ["COOKIES_PATH"] = str(COOKIES_FILE)

    # Asegurar carpeta de descargas
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def wait_for_server(timeout: int = 60) -> bool:
    """Espera hasta que el servidor responda en el puerto."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(HEALTH_URL, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def start_backend():
    """Arranca uvicorn en un hilo usando el módulo main de backend."""
    # Añadir backend al path de Python
    sys.path.insert(0, str(BACKEND_DIR))
    sys.path.insert(0, str(MEIPASS))

    # Cambiar directorio de trabajo al backend para que las rutas relativas funcionen
    os.chdir(str(BACKEND_DIR))

    # Importar y arrancar uvicorn directamente (no como subprocess)
    import uvicorn

    # Necesitamos correr uvicorn en un thread con su propio event loop
    def run():
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=PORT,
            log_level="warning",   # silencioso
            access_log=False,
        )

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def main():
    # Si ya hay algo corriendo en el puerto, abrir directamente el navegador
    if not is_port_free(PORT):
        webbrowser.open(APP_URL)
        return

    patch_env()

    # Arrancar backend en background
    start_backend()

    # Esperar a que esté listo
    ready = wait_for_server(timeout=90)

    if ready:
        webbrowser.open(APP_URL)
    else:
        # Fallback: abrir igual por si acaso
        webbrowser.open(APP_URL)

    # Mantener el proceso vivo (el daemon thread del backend muere si el main sale)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
