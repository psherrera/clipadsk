"""
YT Downloader Pro - Backend
Optimized for Render.com deployment.
Features: 
- Heavy dependency removal (Whisper/Torch).
- Groq API & YouTube Subtitle fallback for transcription.
- Robust Bot-Evasion strategy using mobile client emulation.
- Automated cleanup of downloaded files.
"""
# --- CONFIGURACION DE RUTAS ---
import os
import sys
import subprocess
import re

import uuid
import json
import gc
import tempfile
import yt_dlp
import requests
from typing import Optional, List, Any
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from deep_translator import GoogleTranslator
from fastapi import Response
from fastapi.staticfiles import StaticFiles
import asyncio
import base64
import random
import time
import sqlite3
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import functools
try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None

try:
    import instaloader
except ImportError:
    instaloader = None

try:
    from faster_whisper import WhisperModel
    WHISPER_MODEL_AVAILABLE = True
except ImportError:
    WhisperModel = None
    WHISPER_MODEL_AVAILABLE = False

from dotenv import load_dotenv

# --- LOGGING (configured early so other modules can use logger) ---
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
import logging
logging.basicConfig(level=LOG_LEVEL, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('clipadsk')

# --- AÑADIR RAÍZ AL PATH PARA ENCONTRAR FFMPEG SI ESTÁ AHÍ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
FFMPEG_BIN = None

# Buscar en raiz, luego en backend, luego en sistema
for d in [ROOT_DIR, BASE_DIR]:
    if os.path.exists(os.path.join(d, "ffmpeg.exe")):
        FFMPEG_BIN = os.path.join(d, "ffmpeg.exe")
        os.environ["PATH"] += os.pathsep + d
        if AudioSegment:
            AudioSegment.converter = FFMPEG_BIN
            logger.debug(f"Pydub configurado con FFmpeg en {FFMPEG_BIN}")
        break
# -----------------------------------------------------------
# --- CONFIGURACIÓN DE ENTORNO ---
load_dotenv() # Cargar variables desde .env
IS_RENDER = os.environ.get('RENDER') is not None
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')  # configurable via env
GROQ_CHAT_MODEL = os.environ.get('GROQ_CHAT_MODEL', 'llama-3.1-8b-instant')
WHISPER_MODEL_SIZE = os.environ.get('WHISPER_MODEL', 'small')
WHISPER_MODEL = None

try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except ImportError:
    groq_client = None

app = FastAPI(title="YT Downloader Pro API")

# --- BACKGROUND EXECUTOR ---
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '3'))
MAX_CONCURRENT_JOBS = int(os.environ.get('MAX_CONCURRENT_JOBS', '2'))
EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

# --- RESULT STORE (para recuperar transcripciones si la conexión se corta) ---
# Guarda resultados por uid durante 1 hora para que el frontend pueda recuperarlos
RESULT_STORE: dict = {}  # uid -> {"result": ..., "ts": timestamp}
RESULT_STORE_TTL = 3600  # 1 hora

def store_result(uid: str, result: dict):
    """Guarda el resultado de una transcripción en memoria."""
    RESULT_STORE[uid] = {"result": result, "ts": time.time()}
    # Limpiar entradas viejas
    cutoff = time.time() - RESULT_STORE_TTL
    expired = [k for k, v in RESULT_STORE.items() if v["ts"] < cutoff]
    for k in expired:
        RESULT_STORE.pop(k, None)

def get_stored_result(uid: str):
    """Recupera el resultado de una transcripción guardada, si existe."""
    entry = RESULT_STORE.get(uid)
    if entry:
        return entry["result"]
    return None


async def run_blocking(fn: Any, *args, **kwargs):
    """Run a blocking function in a controlled threadpool with semaphore."""
    async with SEMAPHORE:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(EXECUTOR, functools.partial(fn, *args, **kwargs))


def extract_info_sync(opts, url):
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def ydl_download_sync(opts, url):
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


def requests_get_sync(url, **kwargs):
    return requests.get(url, **kwargs)

# Configuración de CORS
allowed = os.environ.get('FRONTEND_ALLOWED_ORIGINS')
if allowed:
    allow_list = [o.strip() for o in allowed.split(',') if o.strip()]
else:
    allow_list = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MIDDLEWARE DE LOGGING ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Logeamos solo peticiones a la API para no saturar con estáticos
    if request.url.path.startswith("/api/"):
        logger.debug(f"API request: {request.method} {request.url.path}")
    response = await call_next(request)
    return response

# --- RUTAS DERIVADAS (usan BASE_DIR/ROOT_DIR ya definidos arriba) ---
# Si se provee FRONTEND_DIR por env (Docker/Render), la usamos prioritariamente
FRONTEND_DIR = os.environ.get('FRONTEND_DIR') or os.path.join(ROOT_DIR, 'frontend')
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')
CACHE_FILE = os.path.join(BASE_DIR, 'transcripts_cache.json')

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# --- BASE DE DATOS (SQLite) ---
DB_FILE = os.path.join(BASE_DIR, 'clipadsk.db')

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS transcripts 
                 (url TEXT PRIMARY KEY, transcript TEXT, date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Migración desde JSON antiguo si existe
    if os.path.exists(CACHE_FILE):
        logger.info("Migrando historial de JSON a SQLite...")
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                for url, text in old_data.items():
                    c.execute("INSERT OR IGNORE INTO transcripts (url, transcript) VALUES (?, ?)", (url, text))
            conn.commit()
            # Renombrar archivo viejo para evitar re-migración
            os.rename(CACHE_FILE, CACHE_FILE + ".migrated")
            logger.info("Migración completada con éxito.")
        except Exception as e:
            logger.exception("Error en migración de cache JSON a SQLite")
    conn.close()

# Inicializar DB al arrancar
init_db()

def load_cache():
    """Mantiene compatibilidad con el código existente pero lee de SQLite."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT url, transcript FROM transcripts")
        rows = c.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.exception("Error leyendo cache desde SQLite")
        return {}

def save_cache_entry(url, transcript):
    """Guarda una entrada individual en la DB."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO transcripts (url, transcript) VALUES (?, ?)", (url, transcript))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.exception("Error guardando entrada en SQLite")

def save_cache(cache):
    """Mantiene compatibilidad (aunque es menos eficiente que save_cache_entry)."""
    # En el flujo actual, save_cache se llama con todo el dict.
    # Para SQLite es mejor guardar solo el nuevo, pero para no romper el flujo:
    for url, text in cache.items():
        save_cache_entry(url, text)


# --- TRADUCCIÓN ---
def translate_to_spanish(text):
    if not text: return ""
    try:
        translator = GoogleTranslator(source='auto', target='es')
        if len(text) > 4000:
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            translated = [translator.translate(c) for c in chunks]
            return " ".join(translated)
        return translator.translate(text)
    except Exception as e:
        logger.exception("Error en traducción")
        return text

def get_local_groq(api_key: str = None):
    if api_key and api_key.strip():
        try:
            from groq import Groq
            return Groq(api_key=api_key.strip())
        except Exception:
            return groq_client
    return groq_client


def get_whisper_model():
    global WHISPER_MODEL
    if not WHISPER_MODEL_AVAILABLE:
        return None
    if WHISPER_MODEL is None:
        try:
            logger.info(f"Cargando modelo Whisper local: {WHISPER_MODEL_SIZE}")
            WHISPER_MODEL = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
        except Exception as e:
            logger.exception(f"No se pudo cargar el modelo Whisper local: {e}")
            WHISPER_MODEL = None
    return WHISPER_MODEL


