# clipa.spec — Configuración de PyInstaller para Clipa.exe
# Ejecutar desde la raíz del proyecto: pyinstaller clipa.spec

import os
from pathlib import Path

ROOT = Path(SPECPATH)  # PyInstaller define SPECPATH automáticamente

# ── Recolectar archivos de datos ──────────────────────────────────────────────
datas = []

# Frontend completo (HTML, CSS, JS, imágenes)
frontend_src = ROOT / "frontend"
if frontend_src.exists():
    datas.append((str(frontend_src), "frontend"))

# backend/main.py como módulo (y cualquier otro .py que necesite)
backend_src = ROOT / "backend"
if backend_src.exists():
    datas.append((str(backend_src / "main.py"), "backend"))

# .env.template por si el usuario quiere ver las variables disponibles
env_template = ROOT / ".env.template"
if env_template.exists():
    datas.append((str(env_template), "."))

# ── Binarios externos ─────────────────────────────────────────────────────────
binaries = []

for bin_name in ["ffmpeg.exe", "ffprobe.exe", "ffplay.exe", "yt-dlp.exe"]:
    bin_path = ROOT / bin_name
    if bin_path.exists():
        binaries.append((str(bin_path), "."))

# ── Hidden imports necesarios para FastAPI / uvicorn ─────────────────────────
hiddenimports = [
    # uvicorn
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # fastapi / starlette
    "fastapi",
    "fastapi.staticfiles",
    "fastapi.responses",
    "starlette",
    "starlette.routing",
    "starlette.staticfiles",
    "starlette.responses",
    "starlette.middleware",
    "starlette.middleware.cors",
    # pydantic
    "pydantic",
    "pydantic.v1",
    # otras dependencias del backend
    "yt_dlp",
    "yt_dlp.postprocessor",
    "groq",
    "deep_translator",
    "dotenv",
    "python_dotenv",
    "pydub",
    "instaloader",
    "requests",
    "multipart",
    "email",
    "email.mime",
    "email.mime.multipart",
    "sqlite3",
    "asyncio",
    # encodings necesarios en Windows
    "encodings",
    "encodings.utf_8",
    "encodings.utf_16",
    "encodings.ascii",
    "encodings.latin_1",
]

# ── Análisis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT), str(ROOT / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Excluir módulos pesados innecesarios
        "torch",
        "torchvision",
        "tensorflow",
        "matplotlib",
        "PIL",
        "Pillow",
        "tkinter",
        "wx",
        "PyQt5",
        "PySide2",
        "faster_whisper",
        "ctranslate2",
        "numpy",
        "pandas",
        "scipy",
        "jupyter",
        "IPython",
        "test",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Clipa",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX puede romper algunos dlls de Windows; desactivado para seguridad
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # Sin ventana de consola — modo silencioso
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "clipa.ico") if (ROOT / "clipa.ico").exists() else None,
    version=None,
    uac_admin=False,
    uac_uiaccess=False,
)
