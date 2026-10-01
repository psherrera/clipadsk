"""
Configuración central de Clipadsk: rutas, variables de entorno y logging.
Todo lo que se puede ajustar por .env está acá.
"""
import os
import shutil
import logging

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# .env en la raíz del proyecto (y, si existe, uno en backend/ que lo complementa)
load_dotenv(os.path.join(ROOT_DIR, '.env'))
load_dotenv(os.path.join(BASE_DIR, '.env'))

# ─── LOGGING ─────────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=LOG_LEVEL, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('clipadsk')


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


def _env_list(name: str) -> list:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


IS_RENDER = os.environ.get('RENDER') is not None

# ─── SERVIDOR ────────────────────────────────────────────────────────────────
# Por defecto solo escucha en esta PC. Para exponerlo en la red local poner HOST=0.0.0.0
# (y conviene definir ADMIN_TOKEN).
HOST = os.environ.get('HOST', '0.0.0.0' if IS_RENDER else '127.0.0.1')
PORT = int(os.environ.get('PORT', '5000'))
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '').strip()

_DEFAULT_ORIGINS = [
    f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}",
    "http://127.0.0.1", "http://localhost",          # frontend nginx (docker-compose)
]
ALLOWED_ORIGINS = _env_list('FRONTEND_ALLOWED_ORIGINS') or _DEFAULT_ORIGINS
if "*" in ALLOWED_ORIGINS:
    logger.warning("FRONTEND_ALLOWED_ORIGINS='*': cualquier página web puede usar esta API.")

# ─── RUTAS ───────────────────────────────────────────────────────────────────
FRONTEND_DIR = os.environ.get('FRONTEND_DIR') or os.path.join(ROOT_DIR, 'frontend')
if not os.path.isabs(FRONTEND_DIR):
    FRONTEND_DIR = os.path.normpath(os.path.join(BASE_DIR, FRONTEND_DIR))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')
DB_FILE = os.path.join(BASE_DIR, 'clipadsk.db')
CACHE_FILE = os.path.join(BASE_DIR, 'transcripts_cache.json')  # formato viejo (se migra)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ─── FFMPEG ──────────────────────────────────────────────────────────────────
FFMPEG_BIN = None
for _d in (ROOT_DIR, BASE_DIR):
    _candidate = os.path.join(_d, "ffmpeg.exe")
    if os.path.exists(_candidate):
        FFMPEG_BIN = _candidate
        os.environ["PATH"] += os.pathsep + _d
        break
if not FFMPEG_BIN:
    FFMPEG_BIN = shutil.which("ffmpeg")
HAS_FFMPEG = FFMPEG_BIN is not None
if not HAS_FFMPEG:
    logger.warning("FFmpeg no encontrado: no se podrá convertir audio ni unir video+audio.")

# ─── MODELOS DE IA ───────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '').strip() or None
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')              # limpieza y análisis
GROQ_FALLBACK_MODEL = os.environ.get('GROQ_FALLBACK_MODEL', 'llama-3.1-8b-instant')  # si hay rate limit
GROQ_CHAT_MODEL = os.environ.get('GROQ_CHAT_MODEL', 'llama-3.1-8b-instant')
GROQ_WHISPER_MODEL = os.environ.get('GROQ_WHISPER_MODEL', 'whisper-large-v3')
GROQ_VISION_MODEL = os.environ.get('GROQ_VISION_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
WHISPER_MODEL_SIZE = os.environ.get('WHISPER_MODEL', 'small')

# Límites para textos largos (en caracteres)
AI_CHUNK_CHARS = int(os.environ.get('AI_CHUNK_CHARS', '6000'))          # limpieza por partes
AI_CLEANUP_MAX_CHARS = int(os.environ.get('AI_CLEANUP_MAX_CHARS', '120000'))
ANALYSIS_CHUNK_CHARS = int(os.environ.get('ANALYSIS_CHUNK_CHARS', '12000'))
CHAT_CONTEXT_CHARS = int(os.environ.get('CHAT_CONTEXT_CHARS', '14000'))

# Audio: Groq acepta hasta 25 MB por archivo; partimos antes por seguridad
GROQ_MAX_UPLOAD_MB = float(os.environ.get('GROQ_MAX_UPLOAD_MB', '19'))
AUDIO_CHUNK_SECONDS = int(os.environ.get('AUDIO_CHUNK_SECONDS', str(20 * 60)))
MAX_UPLOAD_MB = int(os.environ.get('MAX_UPLOAD_MB', '500'))

# ─── CONCURRENCIA ────────────────────────────────────────────────────────────
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '4'))
MAX_CONCURRENT_JOBS = int(os.environ.get('MAX_CONCURRENT_JOBS', '2'))