def parse_time_to_seconds(t_str: str) -> float:
    t_str = t_str.replace(',', '.')
    parts = t_str.split(':')
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600 + float(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60 + float(s)
    return 0.0


def parse_subtitles_to_segments(content: str) -> list:
    segments = []
    # Match standard timestamp line: HH:MM:SS.mmm --> HH:MM:SS.mmm or MM:SS.mmm --> MM:SS.mmm
    pattern = re.compile(r'(\d+(?::\d+)*[\.,]\d{3})\s*-->\s*(\d+(?::\d+)*[\.,]\d{3})')
    # Pattern to remove leftover inline VTT word-level timestamps (e.g. '02:14' stuck to words)
    inline_ts = re.compile(r'\b\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*')
    
    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = pattern.search(line)
        if match:
            start_str, end_str = match.groups()
            start = parse_time_to_seconds(start_str)
            end = parse_time_to_seconds(end_str)
            
            # Read subsequent lines until we hit an empty line or another timestamp
            text_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                # If we see another timestamp or start of next block, break
                if pattern.search(next_line) or (next_line.isdigit() and i + 1 < len(lines) and pattern.search(lines[i+1])):
                    i -= 1 # Step back so outer loop processes it
                    break
                if next_line == "" or next_line.startswith("WEBVTT") or next_line.startswith("Kind:") or next_line.startswith("Language:"):
                    # skip empty or header lines
                    pass
                else:
                    # Pass 1: Clean XML-like tags (e.g. <c.colorWhite>, <00:02:14.000>)
                    cleaned_line = re.sub(r'<[^>]*>', '', next_line).strip()
                    # Pass 2: Remove any leftover inline timestamps (e.g. '02:14' stuck to text)
                    cleaned_line = inline_ts.sub('', cleaned_line).strip()
                    if cleaned_line:
                        text_lines.append(cleaned_line)
                i += 1
            
            text = " ".join(text_lines).strip()
            if text:
                segments.append({"start": start, "end": end, "text": text})
        i += 1
    return segments


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = int(round((seconds % 1) * 1000))
    total_seconds = int(seconds)
    if milliseconds >= 1000:
        milliseconds -= 1000
        total_seconds += 1
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def generate_srt_from_segments(segments) -> str:
    srt_lines = []
    for i, segment in enumerate(segments, start=1):
        if isinstance(segment, dict):
            start = segment.get("start", 0)
            end = segment.get("end", 0)
            text = segment.get("text", "").strip()
        else:
            start = getattr(segment, "start", 0)
            end = getattr(segment, "end", 0)
            text = getattr(segment, "text", "").strip()
        
        start_str = format_srt_timestamp(start)
        end_str = format_srt_timestamp(end)
        srt_lines.append(f"{i}")
        srt_lines.append(f"{start_str} --> {end_str}")
        srt_lines.append(text)
        srt_lines.append("")
    return "\n".join(srt_lines)


def transcribe_with_local_whisper(audio_file_path: str, target_lang: str = "es"):
    model = get_whisper_model()
    if not model:
        raise RuntimeError("No hay modelo Whisper local disponible. Instala faster-whisper para usar este modo.")

    logger.info(f"Transcribiendo audio local con Whisper ({target_lang})...")
    segments, info = model.transcribe(
        audio_file_path,
        beam_size=5,
        vad_filter=True,
        language=target_lang if target_lang in ["es", "en"] else None
    )
    segments = list(segments)
    transcription = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    srt_content = generate_srt_from_segments(segments)
    logger.info(f"Transcripción local completada. Duración aprox: {getattr(info, 'duration', 'desconocida')}s")
    return transcription, srt_content



def remove_repetitions(text: str) -> str:
    """
    Elimina repeticiones de frases que Whisper (y subtítulos VTT) generan.
    Usa un algoritmo de ventana deslizante que no consume tokens de Groq.
    Ejemplo de entrada:  "Cómo andan tanto tiempo Cómo andan tanto tiempo los extrañé"
    Ejemplo de salida:   "Cómo andan tanto tiempo los extrañé"
    """
    if not text or len(text) < 30:
        return text

    words = text.split()
    if len(words) < 6:
        return text

    result = []
    i = 0
    MAX_PHRASE = min(30, len(words) // 2)

    while i < len(words):
        found_repeat = False
        # Probar ventanas desde las más grandes a las más pequeñas
        for phrase_len in range(MAX_PHRASE, 3, -1):
            if i + phrase_len * 2 > len(words):
                continue
            phrase = words[i:i + phrase_len]
            next_phrase = words[i + phrase_len:i + phrase_len * 2]
            if phrase == next_phrase:
                result.extend(phrase)
                i += phrase_len
                # Colapsar repeticiones consecutivas adicionales del mismo fragmento
                while i + phrase_len <= len(words) and words[i:i + phrase_len] == phrase:
                    i += phrase_len
                found_repeat = True
                break
        if not found_repeat:
            result.append(words[i])
            i += 1

    cleaned = ' '.join(result)
    logger.debug(f"remove_repetitions: {len(words)} palabras → {len(result)} palabras")
    return cleaned


def cleanup_transcript_with_ai(text: str, client=None, target_lang="es", is_local_video=False) -> str:
    """Usa la IA para limpiar repeticiones, corregir puntuación y añadir párrafos en el idioma elegido."""
    actual_client = client or groq_client
    if not actual_client or len(text) < 50:
        return text

    if len(text) > 40000:
        logger.info(f"Transcripción muy larga ({len(text)} caracteres). Omitiendo limpieza IA para evitar límites de API.")
        return text
    
    lang_name = "Español" if target_lang == "es" else ("Inglés" if target_lang == "en" else "el idioma original del video")
    
    try:
        max_chunk_length = 6000
        if len(text) > max_chunk_length:
            chunks = [text[i:i+max_chunk_length] for i in range(0, len(text), max_chunk_length)]
            cleaned_chunks = []
            for chunk in chunks:
                if is_local_video:
                    prompt = f"""Actúa como un corrector de estilo estricto. Tu único objetivo es tomar esta transcripción cruda y aplicar correcciones ortotipográficas para facilitar su lectura, manteniendo el 100% del contenido original hablado.

Instrucciones de edición:

Preservación absoluta: NO resumas, NO unifiques temas, NO omitas redundancias ni cambies las palabras del entrevistado o entrevistador. Los periodistas necesitan la desgrabación exacta para extraer sus propias citas.

Corrección de formato: Limítate a corregir puntuación (comas, puntos, signos de interrogación), uso de mayúsculas y separar correctamente los párrafos para que el bloque de texto sea legible.

Limpieza mínima: Solo puedes limpiar tartamudeos o muletillas extremas (ej. "eh...", "este...") si interrumpen gravemente la lectura, pero no debes eliminar ninguna anécdotas, dato repetido o interacción de la mesa.

Regla estricta de formato (Cero Artefactos):
Tu respuesta debe contener ÚNICAMENTE la desgrabación procesada. Está estrictamente prohibido incluir saludos, introducciones (como "Aquí tienes la desgrabación" o "Texto corregido:"), viñetas explicativas o conclusiones al final. Empieza directamente con la primera palabra de la entrevista y termina con el último punto.

Procesa el texto que se encuentra a continuación entre las etiquetas [INICIO DEL TEXTO] y [FIN DEL TEXTO]:

[INICIO DEL TEXTO]
{chunk}
[FIN DEL TEXTO]"""
                else:
                    prompt = f"""Sos un editor experto. Tu tarea es LIMPIAR y FORMATEAR esta parte de una transcripción.
                    1. ELIMINÁ repeticiones de frases.
                    2. AGREGÁ puntuación (comas, puntos).
                    3. DIVIDÍ en párrafos con doble salto de línea.
                    4. EL IDIOMA DE SALIDA DEBE SER: {lang_name}.
                    5. NO RESUMAS, mantené el contenido original.
                    TEXTO:
                    {chunk}"""
                completion = actual_client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=4000,
                )
                cleaned_chunks.append(completion.choices[0].message.content.strip())
            return "\n\n".join(cleaned_chunks)
        else:
            if is_local_video:
                prompt = f"""Actúa como un corrector de estilo estricto. Tu único objetivo es tomar esta transcripción cruda y aplicar correcciones ortotipográficas para facilitar su lectura, manteniendo el 100% del contenido original hablado.

Instrucciones de edición:

Preservación absoluta: NO resumas, NO unifiques temas, NO omitas redundancias ni cambies las palabras del entrevistado o entrevistador. Los periodistas necesitan la desgrabación exacta para extraer sus propias citas.

Corrección de formato: Limítate a corregir puntuación (comas, puntos, signos de interrogación), uso de mayúsculas y separar correctamente los párrafos para que el bloque de texto sea legible.

Limpieza mínima: Solo puedes limpiar tartamudeos o muletillas extremas (ej. "eh...", "este...") si interrumpen gravemente la lectura, pero no debes eliminar ninguna anécdotas, dato repetido o interacción de la mesa.

Regla estricta de formato (Cero Artefactos):
Tu respuesta debe contener ÚNICAMENTE la desgrabación procesada. Está estrictamente prohibido incluir saludos, introducciones (como "Aquí tienes la desgrabación" o "Texto corregido:"), viñetas explicativas o conclusiones al final. Empieza directamente con la primera palabra de la entrevista y termina con el último punto.

Procesa el texto que se encuentra a continuación entre las etiquetas [INICIO DEL TEXTO] y [FIN DEL TEXTO]:

[INICIO DEL TEXTO]
{text}
[FIN DEL TEXTO]"""
            else:
                prompt = f"""Sos un editor experto. Tu tarea es LIMPIAR y FORMATEAR la siguiente transcripción de un video.
                1. ELIMINÁ repeticiones de frases.
                2. AGREGÁ puntuación correcta (comas, puntos).
                3. DIVIDÍ el texto en párrafos lógicos con doble salto de línea.
                4. EL IDIOMA DE SALIDA DEBE SER: {lang_name}.
                5. NO RESUMAS, mantené el contenido original.
                TRANSCRIPCIÓN:
                {text}"""
            completion = actual_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=4000,
            )
            return completion.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("Error limpiando transcripción con IA")
        return text


# --- PROGRESO GLOBAL (TTLCache: auto-limpia entradas > 2h para evitar memory leak) ---
try:
    from cachetools import TTLCache
    progress_store = TTLCache(maxsize=500, ttl=7200)
    log_store      = TTLCache(maxsize=500, ttl=7200)
except ImportError:
    # cachetools no instalado — fallback a dict simple
    progress_store = {}
    log_store = {}
    logger.warning("cachetools no disponible. progress_store y log_store usarán dict simple (sin TTL).")

def update_progress(uid: str, progress: int, text: str):
    if uid:
        progress_store[uid] = {"progress": progress, "text": text}
        add_log(uid, f"Progreso {progress}%: {text}")

def add_log(uid: str, message: str):
    if not uid: return
    if uid not in log_store: log_store[uid] = []
    timestamp = time.strftime("%H:%M:%S")
    log_store[uid].append(f"[{timestamp}] {message}")
    logger.debug(f"LOG [{uid}]: {message}")

def get_session_logs(uid: str) -> str:
    return "\n".join(log_store.get(uid, ["No hay logs disponibles para esta sesion."]))

@app.get("/api/progress/{uid}")
async def get_progress(uid: str):
    return progress_store.get(uid, {"progress": 0, "text": "Procesando en el servidor..."})

# --- MODELOS DE DATOS ---
class VideoRequest(BaseModel):
    url: str
    format_id: Optional[str] = "best"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    groq_api_key: Optional[str] = None
    uid: Optional[str] = None
    target_lang: Optional[str] = "es" # es, en, original

@app.get("/api/logs/{uid}")
async def get_logs(uid: str):
    return JSONResponse(content={"logs": get_session_logs(uid)})




# --- ENDPOINTS ---



# --- SANITIZACIÓN DE URLS ---
def sanitize_url(url: str) -> str:
    """
    Normaliza URLs de video antes de pasarlas a yt-dlp.
    Problemas que resuelve:
    - youtu.be/ID?si=... → youtube.com/watch?v=ID
    - watch?v=ID&feature=youtu.be → watch?v=ID
    - Elimina parámetros de tracking/referral que confunden a yt-dlp
    """
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    url = url.strip()

    try:
        parsed = urlparse(url)
        
        # Convertir youtu.be → youtube.com/watch?v=
        if parsed.netloc in ('youtu.be', 'www.youtu.be'):
            video_id = parsed.path.lstrip('/')
            if video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
                parsed = urlparse(url)
        
        # Para URLs de YouTube, limpiar parámetros no esenciales
        if 'youtube.com' in parsed.netloc:
            qs = parse_qs(parsed.query, keep_blank_values=False)
            # Solo conservar v, list, index, t (tiempo)
            clean_params = {k: v for k, v in qs.items() if k in ('v', 'list', 'index', 't')}
            new_query = urlencode({k: v[0] for k, v in clean_params.items()})
            url = urlunparse(parsed._replace(query=new_query))
    except Exception as e:
        logger.debug(f"sanitize_url error, usando original: {e}")

    logger.debug(f"URL sanitizada → {url}")
    return url


