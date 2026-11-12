"""
Clipa.exe — arranca Clipadsk sin ventanas y abre el navegador.

Dos modos, según lo que haya en la carpeta del exe:
  1. Instalado (existe backend/venv): usa esa instalación, igual que iniciar.bat. Así el exe
     siempre corre el código actual y las actualizaciones desde la app funcionan.
  2. Autónomo (sin instalación): corre el programa que viene dentro del exe. Los datos
     (historial, descargas, registro) quedan en la carpeta "clipadsk_datos" junto al exe;
     .env, cookies.txt y ffmpeg.exe se buscan al lado del exe.

Si Clipadsk ya está abierto, solo abre el navegador.
Opciones: --autonomo (fuerza el modo 2) · --sin-navegador
"""
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

FROZEN = getattr(sys, "frozen", False)
EXE_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
BUNDLE_DIR = getattr(sys, "_MEIPASS", EXE_DIR)
IS_WINDOWS = os.name == "nt"


def read_env_value(name: str, default: str) -> str:
    """Lee una variable del .env de la carpeta del exe (sin depender de python-dotenv)."""
    if os.environ.get(name):
        return os.environ[name]
    for env_file in (os.path.join(EXE_DIR, ".env"), os.path.join(EXE_DIR, "backend", ".env")):
        try:
            with open(env_file, encoding="utf-8-sig") as f:
                for line in f:
                    key, sep, value = line.strip().partition("=")
                    if sep and key.strip() == name and not line.lstrip().startswith("#"):
                        return value.strip().strip('"').strip("'") or default
        except OSError:
            continue
    return default


PORT = int(read_env_value("PORT", "5000"))
APP_URL = f"http://127.0.0.1:{PORT}/"
LOG_HINT = os.path.join(EXE_DIR, "backend", "clipadsk.log")


def message(text: str, error: bool = True):
    """Aviso en una ventanita (el exe no tiene consola)."""
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "Clipadsk", 0x10 if error else 0x40)
            return
        except Exception:
            pass
    print(text, file=sys.stderr if sys.stderr else None)


def clipa_running() -> bool:
    try:
        with urllib.request.urlopen(APP_URL + "api/health", timeout=2) as r:
            return r.status == 200 and b'"status"' in r.read(400)
    except Exception:
        return False


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def wait_for_server(timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if clipa_running():
            return True
        time.sleep(0.5)
    return False


def open_browser():
    if "--sin-navegador" not in sys.argv:
        webbrowser.open(APP_URL)


def venv_python():
    """Python de una instalación hecha con INSTALAR.bat en la carpeta del exe (o None)."""
    venv = os.path.join(EXE_DIR, "backend", "venv")
    for rel in (("Scripts", "pythonw.exe"), ("Scripts", "python.exe"), ("bin", "python3"), ("bin", "python")):
        path = os.path.join(venv, *rel)
        if os.path.exists(path):
            return path
    return None


def start_installed(python: str) -> bool:
    backend = os.path.join(EXE_DIR, "backend")
    flags = 0
    if IS_WINDOWS:
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([python, os.path.join(backend, "main.py")], cwd=backend, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True)
    return wait_for_server(90)


def start_bundled():
    """Corre el servidor dentro de este proceso (modo autónomo). No vuelve hasta que se cierra."""
    # En un exe sin consola stdout/stderr no existen: uvicorn y el logging fallarían.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    local_backend = os.path.join(EXE_DIR, "backend")
    if os.path.exists(os.path.join(local_backend, "main.py")):
        backend = local_backend            # hay código al lado del exe: se usa ese (más nuevo)
    else:
        backend = os.path.join(BUNDLE_DIR, "backend")
        os.environ.setdefault("CLIPA_DATA_DIR", os.path.join(EXE_DIR, "clipadsk_datos"))
    local_frontend = os.path.join(EXE_DIR, "frontend")
    os.environ.setdefault("FRONTEND_DIR", local_frontend if os.path.exists(os.path.join(local_frontend, "index.html"))
                          else os.path.join(BUNDLE_DIR, "frontend"))
    os.environ.setdefault("CLIPA_HOME", EXE_DIR)
    os.environ["PATH"] = EXE_DIR + os.pathsep + os.environ.get("PATH", "")  # ffmpeg.exe y yt-dlp.exe

    sys.path.insert(0, backend)
    os.chdir(backend)
    import uvicorn
    import main  # noqa: E402  (backend/main.py)

    threading.Thread(target=lambda: wait_for_server(90) and open_browser(), daemon=True).start()
    uvicorn.run(main.app, host=main.HOST, port=PORT, log_config=None, access_log=False, timeout_keep_alive=600)


def run():
    if clipa_running():
        open_browser()
        return
    if port_in_use():
        message(f"El puerto {PORT} está ocupado por otro programa.\n"
                f"Cerralo o cambiá PORT en el archivo .env de Clipadsk.")
        return
    python = None if "--autonomo" in sys.argv else venv_python()
    if python:
        if start_installed(python):
            open_browser()
        else:
            message("Clipadsk no arrancó a tiempo.\n\n"
                    f"Probá con iniciar.bat para ver el error, o revisá el registro:\n{LOG_HINT}")
        return
    if not FROZEN:
        message("No hay instalación en esta carpeta. Ejecutá INSTALAR.bat primero.")
        return
    try:
        start_bundled()
    except Exception as e:
        message(f"Clipadsk no pudo arrancar:\n\n{e}")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    run()
