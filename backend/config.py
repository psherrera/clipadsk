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
_log_format = '[%(asctime)s] %(levelname)s %(name)s: %(message)s'
logging.basicConfig(level=LOG_LEVEL, format=_log_format)
# El servidor corre sin ventana (iniciar.bat): además se guarda un registro en backend/clipadsk.log
try:
    from logging.handlers import RotatingFileHandler
    _fh = RotatingFileHandler(os.path.join(BASE_DIR, 'clipadsk.log'), maxBytes=1_000_000, backupCount=2, encoding='utf-8')
    _fh.setFormatter(logging.Formatter(_log_format))
    logging.getLogger().addHandler(_fh)
except OSError:
    pass
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
# Groq retira modelos cada tanto (ago-2026: llama-3.x dejó de estar en el plan gratis).
# Por eso se usan LISTAS en orden de preferencia: la app pregunta a Groq qué modelos tiene
# la cuenta y usa el primero disponible; si uno falla por "model not found", pasa al siguiente.
# Se pueden cambiar en .env separando por comas (p. ej. GROQ_TEXT_MODELS=openai/gpt-oss-120b,...).
def _models(env_list: str, env_single: str, default: list) -> list:
    raw = os.environ.get(env_list, '')
    models = [m.strip() for m in raw.split(',') if m.strip()] or list(default)
    single = os.environ.get(env_single, '').strip()   # compatibilidad con .env viejos
    if single and single not in models:
        models.insert(0, single)
    return models

GROQ_TEXT_MODELS = _models('GROQ_TEXT_MODELS', 'GROQ_MODEL', [
    'openai/gpt-oss-120b', 'llama-3.3-70b-versatile', 'openai/gpt-oss-20b', 'qwen/qwen3.8-27b', 'llama-3.1-8b-instant'])
GROQ_CHAT_MODELS = _models('GROQ_CHAT_MODELS', 'GROQ_CHAT_MODEL', [
    'openai/gpt-oss-20b', 'llama-3.1-8b-instant', 'openai/gpt-oss-120b', 'llama-3.3-70b-versatile', 'qwen/qwen3.8-27b'])
GROQ_VISION_MODELS = _models('GROQ_VISION_MODELS', 'GROQ_VISION_MODEL', [
    'qwen/qwen3.8-27b', 'meta-llama/llama-4-scout-17b-16e-instruct', 'meta-llama/llama-4-maverick-17b-128e-instruct'])
GROQ_WHISPER_MODELS = _models('GROQ_WHISPER_MODELS', 'GROQ_WHISPER_MODEL', [
    'whisper-large-v3', 'whisper-large-v3-turbo'])
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