def get_robust_opts(target_url, extra={}):
    """Genera opciones unificadas para yt-dlp con soporte para cookies locales y de entorno."""
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1'
    ]

    is_instagram = 'instagram.com' in target_url
    is_youtube = 'youtube.com' in target_url or 'youtu.be' in target_url
    is_tiktok = 'tiktok.com' in target_url or 'vm.tiktok.com' in target_url
    is_twitter = 'twitter.com' in target_url or 'x.com' in target_url or 't.co' in target_url
    is_facebook = 'facebook.com' in target_url or 'fb.watch' in target_url or 'fb.com' in target_url

    cookie_path = os.path.join(BASE_DIR, 'cookies.txt')
    ig_cookie_path = os.path.join(BASE_DIR, 'cookies_ig.txt')
    # Soporte para modo portable (.exe): el launcher inyecta COOKIES_PATH
    # apuntando al archivo al lado del .exe
    portable_cookie_path = os.environ.get('COOKIES_PATH', '')

    opts = {
        'quiet': False,
        'no_warnings': False,
        'cachedir': False,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'user_agent': random.choice(USER_AGENTS),
        **extra
    }

    # Seleccionar cookies según plataforma
    if is_instagram:
        cookie_b64 = os.environ.get('INSTAGRAM_COOKIES_B64') or os.environ.get('COOKIES_B64')
        # Buscar primero cookies_ig.txt y usar cookies.txt como fallback
        local_paths = ['/etc/secrets/cookies_ig.txt', ig_cookie_path, '/etc/secrets/cookies.txt', cookie_path]
        if portable_cookie_path:
            local_paths.insert(0, portable_cookie_path)
    else:
        cookie_b64 = os.environ.get('COOKIES_B64')
        local_paths = ['/etc/secrets/cookies.txt', cookie_path]
        if portable_cookie_path:
            local_paths.insert(0, portable_cookie_path)

    # Cargar cookies desde variable de entorno
    if cookie_b64:
        try:
            cookie_data = base64.b64decode(cookie_b64).decode()
            temp_cookie = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            temp_cookie.write(cookie_data)
            temp_cookie.close()
            opts['cookiefile'] = temp_cookie.name
            platform = 'Instagram' if is_instagram else 'YouTube'
            logger.debug(f"Cargando cookies [{platform}] desde variable de entorno (Temp: {temp_cookie.name})")
        except Exception as e:
            logger.exception("Error cargando cookies desde variable de entorno")

    # Fallback a archivo local
    if 'cookiefile' not in opts:
        for path_candidate in local_paths:
            if os.path.exists(path_candidate):
                logger.debug(f"Cargando cookies desde archivo {path_candidate}")
                opts['cookiefile'] = path_candidate
                break

    # Estrategia específica por plataforma
    if is_youtube:
        # Dejamos que yt-dlp use sus clientes por defecto (web, tv, etc.) para que encuentre todas las calidades (1080p, 720p)
        opts['user_agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1'
        logger.debug(f"Estrategia YouTube optimizada (Cookies: {'Si' if 'cookiefile' in opts else 'No'})")

    elif is_tiktok:
        # TikTok requiere user-agent móvil y headers específicos
        opts['user_agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1'
        opts['http_headers'] = {
            'Referer': 'https://www.tiktok.com/',
            'Accept-Language': 'es-419,es;q=0.9,en;q=0.8',
        }

    elif is_twitter:
        # Twitter/X funciona mejor con user-agent desktop Chrome reciente
        opts['user_agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

    elif is_facebook:
        # Facebook requiere cookies para la mayoría del contenido público
        opts['user_agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

    return opts

# --- INSTAGRAM CON INSTALOADER ---

def get_instagram_info(url):
    """Extrae info de un Reel/Video de Instagram usando instaloader."""
    if not instaloader:
        raise Exception("instaloader no está instalado")

    ig_user = os.environ.get('IG_USER', '')
    ig_pass = os.environ.get('IG_PASS', '')

    L = instaloader.Instaloader(
        download_videos=True,
        download_video_thumbnails=True,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )

    if ig_user and ig_pass:
        try:
            L.login(ig_user, ig_pass)
            logger.debug(f"Instaloader login OK como {ig_user}")
        except Exception as e:
            logger.debug(f"Instaloader login falló: {e}")

    match = re.search(r'/(reel|p|tv)/([A-Za-z0-9_-]+)', url)
    if not match:
        raise Exception("No se pudo extraer el shortcode del URL de Instagram")

    shortcode = match.group(2)
    logger.debug(f"Instaloader extrayendo shortcode: {shortcode}")

    post = instaloader.Post.from_shortcode(L.context, shortcode)

    title = post.caption[:100] if post.caption else f"Instagram Reel {shortcode}"

    try:
        thumbnail = post.url
    except:
        thumbnail = None

    return {
        'shortcode': shortcode,
        'title': title,
        'thumbnail': thumbnail,
        'duration': int(post.video_duration) if post.is_video and post.video_duration else None,
        'uploader': post.owner_username,
        'is_video': post.is_video,
        'video_url': post.video_url if post.is_video else None,
    }

def get_instagram_carousel_info(url, cookies_path=None):
    """Extrae la lista de imágenes/videos de un carrusel de Instagram usando gallery-dl."""
    venv_dir = os.path.join(ROOT_DIR, "backend", "venv")
    gallery_dl_bin = os.path.join(venv_dir, "Scripts", "gallery-dl.exe")
    if not os.path.exists(gallery_dl_bin):
        gallery_dl_bin = "gallery-dl" # fallback al path del sistema
        
    cmd = [gallery_dl_bin, "-j"]
    if cookies_path and os.path.exists(cookies_path):
        cmd.extend(["--cookies", cookies_path])
    cmd.append(url)
    
    logger.info(f"Ejecutando gallery-dl: {cmd}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
        if res.returncode != 0:
            logger.warning(f"gallery-dl falló con código {res.returncode}: {res.stderr}")
            return None
        
        data = json.loads(res.stdout)
        files = []
        for item in data:
            if isinstance(item, list) and len(item) >= 3 and item[0] == 3:
                files.append({
                    "url": item[1],
                    "metadata": item[2]
                })
        return files
    except Exception as e:
        logger.exception(f"Error extrayendo carrusel con gallery-dl: {e}")
        return None

# --- ENDPOINTS ---

@app.post("/api/video-info")
async def get_video_info(req: VideoRequest, request: Request):
    url = sanitize_url(req.url)
    is_instagram = 'instagram.com' in url

    # --- INSTAGRAM: usar instaloader ---
    if is_instagram and instaloader:
        try:
            ig_info = await asyncio.to_thread(get_instagram_info, url)
            if ig_info['is_video']:
                formats = [
                    {'format_id': 'best', 'ext': 'mp4', 'resolution': 'Mejor calidad', 'filesize': None, 'label': 'Mejor calidad (.mp4)'},
                    {'format_id': 'mp3',  'ext': 'mp3', 'resolution': 'Solo audio',    'filesize': None, 'label': 'Solo audio (.mp3)'},
                ]
            else:
                formats = [{'format_id': 'best', 'ext': 'jpg', 'resolution': 'Imagen original', 'filesize': None, 'label': 'Imagen original (.jpg)'}]

            thumbnail = ig_info.get('thumbnail')
            if thumbnail:
                from urllib.parse import quote
                thumbnail = f"/api/proxy-thumbnail?url={quote(thumbnail, safe='')}"

            return {
                'title': ig_info['title'],
                'thumbnail': thumbnail,
                'max_res_thumbnail': thumbnail,
                'duration': ig_info.get('duration'),
                'uploader': ig_info.get('uploader', 'Instagram'),
                'description': ig_info['title'],
                'formats': formats,
                'has_ffmpeg': True,
                'has_subtitles': False,
            }
        except Exception as e:
            logger.debug(f"Instaloader falló, intentando con yt-dlp: {e}")

    is_youtube = 'youtube.com' in url or 'youtu.be' in url

    info = None
    last_error = ""
    
    # --- INTENTO 1: Estrategia Optimizada (Basada en get_robust_opts) ---
    try:
        logger.debug("Intento 1 - Estrategia optimizada...")
        opts = get_robust_opts(url)
        info = await run_blocking(extract_info_sync, opts, url)
    except Exception as e:
        last_error = str(e)
        logger.debug(f"Intento 1 falló: {last_error[:100]}")

    # --- INTENTO 2: Forzar Móvil SIN COOKIES (Para saltar n-challenge) ---
    if not info and is_youtube:
        try:
            logger.debug("Intento 2 - Forzando móvil SIN cookies...")
            opts = get_robust_opts(url)
            opts.pop('cookiefile', None) # Quitamos cookies para que no las ignore
            opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios']}}
            info = await run_blocking(extract_info_sync, opts, url)
        except Exception as e:
            last_error += f" | Intento 2: {str(e)[:100]}"
            logger.debug(f"Intento 2 falló: {str(e)[:100]}")

    # --- INTENTO 3: Forzar iOS (Último recurso) ---
    if not info and is_youtube:
        try:
            logger.debug("Intento 3 - Forzando solo iOS...")
            opts = get_robust_opts(url)
            opts.pop('cookiefile', None)
            opts['extractor_args'] = {'youtube': {'player_client': ['ios']}}
            info = await run_blocking(extract_info_sync, opts, url)
        except Exception as e:
            last_error += f" | Intento 3: {str(e)[:100]}"
            logger.debug(f"Intento 3 falló: {str(e)[:100]}")

    if not info:
        logger.error(f"EXTRACT_INFO FAILED for {url}.")
        if is_instagram:
            cookie_file = get_robust_opts(url).get('cookiefile')
            files = await run_blocking(get_instagram_carousel_info, url, cookie_file)
            if files:
                first_file = files[0]
                metadata = first_file.get("metadata", {})
                title = metadata.get("description") or f"Instagram Post {metadata.get('post_shortcode', '')}"
                if len(title) > 100:
                    title = title[:100] + "..."
                uploader = metadata.get("username") or "Instagram User"
                
                thumbnail = first_file.get("url")
                if thumbnail:
                    from urllib.parse import quote
                    thumbnail = f"/api/proxy-thumbnail?url={quote(thumbnail, safe='')}"
                
                formats = [{
                    'format_id': 'carousel_images',
                    'ext': 'zip',
                    'resolution': 'Imágenes (ZIP)',
                    'filesize': None,
                    'label': f"Conjunto de {len(files)} imágenes (.zip)"
                }]
                
                return {
                    'title': title,
                    'thumbnail': thumbnail,
                    'max_res_thumbnail': thumbnail,
                    'duration': None,
                    'uploader': uploader,
                    'description': metadata.get("description") or "",
                    'formats': formats,
                    'has_ffmpeg': True,
                    'has_subtitles': False,
                    'can_transcribe': True,
                }

        if is_instagram and "No video formats found" in last_error:
            raise HTTPException(
                status_code=400,
                detail="Este post de Instagram no contiene video (es una publicación de fotos/imágenes). Clipadsk solo puede descargar o transcribir videos y audios."
            )
        raise HTTPException(
            status_code=400, 
            detail=f"No pudimos procesar este video. Puede ser privado o YouTube bloqueó la conexión. Errores: {last_error[:200]}"
        )

    # Procesar formatos
    formats = []
    seen_res = set()
    all_formats = info.get('formats', [])
    useful_formats = [f for f in all_formats if f.get('vcodec') != 'none']
    useful_formats.sort(key=lambda x: (x.get('height') or 0), reverse=True)

    for f in useful_formats:
        height = f.get('height')
        # Si no tiene height pero tiene resolution con formato WxH, extraer height
        resolution_str = f.get('resolution')
        if not height and resolution_str and 'x' in resolution_str:
            try:
                parts = resolution_str.split('x')
                if len(parts) == 2:
                    height = int(parts[1])
            except ValueError:
                pass

        if height:
            if height >= 2160:
                res = "2160p (4K UHD)"
            elif height >= 1440:
                res = "1440p (2K QHD)"
            elif height >= 1080:
                res = "1080p (Full HD)"
            elif height >= 720:
                res = "720p (HD)"
            elif height >= 480:
                res = "480p (SD)"
            elif height >= 360:
                res = "360p (SD)"
            else:
                res = f"{height}p"
        else:
            note = f.get('format_note')
            if note and not re.search(r'\d+x\d+', note) and len(note) < 15:
                res = note
            else:
                res = "Calidad estándar"

        ext = f.get('ext', 'mp4')
        res_key = f"{res}_{ext}"
        if res_key not in seen_res:
            formats.append({
                'format_id': f.get('format_id'),
                'ext': ext,
                'resolution': res,
                'filesize': f.get('filesize') or f.get('filesize_approx'),
                'label': f"{res} (.{ext})"
            })
            seen_res.add(res_key)

    # Si no hay formatos (Shorts, videos con DRM, etc.), agregar opción genérica
    if not formats:
        formats.append({
            'format_id': 'best',
            'ext': 'mp4',
            'resolution': 'Mejor calidad',
            'filesize': None,
            'label': 'Mejor calidad (.mp4)'
        })

    # Agregar la opción de descarga como MP3 para YouTube e Instagram (cualquier plataforma con audio)
    if is_instagram or is_youtube:
        formats.append({
            'format_id': 'mp3',
            'ext': 'mp3',
            'resolution': 'Solo audio',
            'filesize': None,
            'label': 'Solo audio (.mp3)'
        })

    # Proxy para miniaturas de Instagram
    # Se añade encoding y el prefijo /api/ para resolver problemas de carga en el frontend
    thumbnail = info.get('thumbnail')
    if 'instagram.com' in url and thumbnail:
        from urllib.parse import quote
        thumbnail = f"/api/proxy-thumbnail?url={quote(thumbnail, safe='')}"
        logger.debug(f"Instagram Thumbnail proxied (with encoding): {thumbnail}")

    return {
        'title': info.get('title'),
        'thumbnail': thumbnail,
        'max_res_thumbnail': thumbnail,
        'duration': info.get('duration'),
        'uploader': info.get('uploader') or "Desconocido",
        'description': (info.get('description') or 'Sin descripción')[:200] + '...',
        'formats': formats,
        'has_ffmpeg': True, # En Docker siempre tenemos FFmpeg
        'has_subtitles': bool(info.get('subtitles') or info.get('automatic_captions'))
    }

@app.get("/api/result/{uid}")
async def get_transcript_result(uid: str):
    """
    Recupera el resultado de una transcripción previamente completada por su UID.
    Útil cuando la conexión HTTP se cortó durante un video largo pero el servidor
    terminó el proceso correctamente.
    """
    result = get_stored_result(uid)
    if result is None:
        raise HTTPException(status_code=404, detail="Resultado no disponible. La transcripción puede no haber terminado o el UID es incorrecto.")
    return result


@app.post("/api/transcript")
async def get_transcript(req: VideoRequest):
    url = sanitize_url(req.url)
    uid = req.uid
    lang = req.target_lang or "es"
    
    add_log(uid, f"Iniciando transcripcion para: {url} | Idioma: {lang}")
    
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    
    # Cache por URL e Idioma
    cache_key = f"{url}_{lang}"
    cache = load_cache()
    if cache_key in cache:
        add_log(uid, "Resultado recuperado de cache local.")
        cached_val = cache[cache_key]
        try:
            parsed = json.loads(cached_val)
            if isinstance(parsed, dict) and "transcript" in parsed:
                return {
                    "transcript": parsed.get("transcript", ""),
                    "srt": parsed.get("srt", ""),
                    "segments": parsed.get("segments", []),
                    "method": "cache"
                }
        except Exception:
            pass
        return {"transcript": cached_val, "method": "cache"}

    # --- INSTAGRAM CAROUSEL OCR FALLBACK ---
    is_instagram = 'instagram.com' in url
    local_groq = get_local_groq(req.groq_api_key)
    if is_instagram:
        cookie_file = get_robust_opts(url).get('cookiefile')
        files = await run_blocking(get_instagram_carousel_info, url, cookie_file)
        if files:
            only_images = True
            for f in files:
                meta = f.get("metadata", {})
                ext = meta.get("extension") or ""
                video_url = meta.get("video_url")
                if video_url or ext.lower() in ('mp4', 'mov', 'avi', 'mkv', 'webm'):
                    only_images = False
                    break
            
            if only_images:
                if not local_groq:
                    raise HTTPException(
                        status_code=400, 
                        detail="Para extraer texto de imágenes (OCR), necesitás configurar la API Key de Groq en Configuración."
                    )
                add_log(uid, f"Detectado carrusel de imágenes ({len(files)} diapositivas). Iniciando OCR con Groq Vision...")
                ocr_text = ""
                total_files = len(files)
                for idx, file_item in enumerate(files):
                    img_url = file_item["url"]
                    update_progress(req.uid, int((idx / total_files) * 90) + 5, f"Analizando diapositiva {idx+1}/{total_files}...")
                    
                    try:
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        img_res = requests.get(img_url, headers=headers, timeout=20)
                        if img_res.status_code == 200:
                            b64_img = base64.b64encode(img_res.content).decode('utf-8')
                            
                            chat_completion = local_groq.chat.completions.create(
                                messages=[
                                    {
                                        "role": "user",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "Extract all readable text from this image. Return only the extracted text, keeping logical line breaks. Do not add any introductory or extra conversational text."
                                            },
                                            {
                                                "type": "image_url",
                                                "image_url": {
                                                    "url": f"data:image/jpeg;base64,{b64_img}"
                                                }
                                            }
                                        ]
                                    }
                                ],
                                model="meta-llama/llama-4-scout-17b-16e-instruct",
                                temperature=0.1,
                                max_tokens=1024
                            )
                            extracted = chat_completion.choices[0].message.content.strip()
                            ocr_text += f"--- DIAPOSITIVA {idx+1} ---\n{extracted}\n\n"
                            add_log(uid, f"Diapositiva {idx+1}/{total_files} procesada exitosamente.")
                        else:
                            ocr_text += f"--- DIAPOSITIVA {idx+1} ---\n[Error al descargar la imagen: Código {img_res.status_code}]\n\n"
                            add_log(uid, f"Error al descargar diapositiva {idx+1}: código {img_res.status_code}")
                    except Exception as ocr_err:
                        logger.warning(f"Error en OCR diapositiva {idx+1}: {ocr_err}")
                        ocr_text += f"--- DIAPOSITIVA {idx+1} ---\n[Error de extracción: {str(ocr_err)}]\n\n"
                        add_log(uid, f"Error al procesar OCR de diapositiva {idx+1}: {str(ocr_err)}")
                
                update_progress(req.uid, 95, "Guardando resultado...")
                ocr_text = ocr_text.strip()
                
                cache_data = {
                    "transcript": ocr_text,
                    "srt": "",
                    "segments": []
                }
                save_cache_entry(cache_key, json.dumps(cache_data))
                update_progress(req.uid, 100, "¡Extracción de texto completa!")
                
                result_payload = {
                    "transcript": ocr_text,
                    "srt": "",
                    "segments": [],
                    "method": "groq_vision_ocr"
                }
                if uid:
                    store_result(uid, result_payload)
                return result_payload

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            local_groq = get_local_groq(req.groq_api_key)
            if is_youtube:
                add_log(uid, "Intentando extraer subtitulos de YouTube...")
                # --- INTENTO DE SUBS CON 3 ESTRATEGIAS ---
                sub_extracted = False

                # 1. Celular sin cookies
                try:
                    update_progress(req.uid, 10, "Buscando subtítulos (1/2)...")
                    opts = get_robust_opts(url, {'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 'subtitleslangs': ['es.*', 'en.*'], 'outtmpl': os.path.join(tmpdir, 'sub.%(ext)s'), 'ignoreerrors': True})
                    opts.pop('cookiefile', None)
                    opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios']}}
                    await run_blocking(ydl_download_sync, opts, url)
                    sub_extracted = True
                except: pass

                # 2. Con cookies
                if not sub_extracted:
                    try:
                        update_progress(req.uid, 20, "Buscando subtítulos (2/2)...")
                        opts = get_robust_opts(url, {'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 'subtitleslangs': ['es.*', 'en.*'], 'outtmpl': os.path.join(tmpdir, 'sub.%(ext)s'), 'ignoreerrors': True})
                        await run_blocking(ydl_download_sync, opts, url)
                        sub_extracted = True
                    except: pass

                sub_file = None
                is_english = False
                for f in os.listdir(tmpdir):
                    if f.startswith('sub.') and ('.es' in f or '.es-419' in f):
                        sub_file = os.path.join(tmpdir, f)
                        break
                if not sub_file:
                    for f in os.listdir(tmpdir):
                        if f.startswith('sub.') and ('.en' in f or '.en-US' in f):
                            sub_file = os.path.join(tmpdir, f)
                            is_english = True
                            break
                
                if sub_file:
                    with open(sub_file, 'r', encoding='utf-8') as f:
                        raw_content = f.read()
                    
                    segments = parse_subtitles_to_segments(raw_content)
                    
                    # Traducir y limpiar cada segmento
                    for seg in segments:
                        if is_english and lang == "es":
                            seg["text"] = translate_to_spanish(seg["text"])
                        seg["text"] = remove_repetitions(seg["text"])
                    
                    # Generar texto plano completo y SRT
                    raw_full_text = ' '.join([seg["text"] for seg in segments])
                    srt_content = generate_srt_from_segments(segments)
                    
                    # Paso 2: Limpieza con IA para puntuación y párrafos
                    update_progress(req.uid, 80, f"Aplicando limpieza con IA ({lang})...")
                    final_text = cleanup_transcript_with_ai(raw_full_text, local_groq, lang)
                    
                    cache_data = {
                        "transcript": final_text,
                        "srt": srt_content,
                        "segments": segments
                    }
                    save_cache_entry(cache_key, json.dumps(cache_data))
                    add_log(uid, "Transcripcion via subtitulos completada.")
                    update_progress(req.uid, 100, "¡Transcripción lista!")
                    result_payload = {
                        "transcript": final_text,
                        "srt": srt_content,
                        "segments": segments,
                        "method": "subtitles"
                    }
                    if uid:
                        store_result(uid, result_payload)
                    return result_payload

            raise Exception("No direct subtitles")

        except Exception as e:
            add_log(uid, f"Fallo extraccion de subtitulos: {str(e)}")
            # 2. Descargar audio y usar Whisper con 3 estrategias
            audio_downloaded = False
            audio_file = None
            
            add_log(uid, "Iniciando descarga de audio para Whisper...")

            # Estrategia 1: Móvil sin cookies
            try:
                audio_opts = get_robust_opts(url, {'format': 'bestaudio/best', 'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'), 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '64'}]})
                audio_opts.pop('cookiefile', None)
                audio_opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios']}}
                await run_blocking(ydl_download_sync, audio_opts, url)
                for f in os.listdir(tmpdir):
                    if f.startswith('audio.'):
                        audio_file = os.path.join(tmpdir, f)
                        audio_downloaded = True
                        break
            except: pass

            # Estrategia 2: Con cookies
            if not audio_downloaded:
                try:
                    audio_opts = get_robust_opts(url, {'format': 'bestaudio/best', 'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'), 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '64'}]})
                    await run_blocking(ydl_download_sync, audio_opts, url)
                    for f in os.listdir(tmpdir):
                        if f.startswith('audio.'):
                            audio_file = os.path.join(tmpdir, f)
                            audio_downloaded = True
                            break
                except: pass

            if audio_downloaded and audio_file:
                # 2.1 Intentar con Groq API (Más rápido y ligero)
                transcription = ""
                srt_content = ""
                all_segments = []
                method = "groq_whisper_v3_file"

                if local_groq:
                    try:
                        file_size_mb = os.path.getsize(audio_file) / (1024 * 1024)
                        if AudioSegment:
                            # Lógica de troceado si es necesario
                            if file_size_mb >= 20:
                                 add_log(uid, f"Audio grande ({file_size_mb:.1f}MB). Dividiendo en trozos de 20 min...")
                                 audio = AudioSegment.from_file(audio_file)
                                 chunk_length_ms = 20 * 60 * 1000 # 20 minutos por trozo
                                 chunks = []
                                 for i in range(0, len(audio), chunk_length_ms):
                                     chunks.append(audio[i:i + chunk_length_ms])
                                 
                                 for idx, chunk in enumerate(chunks):
                                     with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as c_file:
                                         chunk.export(c_file.name, format="mp3", bitrate="64k")
                                         add_log(uid, f"Transcribiendo parte {idx+1}/{len(chunks)}...")
                                         with open(c_file.name, "rb") as f:
                                             part_res = local_groq.audio.transcriptions.create(
                                                 file=(c_file.name, f.read(), "audio/mpeg"),
                                                 model="whisper-large-v3",
                                                 response_format="verbose_json",
                                                 language=lang if lang in ["es", "en"] else None
                                             )
                                             transcription += getattr(part_res, "text", "") + " "
                                             
                                             # Adjust segments timestamps for chunk index
                                             offset = idx * 20 * 60
                                             part_segments = getattr(part_res, "segments", []) or []
                                             for segment in part_segments:
                                                 if isinstance(segment, dict):
                                                     s_start = segment.get("start", 0) + offset
                                                     s_end = segment.get("end", 0) + offset
                                                     s_text = segment.get("text", "").strip()
                                                 else:
                                                     s_start = getattr(segment, "start", 0) + offset
                                                     s_end = getattr(segment, "end", 0) + offset
                                                     s_text = getattr(segment, "text", "").strip()
                                                 all_segments.append({"start": s_start, "end": s_end, "text": s_text})
                                         os.remove(c_file.name)
                                 srt_content = generate_srt_from_segments(all_segments)

                            else:
                                update_progress(req.uid, 40, "Enviando a Whisper (IA)...")
                                with open(audio_file, "rb") as f:
                                    trans_res = local_groq.audio.transcriptions.create(
                                        file=(audio_file, f.read(), "audio/mpeg"),
                                        model="whisper-large-v3",
                                        response_format="verbose_json",
                                        language=lang if lang in ["es", "en"] else None
                                    )
                                transcription = getattr(trans_res, "text", "")
                                part_segments = getattr(trans_res, "segments", []) or []
                                for segment in part_segments:
                                    if isinstance(segment, dict):
                                         s_start = segment.get("start", 0)
                                         s_end = segment.get("end", 0)
                                         s_text = segment.get("text", "").strip()
                                    else:
                                         s_start = getattr(segment, "start", 0)
                                         s_end = getattr(segment, "end", 0)
                                         s_text = getattr(segment, "text", "").strip()
                                    all_segments.append({"start": s_start, "end": s_end, "text": s_text})
                                srt_content = generate_srt_from_segments(all_segments)
                        else:
                            add_log(uid, "Enviando audio completo a Whisper (IA)...")
                            with open(audio_file, "rb") as f:
                                trans_res = local_groq.audio.transcriptions.create(
                                    file=(audio_file, f.read(), "audio/mpeg"),
                                    model="whisper-large-v3",
                                    response_format="verbose_json",
                                    language=lang if lang in ["es", "en"] else None
                                )
                            transcription = getattr(trans_res, "text", "")
                            part_segments = getattr(trans_res, "segments", []) or []
                            for segment in part_segments:
                                if isinstance(segment, dict):
                                     s_start = segment.get("start", 0)
                                     s_end = segment.get("end", 0)
                                     s_text = segment.get("text", "").strip()
                                else:
                                     s_start = getattr(segment, "start", 0)
                                     s_end = getattr(segment, "end", 0)
                                     s_text = getattr(segment, "text", "").strip()
                                all_segments.append({"start": s_start, "end": s_end, "text": s_text})
                            srt_content = generate_srt_from_segments(all_segments)
                        
                        add_log(uid, "Procesando texto crudo de Whisper...")
                        transcription = remove_repetitions(str(transcription).strip())
                        
                        # Paso 2: Limpieza con IA para puntuación y párrafos
                        add_log(uid, f"Aplicando limpieza y formato IA ({lang})...")
                        transcription = cleanup_transcript_with_ai(transcription, local_groq, lang)
                        
                        cache_data = {
                            "transcript": transcription,
                            "srt": srt_content,
                            "segments": all_segments
                        }
                        save_cache_entry(cache_key, json.dumps(cache_data))
                        add_log(uid, "Transcripcion de archivo completada.")
                        update_progress(req.uid, 100, "¡Transcripción lista!")
                        result_payload = {
                            "transcript": transcription,
                            "srt": srt_content,
                            "segments": all_segments,
                            "method": "groq_whisper_v3_file"
                        }
                        if uid:
                            store_result(uid, result_payload)
                        return result_payload
                    except Exception as ge:
                        add_log(uid, f"Error en Groq Whisper, intentando local: {str(ge)}")
                        if not WHISPER_MODEL_AVAILABLE:
                            raise Exception(f"Error en Groq API: {str(ge)}")
                
                # 2.2 Intentar con local whisper (Fallback o si no hay Groq)
                if WHISPER_MODEL_AVAILABLE:
                    try:
                        add_log(uid, "Iniciando transcripcion local con faster-whisper...")
                        update_progress(req.uid, 40, "Transcribiendo en local (Whisper)...")
                        transcription, srt_content = transcribe_with_local_whisper(audio_file, lang)
                        all_segments = parse_subtitles_to_segments(srt_content)
                        method = "local_whisper"
                        
                        add_log(uid, "Procesando texto crudo...")
                        transcription = remove_repetitions(transcription.strip())
                        
                        # Limpieza IA si está configurada
                        if local_groq:
                            add_log(uid, f"Aplicando limpieza IA...")
                            transcription = cleanup_transcript_with_ai(transcription, local_groq, lang)
                        
                        cache_data = {
                            "transcript": transcription,
                            "srt": srt_content,
                            "segments": all_segments
                        }
                        save_cache_entry(cache_key, json.dumps(cache_data))
                        add_log(uid, "Transcripcion local completada.")
                        update_progress(req.uid, 100, "¡Transcripción lista!")
                        result_payload = {
                            "transcript": transcription,
                            "srt": srt_content,
                            "segments": all_segments,
                            "method": "local_whisper"
                        }
                        if uid:
                            store_result(uid, result_payload)
                        return result_payload
                    except Exception as le:
                        add_log(uid, f"Error en transcripcion local: {str(le)}")
                        raise le
                else:
                    raise Exception("Groq API no configurada o falló, y no hay modelo Whisper local disponible.")

            raise Exception("No se pudo descargar el audio para la transcripción por ningún medio.")
        except Exception as final_e:
            return JSONResponse(status_code=500, content={"error": str(final_e)})

class ChatRequest(BaseModel):
    url: str
    question: str
    transcript: str
    groq_api_key: Optional[str] = None

@app.post("/api/chat")
async def chat_with_transcript(req: ChatRequest):
    local_groq = get_local_groq(req.groq_api_key)
    if not local_groq:
        raise HTTPException(status_code=500, detail="Groq API no configurada")
    
    # --- RECORTE DE SEGURIDAD PARA RATE LIMITS (6000 TPM) ---
    # Si la transcripcion es muy larga, la recortamos para que quepa en el limite gratuito de Groq.
    # 20,000 caracteres son aprox 5,000 tokens, lo que deja margen para la respuesta.
    transcript_safe = req.transcript
    if len(transcript_safe) > 12000:
        logger.warning(f"Transcripcion muy larga ({len(transcript_safe)} chars). Recortando para evitar error 413.")
        transcript_safe = transcript_safe[:6000] + "\n\n[...] [Parte omitida por longitud] [...] \n\n" + transcript_safe[-6000:]

    try:
        system_prompt = f"""
        Eres un asistente experto que analiza transcripciones de videos. 
        Tu objetivo es responder preguntas del usuario basándote únicamente en la siguiente transcripción (puede estar recortada por longitud):
        
        --- TRANSCRIPCIÓN ---
        {transcript_safe}
        --- FIN ---
        
        Responde de forma concisa, útil y en español. 
        
        REGLAS DE FORMATO:
        1. Usá **negritas** para nombres de productos, marcas o conceptos clave.
        2. Usá "punto y aparte" (doble salto de línea) entre párrafos o puntos de una lista para que el texto "respire" y sea fácil de leer.
        3. Si hacés una lista, que cada ítem esté separado por una línea en blanco.
        
        Si la respuesta no está en la transcripción, dilo amablemente.
        """
        
        completion = local_groq.chat.completions.create(
            model=GROQ_CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.question}
            ],
            temperature=0.7,
            max_tokens=1024,
        )
        
        return {"answer": completion.choices[0].message.content}
    except Exception as e:
        logger.exception("Error en Chat")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/download")
