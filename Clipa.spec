# -*- mode: python ; coding: utf-8 -*-
# Receta de PyInstaller para Clipa.exe. No se usa a mano: la corre CREAR_EXE.bat.
#
# El código de backend/ y frontend/ va DENTRO del exe como archivos (no compilado), para que
# el exe pueda preferir el código que esté al lado (más nuevo) y usar el de adentro solo si no hay.
import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(SPECPATH)
BACKEND = os.path.join(ROOT, 'backend')
BACKEND_MODULES = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(BACKEND, '*.py')))

hidden = list(BACKEND_MODULES)          # para que PyInstaller encuentre lo que usan
for pkg in ('uvicorn', 'yt_dlp', 'gallery_dl', 'instaloader', 'deep_translator', 'groq', 'docx', 'pydub',
            'cachetools', 'multipart', 'python_multipart', 'dotenv', 'fastapi', 'starlette', 'pydantic'):
    try:
        hidden += collect_submodules(pkg)
    except Exception:
        pass
try:  # complemento de yt-dlp para YouTube (opcional)
    hidden += collect_submodules('yt_dlp_plugins')
except Exception:
    pass

datas = [(os.path.join(ROOT, 'frontend'), 'frontend')]
datas += [(p, 'backend') for p in glob.glob(os.path.join(BACKEND, '*.py'))]
datas += [(os.path.join(BACKEND, 'requirements.txt'), 'backend')]
for pkg in ('docx', 'yt_dlp', 'gallery_dl', 'certifi'):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

a = Analysis(
    [os.path.join(ROOT, 'launcher.py')],
    pathex=[BACKEND],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=['faster_whisper', 'ctranslate2', 'torch', 'tkinter', 'matplotlib', 'IPython', 'pytest'],
    noarchive=False,
)
# Los módulos de backend NO van compilados adentro: se cargan desde backend/ (al lado o dentro del exe).
a.pure = [m for m in a.pure if m[0] not in BACKEND_MODULES]

pyz = PYZ(a.pure)
icon = os.path.join(ROOT, 'clipa.ico')
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Clipa',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon if os.path.exists(icon) else None,
)