async def download_video(req: VideoRequest, background_tasks: BackgroundTasks):
    url = sanitize_url(req.url)
    format_id = req.format_id
    uid = str(uuid.uuid4())

    # --- CARRUSEL DE IMÁGENES (gallery-dl) ---
    if format_id == 'carousel_images':
        cookie_file = get_robust_opts(url).get('cookiefile')
        files = await run_blocking(get_instagram_carousel_info, url, cookie_file)
        if not files:
            raise HTTPException(status_code=400, detail="No se pudieron extraer las imágenes del carrusel.")
            
        import zipfile
        zip_filename = f"instagram_carousel_{uid}.zip"
        zip_path = os.path.join(DOWNLOAD_FOLDER, zip_filename)
        
        def create_zip():
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for idx, file_item in enumerate(files):
                    file_url = file_item["url"]
                    meta = file_item.get("metadata", {})
                    ext = meta.get("extension") or "jpg"
                    try:
                        r = requests.get(file_url, headers=headers, timeout=30)
                        if r.status_code == 200:
                            zipf.writestr(f"imagen_{idx+1}.{ext}", r.content)
                    except Exception as download_err:
                        logger.warning(f"Error descargando imagen {idx+1} para zip: {download_err}")
                        
        await run_blocking(create_zip)
        
        def remove_file(path):
            try:
                if os.path.exists(path): os.remove(path)
            except: pass
            
        background_tasks.add_task(remove_file, zip_path)
        
        username_safe = "".join([c for c in files[0]["metadata"].get("username", "instagram") if c.isalnum() or c==' ']).strip() or "carrusel"
        filename = f"carrusel_{username_safe}_{uid[:6]}.zip"
        return FileResponse(zip_path, filename=filename, media_type='application/zip')

    # --- INSTAGRAM: usar instaloader para descarga ---
    if 'instagram.com' in url and instaloader:
        try:
            ig_info = await asyncio.to_thread(get_instagram_info, url)
            if not ig_info['is_video']:
                raise HTTPException(status_code=400, detail="Este post de Instagram no tiene video.")

            # --- Descarga como MP3 (extracción de audio) ---
            if format_id == 'mp3':
                video_url = ig_info['video_url']
                headers_dl = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15'}
                r = await run_blocking(requests_get_sync, video_url, headers=headers_dl, stream=True, timeout=60)
                r.raise_for_status()

                tmp_mp4 = os.path.join(DOWNLOAD_FOLDER, f'instagram_{uid}_tmp.mp4')
                with open(tmp_mp4, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

                mp3_path = os.path.join(DOWNLOAD_FOLDER, f'instagram_{uid}.mp3')
                ffmpeg_exe = os.path.join(BASE_DIR, '..', 'ffmpeg.exe')
                if not os.path.exists(ffmpeg_exe):
                    ffmpeg_exe = 'ffmpeg'
                import subprocess
                subprocess.run(
                    [ffmpeg_exe, '-y', '-i', tmp_mp4, '-vn', '-acodec', 'libmp3lame', '-q:a', '2', mp3_path],
                    check=True, capture_output=True
                )
                os.remove(tmp_mp4)

                def remove_file_mp3(path):
                    try:
                        if os.path.exists(path): os.remove(path)
                    except: pass

                background_tasks.add_task(remove_file_mp3, mp3_path)
                filename = f"{ig_info['title'][:30].strip()}_{uid}.mp3"
                return FileResponse(mp3_path, filename=filename, media_type='audio/mpeg')

            # --- Descarga normal como MP4 ---
            video_url = ig_info['video_url']
            headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15'}
            r = await run_blocking(requests_get_sync, video_url, headers=headers, stream=True, timeout=60)
            r.raise_for_status()

            file_path = os.path.join(DOWNLOAD_FOLDER, f'instagram_{uid}.mp4')
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            def remove_file(path):
                try:
                    if os.path.exists(path): os.remove(path)
                except: pass

            background_tasks.add_task(remove_file, file_path)
            filename = f"{ig_info['title'][:30].strip()}_{uid}.mp4"
            return FileResponse(file_path, filename=filename, media_type='video/mp4')

        except HTTPException:
            raise
        except Exception as e:
            logger.debug(f"Instaloader download falló, intentando con yt-dlp: {e}")

    output_template = os.path.join(DOWNLOAD_FOLDER, f'%(title)s_{uid}.%(ext)s')

    # --- Formato MP3: extraer solo audio ---
    if format_id == 'mp3':
        extra_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
    else:
        if format_id and format_id not in ('best', 'bestvideo+bestaudio', None):
            fmt = f"{format_id}/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
        else:
            fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'

        extra_opts = {
            'format': fmt,
            'outtmpl': output_template,
            'merge_output_format': 'mp4',
        }
    
    def my_hook(d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('\x1b[0;94m','').replace('\x1b[0m','').strip()
            # extract number
            try:
                p_val = float(p.replace('%',''))
                update_progress(req.uid, int(p_val * 0.9), f"Descargando video: {p}")
            except: pass
        elif d['status'] == 'finished':
            update_progress(req.uid, 90, "Descarga completada, procesando con FFmpeg...")

    extra_opts['progress_hooks'] = [my_hook]

    if req.start_time or req.end_time:
        from yt_dlp.utils import parse_duration, download_range_func
        start_sec = parse_duration(req.start_time) if req.start_time else 0
        end_sec = parse_duration(req.end_time) if req.end_time else float('inf')
        extra_opts['download_ranges'] = download_range_func(None, [(start_sec, end_sec)])
        extra_opts['force_keyframes_at_cuts'] = True

    # Intentar descarga con 3 estrategias
    downloaded = False
    last_err = ""
    update_progress(req.uid, 5, "Iniciando proceso...")

    # --- ESTRATEGIA 1: Celular sin cookies (La que funcionó para info) ---
    try:
        logger.debug("Descarga Intento 1 - Celular sin cookies...")
        update_progress(req.uid, 10, "Conectando al servidor (1/3)...")
        opts = get_robust_opts(url, extra_opts)
        opts.pop('cookiefile', None)
        opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios']}}
        await run_blocking(ydl_download_sync, opts, url)
        downloaded = True
    except Exception as e:
        last_err = str(e)
        logger.debug(f"Descarga Intento 1 falló: {last_err[:100]}")

    # --- ESTRATEGIA 2: Navegador con Cookies ---
    if not downloaded:
        try:
            logger.debug("Descarga Intento 2 - Con cookies...")
            update_progress(req.uid, 15, "Reintentando con cookies (2/3)...")
            opts = get_robust_opts(url, extra_opts)
            await run_blocking(ydl_download_sync, opts, url)
            downloaded = True
        except Exception as e:
            last_err += f" | Intento 2: {str(e)[:100]}"
            logger.debug(f"Descarga Intento 2 falló: {str(e)[:100]}")

    # --- ESTRATEGIA 3: Forzar iOS ---
    if not downloaded:
        try:
            logger.debug("Descarga Intento 3 - Forzando iOS...")
            update_progress(req.uid, 20, "Forzando modo iOS (3/3)...")
            opts = get_robust_opts(url, extra_opts)
            opts.pop('cookiefile', None)
            opts['extractor_args'] = {'youtube': {'player_client': ['ios']}}
            await run_blocking(ydl_download_sync, opts, url)
            downloaded = True
        except Exception as e:
            last_err += f" | Intento 3: {str(e)[:100]}"
            logger.debug(f"Descarga Intento 3 falló: {str(e)[:100]}")

    if downloaded:
        update_progress(req.uid, 100, "¡Archivo listo!")
        # Encontrar archivo
        for f in os.listdir(DOWNLOAD_FOLDER):
            if uid in f:
                file_path = os.path.join(DOWNLOAD_FOLDER, f)
                def remove_file(path: str):
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                            logger.debug(f"Archivo borrado: {file_path}")
                    except Exception as e:
                        logger.exception("Error borrando archivo")
                
                background_tasks.add_task(remove_file, file_path)
                return FileResponse(file_path, filename=f)
        raise Exception("Archivo no encontrado tras descarga exitosa")
    else:
        raise HTTPException(status_code=500, detail=f"No se pudo descargar: {last_err[:200]}")

@app.get("/api/proxy-thumbnail")
async def proxy_thumbnail(url: str):
    logger.debug(f"Proxy request for: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Referer': 'https://www.instagram.com/'
    }
    try:
        resp = await run_blocking(requests_get_sync, url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        logger.debug(f"Proxy success, Content-Type: {resp.headers.get('Content-Type')}")
        return Response(content=resp.content, media_type=resp.headers.get('Content-Type', 'image/jpeg'))
    except Exception as e:
        logger.exception("Proxy FAILED")
        return Response(status_code=500)

# --- HEALTHCHECKS ---
@app.get("/api/health/cookies")
async def check_cookies():
    """Verifica si las cookies actuales siguen siendo válidas con un video de prueba."""
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    try:
        opts = get_robust_opts(test_url)
        info = await run_blocking(extract_info_sync, opts, test_url)
        return {
            "status": "ok", 
            "cookie_valid": True, 
            "video_title": info.get('title'),
            "server_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return {
            "status": "error", 
            "cookie_valid": False, 
            "error": str(e),
            "server_time": time.strftime("%Y-%m-%d %H:%M:%S")
        }

# --- TRANSCRIPCIÓN DE ARCHIVO DE AUDIO (WhatsApp, grabaciones, etc.) ---

ALLOWED_AUDIO_EXTENSIONS = {'.ogg', '.opus', '.mp3', '.m4a', '.wav', '.mp4', '.aac', '.weba', '.webm', '.mov', '.avi', '.mkv'}
MAX_AUDIO_SIZE_MB = 200

@app.post("/api/transcript-file")
async def transcript_audio_file(
    file: UploadFile = File(...),
    target_lang: str = Form(default="es"),
    uid: str = Form(default=None),
    groq_api_key: str = Form(default=None),
    is_local_video: Optional[str] = Form(default=None)
):

    """
    Transcribe un archivo de audio subido directamente.
    Soporta WhatsApp (.ogg/.opus), grabaciones de voz (.m4a/.mp3), y más.
    """
    local_groq = get_local_groq(groq_api_key)
    if not local_groq and not WHISPER_MODEL_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Groq API no configurada. Configura tu API Key en la interfaz o instala faster-whisper para transcribir localmente."
        )
    if not local_groq:
        add_log(uid, "Groq API no configurada. Usando transcripción local si está disponible.")

    # Validar extensión
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado: '{ext}'. Formatos válidos: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}"
        )

    is_video = False
    if is_local_video == "true":
        is_video = True
    else:
        VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.weba'}
        if ext in VIDEO_EXTS:
            is_video = True

    with tempfile.TemporaryDirectory() as tmpdir:
        # Guardar archivo subido
        input_path = os.path.join(tmpdir, f"input{ext}")
        content = await file.read()

        # Validar tamaño
        size_mb = len(content) / (1024 * 1024)
        if size_mb > MAX_AUDIO_SIZE_MB:
            raise HTTPException(status_code=413, detail=f"El archivo es demasiado grande ({size_mb:.1f} MB). Máximo: {MAX_AUDIO_SIZE_MB} MB.")

        with open(input_path, 'wb') as f:
            f.write(content)
        
        update_progress(uid, 5, "Archivo recibido en el servidor...")
        add_log(uid, f"Archivo recibido para transcribir: {file.filename} ({size_mb:.2f} MB)")


        # Convertir a MP3 si es necesario usando pydub (audio y video)
        audio_path = input_path
        conversion_done = False
        VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.weba'}
        AUDIO_EXTS = {'.ogg', '.opus', '.m4a', '.wav', '.aac'}
        
        if ext in AUDIO_EXTS | VIDEO_EXTS:
            converted_path = os.path.join(tmpdir, "converted.mp3")
            try:
                update_progress(uid, 10, "Convirtiendo formato de audio/video...")
                if AudioSegment:
                    logger.debug("Intentando conversion con pydub...")
                    audio = AudioSegment.from_file(input_path)
                    audio = audio.set_frame_rate(16000).set_channels(1)
                    audio.export(converted_path, format="mp3", bitrate="32k")
                    if os.path.exists(converted_path) and os.path.getsize(converted_path) > 0:
                        audio_path = converted_path
                        conversion_done = True
                        logger.debug(f"Pydub exitoso. Tamaño: {os.path.getsize(audio_path)/1024/1024:.2f} MB")
                
                if not conversion_done:
                    logger.debug("Pydub no disponible o fallo, intentando ffmpeg directo...")
                    import subprocess
                    # Usar el binario encontrado o solo 'ffmpeg' si no hay binario local
                    exe = FFMPEG_BIN if FFMPEG_BIN else 'ffmpeg'
                    subprocess.run(
                        [exe, '-y', '-i', input_path, '-vn', '-ar', '16000', '-ac', '1', '-ab', '32k', '-f', 'mp3', converted_path],
                        capture_output=True, check=True
                    )
                    if os.path.exists(converted_path) and os.path.getsize(converted_path) > 0:
                        audio_path = converted_path
                        conversion_done = True
                        logger.debug(f"FFmpeg directo exitoso. Tamaño: {os.path.getsize(audio_path)/1024/1024:.2f} MB")
            except Exception as e:
                logger.exception(f"Error en conversion: {e}")

        try:
            file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            
            # VALIDACION CRITICA: Límite de Groq (25MB)
            if file_size_mb > 25 and not WHISPER_MODEL_AVAILABLE:
                if not conversion_done:
                    raise HTTPException(status_code=400, detail="El archivo es demasiado grande (o es un video) y no se pudo convertir porque FFmpeg no está instalado en el sistema. Por favor, instala FFmpeg o sube un archivo de audio comprimido.")
                else:
                    raise HTTPException(status_code=400, detail=f"El archivo es demasiado largo ({file_size_mb:.1f}MB) incluso tras comprimirlo. El limite de Groq es 25MB, pero puedes instalar faster-whisper para transcribir localmente.")

            transcription = ""
            srt_content = ""
            method = "groq_whisper_v3_file" if local_groq else "local_whisper"

            update_progress(uid, 20, "Iniciando transcripción del audio...")

            if local_groq:
                try:
                    all_segments = []
                    if AudioSegment and file_size_mb >= 20:
                        # Archivos grandes: trocear en partes de 20 minutos
                        update_progress(uid, 22, "Dividiendo audio grande en partes...")
                        add_log(uid, f"Dividiendo audio de {file_size_mb:.1f}MB en partes...")
                        audio = AudioSegment.from_file(audio_path)
                        chunk_length_ms = 20 * 60 * 1000
                        chunks = [audio[i:i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

                        for idx, chunk in enumerate(chunks):
                            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as c_file:
                                chunk.export(c_file.name, format="mp3", bitrate="64k")
                                progress_pct = 25 + int((idx / len(chunks)) * 55)
                                update_progress(uid, progress_pct, f"Transcribiendo parte {idx+1}/{len(chunks)} con Groq Whisper...")
                                add_log(uid, f"Transcribiendo parte {idx+1}/{len(chunks)}...")
                                with open(c_file.name, "rb") as cf:
                                    part_res = local_groq.audio.transcriptions.create(
                                        file=(c_file.name, cf.read(), "audio/mpeg"),
                                        model="whisper-large-v3",
                                        response_format="verbose_json",
                                        language=target_lang if target_lang in ["es", "en"] else None
                                    )
                                    transcription += getattr(part_res, "text", "") + " "
                                    
                                    # Adjust segments timestamps for chunk index
                                    offset = idx * 20 * 60
                                    part_segments = getattr(part_res, "segments", []) or []
                                    for segment in part_segments:
                                        if isinstance(segment, dict):
                                            s_start = segment.get("start", 0) + offset
                                            s_end = segment.get("end", 0) + offset
                                            s_text = segment.get("text", "").strip()
                                        else:
                                            s_start = getattr(segment, "start", 0) + offset
                                            s_end = getattr(segment, "end", 0) + offset
                                            s_text = getattr(segment, "text", "").strip()
                                        all_segments.append({"start": s_start, "end": s_end, "text": s_text})

                                os.remove(c_file.name)
                        srt_content = generate_srt_from_segments(all_segments)
                    else:
                        if audio_path.endswith('.mp3'):
                            mime_type = "audio/mpeg"
                        elif audio_path.endswith('.wav'):
                            mime_type = "audio/wav"
                        elif audio_path.endswith('.mp4'):
                            mime_type = "video/mp4"
                        elif audio_path.endswith('.m4a'):
                            mime_type = "audio/mp4"
                        elif audio_path.endswith('.webm'):
                            mime_type = "audio/webm"
                        else:
                            mime_type = "audio/ogg"

                        update_progress(uid, 35, "Transcribiendo con Groq Whisper...")
                        with open(audio_path, "rb") as f:
                            trans_res = local_groq.audio.transcriptions.create(
                                file=(os.path.basename(audio_path), f.read(), mime_type),
                                model="whisper-large-v3",
                                response_format="verbose_json",
                                language=target_lang if target_lang in ["es", "en"] else None
                            )
                        transcription = getattr(trans_res, "text", "")
                        segments = getattr(trans_res, "segments", []) or []
                        srt_content = generate_srt_from_segments(segments)
                    
                    transcription = str(transcription)
                except Exception as ge:
                    add_log(uid, f"Error critico en Groq Whisper: {str(ge)}")
                    if not WHISPER_MODEL_AVAILABLE:
                        raise Exception(f"Error en Groq API: {str(ge)}")
                    update_progress(uid, 40, "Groq falló. Usando transcripción local con Whisper...")
                    add_log(uid, "Groq falló o la API Key es inválida. Intentando transcripción local con Whisper...")
                    transcription, srt_content = transcribe_with_local_whisper(audio_path, target_lang)
                    method = "local_whisper"
            else:
                update_progress(uid, 30, "Transcribiendo localmente con Whisper...")
                transcription, srt_content = transcribe_with_local_whisper(audio_path, target_lang)

            # Unificar segmentos para retornar
            if method == "local_whisper":
                segments_to_return = parse_subtitles_to_segments(srt_content)
            else:
                # Groq
                if 'segments' in locals() and segments:
                    segments_to_return = []
                    for s in segments:
                        if isinstance(s, dict):
                            s_start = s.get("start", 0)
                            s_end = s.get("end", 0)
                            s_text = s.get("text", "").strip()
                        else:
                            s_start = getattr(s, "start", 0)
                            s_end = getattr(s, "end", 0)
                            s_text = getattr(s, "text", "").strip()
                        segments_to_return.append({"start": s_start, "end": s_end, "text": s_text})
                else:
                    segments_to_return = all_segments

            transcript_text = str(transcription).strip()
            # Limpieza con IA
            update_progress(uid, 80, "Aplicando limpieza y formato con IA...")
            add_log(uid, f"Aplicando limpieza y formato IA ({target_lang})...")
            transcript_text = cleanup_transcript_with_ai(transcript_text, local_groq, target_lang, is_local_video=is_video)
            
            update_progress(uid, 100, "Completado")
            add_log(uid, "Transcripcion de archivo completada con exito.")
            return {
                "transcript": transcript_text,
                "srt": srt_content,
                "segments": segments_to_return,
                "method": method,
                "filename": file.filename,
                "size_mb": round(size_mb, 2)
            }

        except Exception as e:
            add_log(uid, f"Error en transcripcion de archivo: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error al transcribir: {str(e)}")


# --- LIMPIEZA DE DESCARGAS ---
@app.delete("/api/clear-downloads")
async def clear_downloads():
    try:
        import shutil
        if os.path.exists(DOWNLOAD_FOLDER):
            shutil.rmtree(DOWNLOAD_FOLDER)
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
        return {"status": "success", "message": "Descargas locales eliminadas correctamente."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- HERRAMIENTAS PERIODÍSTICAS (IA) ---

class AnalyzeRequest(BaseModel):
    transcript: str
    mode: str  # "summary" | "quotes" | "data" | "angle" | "diarization"
    groq_api_key: Optional[str] = None

class QuotesRequest(BaseModel):
    transcript: str
    segments: list = []   # lista de {start, end, text} para ubicar tiempos
    groq_api_key: Optional[str] = None

def find_segment_times_for_quote(search_phrase: str, segments: list) -> dict:
    """Busca la frase en los segmentos y devuelve el start/end del segmento más cercano."""
    if not segments or not search_phrase:
        return {}
    
    search_lower = search_phrase.lower().strip()
    search_words = set(search_lower.split())
    
    best_score = 0
    best_seg = None
    best_idx = -1
    
    for i, seg in enumerate(segments):
        seg_text = seg.get('text', '').lower()
        # Exact substring match — perfect
        if search_lower in seg_text:
            return {"start": seg["start"], "end": seg["end"], "seg_idx": i}
        # Word overlap score
        seg_words = set(seg_text.split())
        overlap = len(search_words & seg_words)
        if overlap > best_score:
            best_score = overlap
            best_seg = seg
            best_idx = i
    
    if best_seg and best_score >= max(2, len(search_words) // 2):
        # Expand the window: take from this segment to 2 segments later for context
        end_idx = min(best_idx + 2, len(segments) - 1)
        return {"start": best_seg["start"], "end": segments[end_idx]["end"], "seg_idx": best_idx}
    
    return {}

JOURNALIST_PROMPTS = {
    "summary": """Sos un asistente para periodistas especializados en comunicación política e imagen pública.
Dado el siguiente texto transcripto, generá un RESUMEN EJECUTIVO periodístico de máximo 5 oraciones.
Incluí: tema central, postura del hablante, y punto más relevante para una nota periodística.
Respondé solo con el resumen, sin encabezados ni explicaciones.

TRANSCRIPCIÓN:
{transcript}""",

    "quotes": """¡IMPORTANTE! Respondé EXCLUSIVAMENTE con un objeto JSON válido que contenga un array bajo la clave "quotes", sin ningún texto antes ni después.

Sos un asistente para periodistas. Dado el siguiente texto transcripto, extraé las 5 CITAS TEXTUALES más noticiosas, llamativas o reveladoras.

Para cada cita devolvé un objeto JSON con estos campos exactos:
- "quote": la cita textual exacta del hablante (sin comillas dobles internas, usa simples si es necesario)
- "note": una o dos oraciones sobre por qué es relevante para una nota periodística
- "search": una frase corta única de 4-8 palabras que esté dentro de la cita, para poder ubicarla en el texto

Formato de respuesta (solo el JSON, nada más):
{
  "quotes": [
    {"quote": "...", "note": "...", "search": "..."}
  ]
}

TRANSCRIPCIÓN:
{transcript}""",

    "data": """Sos un asistente para periodistas especializados en comunicación política e imagen pública.
Dado el siguiente texto transcripto, extraé todos los DATOS DUROS mencionados:
- Fechas y plazos
- Cifras, porcentajes, montos
- Nombres de personas y sus cargos
- Instituciones y organizaciones
- Lugares geográficos relevantes

Organizalos en una lista clara. Si no hay datos duros, indicalo.
Respondé solo con los datos, sin introducción.

TRANSCRIPCIÓN:
{transcript}""",

    "angle": """Sos un editor de medios con experiencia en periodismo político y comunicación institucional.
Dado el siguiente texto transcripto, sugerí 3 ÁNGULOS PERIODÍSTICOS posibles para cubrir este contenido.

Para cada ángulo incluí:
• **Título sugerido**
• **Justificación**: Por qué es el ángulo más relevante.

Separá cada propuesta con un DOBLE SALTO DE LÍNEA.
Respondé directamente con los 3 ángulos, sin introducción.

TRANSCRIPCIÓN:
{transcript}""",

    "diarization": """Sos un asistente para periodistas experto en análisis de diálogos.
Dado el siguiente texto transcripto, tu tarea es analizar la conversación y dividirla en un diálogo estructurado, identificando a los diferentes hablantes.

Instrucciones críticas:
1. DETERMINA LOS NOMBRES REALES: Analiza detenidamente el texto para deducir los nombres reales de los hablantes si se presentan, se saludan, se llaman por su nombre o se infiere por el contexto. Si los detectas, usa sus nombres reales como etiquetas (por ejemplo: **Juan**, **María**, **Entrevistador**, etc.) en lugar de "Hablante A" o "Hablante B".
2. Identificá los cambios de turno de palabra basándote en la coherencia y las preguntas/respuestas.
3. Formateá la salida como un diálogo claro, precediendo cada intervención con el nombre del hablante o su etiqueta en negrita, por ejemplo:
**Nombre del Hablante**: [texto original hablado en este turno]

4. Preservación absoluta: No resumas, no edites ni elimines contenido. Mantené el 100% de las palabras originales habladas.
5. Respondé ÚNICAMENTE con el diálogo formateado. Está prohibido incluir saludos, introducciones, explicaciones o conclusiones.

TRANSCRIPCIÓN:
{transcript}"""
}

@app.post("/api/analyze")
async def analyze_transcript(req: AnalyzeRequest):
    """
    Analiza una transcripción con IA para uso periodístico.
    Modos: summary (resumen), quotes (citas), data (datos duros), angle (ángulos de nota)
    """
    local_groq = get_local_groq(req.groq_api_key)
    if not local_groq:
        raise HTTPException(status_code=503, detail="Groq API no configurada.")

    if req.mode not in JOURNALIST_PROMPTS:
        raise HTTPException(status_code=400, detail=f"Modo inválido. Opciones: {list(JOURNALIST_PROMPTS.keys())}")

    if len(req.transcript.strip()) < 50:
        raise HTTPException(status_code=400, detail="La transcripción es demasiado corta para analizar.")

    # Truncar si es muy larga (Groq tiene límite de tokens)
    transcript = req.transcript
    # Diarization necesita más contexto para detectar nombres al principio y al final
    max_chars = 16000 if req.mode == "diarization" else 12000
    if len(transcript) > max_chars:
        half = max_chars // 2
        transcript = transcript[:half] + "\n\n[...] [Parte omitida por longitud] [...] \n\n" + transcript[-half:]

    prompt = JOURNALIST_PROMPTS[req.mode].replace("{transcript}", transcript)

    # Modelos a intentar en orden: el grande primero, el liviano como fallback
    MODELS_TO_TRY = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

    last_error = None
    for model in MODELS_TO_TRY:
        try:
            response = local_groq.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=6000 if req.mode == "diarization" else 1500,
                temperature=0.3
            )
            result = response.choices[0].message.content.strip()
            return {"result": result, "mode": req.mode, "model_used": model}

        except Exception as e:
            err_str = str(e)
            logger.exception(f"Error con modelo {model}: {err_str}")

            # Rate limit (429): intentar con el siguiente modelo
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                last_error = e
                logger.info(f"Rate limit en {model}, intentando con el siguiente modelo...")
                continue
            else:
                # Error distinto al rate limit: falla inmediata con mensaje claro
                raise HTTPException(status_code=500, detail=f"Error al analizar: {err_str}")

    # Si todos los modelos fallaron por rate limit
    raise HTTPException(
        status_code=429,
        detail="⚠️ Límite de uso de Groq alcanzado por hoy. Podés:\n1. Esperá unos minutos e intentá de nuevo.\n2. Configurar tu propia API key de Groq en Configuración (gratis en console.groq.com)."
    )


@app.post("/api/quotes")
async def extract_quotes_with_times(req: QuotesRequest):
    """
    Extrae citas textuales de la transcripción con sus tiempos de entrada/salida,
    buscándolas en los segmentos del video.
    """
    local_groq = get_local_groq(req.groq_api_key)
    if not local_groq:
        raise HTTPException(status_code=503, detail="Groq API no configurada.")

    if len(req.transcript.strip()) < 50:
        raise HTTPException(status_code=400, detail="La transcripción es demasiado corta.")

    # Usar el prompt de citas (que ahora pide JSON)
    transcript = req.transcript
    if len(transcript) > 12000:
        transcript = transcript[:6000] + "\n\n[...]\n\n" + transcript[-6000:]

    prompt = JOURNALIST_PROMPTS["quotes"].replace("{transcript}", transcript)

    MODELS_TO_TRY = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    raw_result = None

    for model in MODELS_TO_TRY:
        try:
            response = local_groq.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.3,
                response_format={"type": "json_object"} if "70b" in model else None,
            )
            raw_result = response.choices[0].message.content.strip()
            break
        except Exception as e:
            err_str = str(e)
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                continue
            raise HTTPException(status_code=500, detail=f"Error al analizar: {err_str}")

    if not raw_result:
        raise HTTPException(status_code=429, detail="Límite de Groq alcanzado. Esperá unos minutos.")

    # Parsear el JSON de la IA (puede venir envuelto en ```json ... ```)
    try:
        clean = re.sub(r'^```(?:json)?\s*', '', raw_result.strip(), flags=re.MULTILINE)
        clean = re.sub(r'```\s*$', '', clean.strip(), flags=re.MULTILINE).strip()
        # La IA a veces devuelve {"quotes": [...]} en vez de [...]
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            # Buscar la primera lista en los valores
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break
        quotes_list = parsed if isinstance(parsed, list) else []
    except Exception as parse_err:
        logger.warning(f"No se pudo parsear JSON de citas: {parse_err}. Raw: {raw_result[:300]}")
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo parsear el formato de citas generado por la IA. Por favor, reintentá. Error: {str(parse_err)}"
        )

    # Enriquecer cada cita con tiempos buscando en los segmentos
    enriched = []
    for item in quotes_list:
        if not isinstance(item, dict):
            continue
        quote_text = item.get("quote", "").strip()
        note_text  = item.get("note", "").strip()
        search_kw  = item.get("search", quote_text[:40]).strip()

        times = find_segment_times_for_quote(search_kw, req.segments)

        enriched.append({
            "quote":  quote_text,
            "note":   note_text,
            "search": search_kw,
            "start":  times.get("start"),
            "end":    times.get("end"),
            "has_time": bool(times),
        })

    return {"quotes": enriched, "total": len(enriched)}


# --- SERVIDO DE FRONTEND ---
# Este bloque DEBE ir al final para no interceptar rutas de la API
if os.path.exists(FRONTEND_DIR):
    @app.get("/{path:path}")
    async def serve_static_or_index(path: str):
        # Si la ruta está vacía, servimos index.html
        if not path:
            return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))

        # Intentamos buscar el archivo en la carpeta frontend de forma segura
        requested = Path(FRONTEND_DIR) / path
        try:
            resolved = requested.resolve()
            frontend_root = Path(FRONTEND_DIR).resolve()
            # Asegurar que la ruta resuelta está dentro de la carpeta frontend
            if frontend_root in resolved.parents or resolved == frontend_root:
                if resolved.exists() and resolved.is_file():
                    return FileResponse(str(resolved))
        except Exception as e:
            logger.debug(f"Error resolviendo ruta estática: {e}")

        # Fallback a index.html para rutas SPA
        return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))

    # Soporte explícito para HEAD / (Render HealthCheck)
    @app.head("/", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    async def serve_index():
        if os.path.exists(os.path.join(FRONTEND_DIR, 'index.html')):
            return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))
        return Response(content="StreamVault API Root", media_type="text/plain")
else:
    logger.warning(f"No se encontró la carpeta frontend en {FRONTEND_DIR}")


# --- FUNCIONES DE MANTENIMIENTO DEL SISTEMA ---

@app.post("/api/system/update-app")
async def update_app(request: Request):
    """Ejecuta git pull para traer los últimos cambios del código, protegiendo archivos de configuración locales."""
    # Protección simple: si ADMIN_TOKEN está configurado, requerir header X-ADMIN-TOKEN
    admin_token = os.environ.get('ADMIN_TOKEN')
    if admin_token:
        provided = request.headers.get('X-ADMIN-TOKEN') or request.query_params.get('admin_token')
        if not provided or provided != admin_token:
            raise HTTPException(status_code=403, detail="Se requiere token de administrador para esta operación.")
    
    # Respaldar archivos de configuración locales para evitar que git pull los borre o sobreescriba
    config_backups = {}
    files_to_backup = [
        (ROOT_DIR, ".env"),
        (ROOT_DIR, "cookies.txt"),
        (ROOT_DIR, "cookies_ig.txt"),
        (BASE_DIR, "cookies.txt"),
        (BASE_DIR, "cookies_ig.txt")
    ]
    for folder, fname in files_to_backup:
        fpath = os.path.join(folder, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "rb") as f:
                    config_backups[fpath] = f.read()
                logger.info(f"Respaldo temporal creado para: {fpath}")
            except Exception as ex:
                logger.warning(f"No se pudo respaldar {fpath}: {ex}")

    pull_error = None
    pull_stdout = ""
    pull_stderr = ""

    # Determinar directorio del repo git.
    git_repo_dir = os.environ.get('GIT_REPO_DIR', ROOT_DIR)

    try:
        import subprocess
        logger.info(f"Ejecutando git pull en: {git_repo_dir}")
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            capture_output=True,
            text=True,
            cwd=git_repo_dir
        )
        pull_stdout = result.stdout.strip()
        pull_stderr = result.stderr.strip()

        if result.returncode != 0:
            pull_error = f"git pull salió con código {result.returncode}. stderr: {pull_stderr}"
        elif "Already up to date" in pull_stdout:
            pull_stdout = "La aplicación ya está actualizada. No hay cambios nuevos."
    except FileNotFoundError:
        pull_error = "Git no está instalado o no está en el PATH."
    except Exception as e:
        pull_error = str(e)

    # Restaurar siempre los archivos de configuración respaldados
    for fpath, content in config_backups.items():
        try:
            with open(fpath, "wb") as f:
                f.write(content)
            logger.info(f"Restaurado archivo de configuración/cookie en: {fpath}")
        except Exception as ex:
            logger.warning(f"No se pudo restaurar {fpath}: {ex}")

    if pull_error:
        return JSONResponse(status_code=500, content={"error": f"Error al actualizar: {pull_error}"})

    return {"status": "ok", "message": "✅ Aplicación actualizada con éxito. Recargando...", "output": pull_stdout}

@app.post("/api/system/update-engine")
async def update_engine(request: Request):
    """Actualiza el ejecutable yt-dlp.exe."""
    admin_token = os.environ.get('ADMIN_TOKEN')
    if admin_token:
        provided = request.headers.get('X-ADMIN-TOKEN') or request.query_params.get('admin_token')
        if not provided or provided != admin_token:
            raise HTTPException(status_code=403, detail="Se requiere token de administrador para esta operación.")
    try:
        import subprocess
        ytdlp_path = os.path.join(ROOT_DIR, "yt-dlp.exe")
        if not os.path.exists(ytdlp_path):
            ytdlp_path = "yt-dlp" # Fallback a path si no está en root
            
        result = subprocess.run([ytdlp_path, "-U"], capture_output=True, text=True, check=True)
        return {"status": "ok", "message": "Motor de descarga actualizado.", "output": result.stdout}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Error al actualizar motor: {str(e)}"})

@app.post("/api/system/reset")
async def reset_system(request: Request):
    """Limpia descargas y base de datos (mantenimiento extremo)."""
    admin_token = os.environ.get('ADMIN_TOKEN')
    if admin_token:
        provided = request.headers.get('X-ADMIN-TOKEN') or request.query_params.get('admin_token')
        if not provided or provided != admin_token:
            raise HTTPException(status_code=403, detail="Se requiere token de administrador para esta operación.")
    try:
        import shutil
        # 1. Limpiar descargas
        if os.path.exists(DOWNLOAD_FOLDER):
            shutil.rmtree(DOWNLOAD_FOLDER)
            os.makedirs(DOWNLOAD_FOLDER)
        
        # 2. Limpiar cache de la base de datos
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM transcripts")
            conn.commit()
            conn.close()
        except Exception as db_err:
            logger.exception(f"Error al limpiar la base de datos en reset: {db_err}")

        return {"status": "ok", "message": "Sistema reseteado (descargas y caché limpias)."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

if __name__ == "__main__":

    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        timeout_keep_alive=600,   # 10 minutos — soporta videos muy largos
        h11_max_incomplete_event_size=None,  # sin límite de tamaño de respuesta
    )
