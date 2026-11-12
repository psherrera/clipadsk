"""
Clipadsk - Backend (FastAPI)

Descarga y transcripción de video/audio para periodistas.
- Subtítulos de YouTube → Groq Whisper → Whisper local (en cascada)
- Herramientas periodísticas con IA (resumen, citas con tiempos, datos, ángulos, diarización)

Módulos:
  config.py      variables de entorno, rutas, logging
  text_utils.py  funciones puras (subtítulos, SRT, citas, URLs) — con tests
  media.py       FFmpeg y transcripción (Groq / Whisper local)
  ai.py          limpieza, traducción y análisis con Groq
"""
import os
import re
import io
import json
import time
import uuid
import hmac
import base64
import random
import shutil
import sqlite3
import asyncio
import zipfile
import mimetypes
import threading
import tempfile
import functools
import subprocess
import sys
import http.cookiejar
from pathlib import Path
from typing import Optional, Any, List
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor

import requests
import yt_dlp
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, UploadFile, File, Form, Response
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import (
    logger, BASE_DIR, ROOT_DIR, HOME_DIR, DATA_DIR, FRONTEND_DIR, DOWNLOAD_FOLDER, DB_FILE, CACHE_FILE,
    HOST, PORT, ADMIN_TOKEN, ALLOWED_ORIGINS, HAS_FFMPEG, FFMPEG_BIN,
    MAX_WORKERS, MAX_CONCURRENT_JOBS, MAX_UPLOAD_MB, GROQ_MAX_UPLOAD_MB,
    IS_LOCAL_ONLY, ALLOWED_HOSTS, YTDLP_NO_CHECK_CERTIFICATE,
)
from formats import (
    build_format_list, download_format_opts, normalize_quality, TRIM_FFMPEG_ARGS,
)
from text_utils import (
    sanitize_url, parse_subtitles_to_segments, generate_srt_from_segments, remove_repetitions,
    find_segment_times_for_quote, ensure_paragraphs, host_matches, is_allowed_thumbnail_url, safe_filename,
    is_trusted_host, is_partial_download, clip_segments,
    YOUTUBE_DOMAINS, INSTAGRAM_DOMAINS, TIKTOK_DOMAINS, TWITTER_DOMAINS, FACEBOOK_DOMAINS,
)
from errors import friendly_error
import history as hist
import media
import ai

try:
    import instaloader
except ImportError:
    instaloader = None

try:
    from cachetools import TTLCache
except ImportError:  # pragma: no cover
    TTLCache = None


APP_VERSION = "3.1.0"
app = FastAPI(title="Clipadsk API", version=APP_VERSION)

# ─── EJECUCIÓN EN SEGUNDO PLANO ──────────────────────────────────────────────
# Todo lo que bloquea (yt-dlp, FFmpeg, Groq, requests) se corre en hilos para que el
# servidor siga respondiendo (progreso, logs) mientras trabaja.
EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
HEAVY_JOBS = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


async def run_blocking(fn: Any, *args, **kwargs):
    """Corre una función bloqueante en el pool, limitando trabajos pesados simultáneos."""
    async with HEAVY_JOBS:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(EXECUTOR, functools.partial(fn, *args, **kwargs))


async def run_light(fn: Any, *args, **kwargs):
    """Corre una función bloqueante liviana (HTTP corto, disco) sin ocupar un cupo pesado."""
    return await asyncio.to_thread(fn, *args, **kwargs)


# ─── SEGURIDAD ───────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def block_foreign_origins(request: Request, call_next):
    """
    1) Host: solo se atiende si se entró por localhost, una IP, un nombre de la red local
       o un dominio declarado en ALLOWED_HOSTS. Esto frena el "DNS rebinding" (una web
       ajena que apunta su dominio a 127.0.0.1 para manejar la app desde el navegador).
    2) CORS no frena los POST "simples" (formularios) de otras páginas: igual llegan al
       servidor. Rechazamos cualquier petición a /api/ que venga con un Origin ajeno.
    """
    if not is_trusted_host(request.headers.get("host", ""), ALLOWED_HOSTS):
        logger.warning(f"Petición bloqueada: Host no permitido ({request.headers.get('host', '')!r})")
        return JSONResponse(status_code=400, content={
            "detail": "Host no permitido. Si usás un dominio propio, agregalo a ALLOWED_HOSTS en .env."})
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and "*" not in ALLOWED_ORIGINS and origin not in ALLOWED_ORIGINS:
            # Mismo host que sirve la app (p. ej. acceso por IP en la red con HOST=0.0.0.0).
            # Es seguro porque el Host ya fue validado arriba.
            if origin.split("://", 1)[-1] != request.headers.get("host", ""):
                logger.warning(f"Petición bloqueada desde origen no permitido: {origin}")
                return JSONResponse(status_code=403, content={"detail": "Origen no permitido."})
    return await call_next(request)


def require_admin(request: Request):
    """
    Operaciones de mantenimiento (actualizar, resetear, borrar descargas).
    - Con ADMIN_TOKEN definido: exige el header X-ADMIN-TOKEN.
    - Sin ADMIN_TOKEN: solo se permiten si el servidor es accesible únicamente desde
      esta PC. Expuesto a la red (HOST=0.0.0.0, Docker, Render) quedan bloqueadas.
    """
    if ADMIN_TOKEN:
        provided = request.headers.get('X-ADMIN-TOKEN', '')
        if not hmac.compare_digest(provided.encode(), ADMIN_TOKEN.encode()):
            raise HTTPException(status_code=403, detail="Se requiere token de administrador para esta operación.")
    elif not IS_LOCAL_ONLY:
        raise HTTPException(status_code=403, detail="Mantenimiento deshabilitado: el servidor está expuesto a la red "
                            "y no tiene ADMIN_TOKEN. Definí ADMIN_TOKEN en .env y reiniciá.")


# ─── PROGRESO, LOGS Y RESULTADOS (memoria, con vencimiento) ──────────────────
if TTLCache:
    progress_store = TTLCache(maxsize=500, ttl=7200)
    log_store = TTLCache(maxsize=500, ttl=7200)
    result_store = TTLCache(maxsize=100, ttl=3600)
else:  # pragma: no cover
    progress_store, log_store, result_store = {}, {}, {}


def update_progress(uid: Optional[str], progress: int, text: str):
    if uid:
        progress_store[uid] = {"progress": progress, "text": text}
        add_log(uid, f"Progreso {progress}%: {text}")


def add_log(uid: Optional[str], message: str):
    logger.debug(f"[{uid}] {message}")
    if not uid:
        return
    log_store.setdefault(uid, []).append(f"[{time.strftime('%H:%M:%S')}] {message}")


def store_result(uid: Optional[str], result: dict):
    if uid:
        result_store[uid] = result


@app.get("/api/progress/{uid}")
async def get_progress(uid: str):
    return progress_store.get(uid, {"progress": 0, "text": "Procesando en el servidor..."})


@app.get("/api/logs/{uid}")
async def get_logs(uid: str):
    return {"logs": "\n".join(log_store.get(uid, ["No hay logs disponibles para esta sesion."]))}


@app.get("/api/result/{uid}")
async def get_transcript_result(uid: str):
    """Recupera una transcripción terminada si la conexión del navegador se cortó."""
    result = result_store.get(uid)
    if result is None:
        raise HTTPException(status_code=404, detail="Resultado no disponible. La transcripción puede no haber terminado o el UID es incorrecto.")
    return result


# ─── CACHÉ DE TRANSCRIPCIONES (SQLite) ───────────────────────────────────────

def db_connect():
    return sqlite3.connect(DB_FILE, timeout=10)


def init_db():
    with db_connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS transcripts
                        (url TEXT PRIMARY KEY, transcript TEXT, date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        if os.path.exists(CACHE_FILE):  # migración del formato JSON viejo
            logger.info("Migrando historial de JSON a SQLite...")
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    for url, text in json.load(f).items():
                        conn.execute("INSERT OR IGNORE INTO transcripts (url, transcript) VALUES (?, ?)", (url, text))
                conn.commit()
                os.replace(CACHE_FILE, CACHE_FILE + ".migrated")
            except Exception:
                logger.exception("Error en migración de cache JSON a SQLite")


def cache_get(key: str) -> Optional[dict]:
    try:
        with db_connect() as conn:
            row = conn.execute("SELECT transcript FROM transcripts WHERE url = ?", (key,)).fetchone()
    except Exception:
        logger.exception("Error leyendo cache")
        return None
    if not row:
        return None
    try:
        parsed = json.loads(row[0])
        if isinstance(parsed, dict) and "transcript" in parsed:
            return parsed
    except (TypeError, ValueError):
        pass
    return {"transcript": row[0], "srt": "", "segments": []}  # entradas viejas (solo texto)


def cache_set(key: str, data: dict):
    try:
        with db_connect() as conn:
            conn.execute("INSERT OR REPLACE INTO transcripts (url, transcript) VALUES (?, ?)", (key, json.dumps(data)))
    except Exception:
        logger.exception("Error guardando en cache")


init_db()
hist.init(DB_FILE)


# ─── YT-DLP ──────────────────────────────────────────────────────────────────

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
]
DESKTOP_UA = USER_AGENTS[0]
MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1'

_env_cookie_files: dict = {}


def _cookie_file_from_env(var_names) -> Optional[str]:
    """Cookies en base64 por variable de entorno (Render/Docker). Se escriben una sola vez."""
    for var in var_names:
        b64 = os.environ.get(var)
        if not b64:
            continue
        if var not in _env_cookie_files:
            try:
                tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
                tmp.write(base64.b64decode(b64).decode())
                tmp.close()
                _env_cookie_files[var] = tmp.name
            except Exception:
                logger.exception(f"Cookies inválidas en {var}")
                continue
        return _env_cookie_files[var]
    return None


def find_cookie_file(url: str) -> Optional[str]:
    is_instagram = host_matches(url, INSTAGRAM_DOMAINS)
    env_vars = ['INSTAGRAM_COOKIES_B64', 'COOKIES_B64'] if is_instagram else ['COOKIES_B64']
    env_file = _cookie_file_from_env(env_vars)
    if env_file:
        return env_file
    names = ['cookies_ig.txt', 'cookies.txt'] if is_instagram else ['cookies.txt']
    candidates = [os.environ.get('COOKIES_PATH', '')]
    for name in names:
        candidates += [f'/etc/secrets/{name}', os.path.join(BASE_DIR, name), os.path.join(ROOT_DIR, name),
                       os.path.join(HOME_DIR, name)]
    return next((p for p in candidates if p and os.path.exists(p)), None)


def get_robust_opts(target_url: str, extra: Optional[dict] = None) -> dict:
    """Opciones base de yt-dlp: cookies, user-agent y headers por plataforma."""
    opts = {
        'quiet': True,
        'no_warnings': False,
        'cachedir': False,
        'noplaylist': True,
        'nocheckcertificate': YTDLP_NO_CHECK_CERTIFICATE,
        'ignoreerrors': False,
        'user_agent': random.choice(USER_AGENTS),
        'js_runtimes': {'deno': {}, 'node': {}},
        'remote_components': ['ejs:github'],
    }
    if FFMPEG_BIN:
        opts['ffmpeg_location'] = FFMPEG_BIN
    cookie = find_cookie_file(target_url)
    if cookie:
        opts['cookiefile'] = cookie

    if host_matches(target_url, TIKTOK_DOMAINS):
        opts['user_agent'] = MOBILE_UA
        opts['http_headers'] = {'Referer': 'https://www.tiktok.com/', 'Accept-Language': 'es-419,es;q=0.9,en;q=0.8'}
    elif host_matches(target_url, YOUTUBE_DOMAINS + TWITTER_DOMAINS + FACEBOOK_DOMAINS) or 'mediadelivery.net' in target_url:
        opts['user_agent'] = DESKTOP_UA
    elif 'b-cdn.net' in target_url and 'playlist.m3u8' in target_url:
        referer = os.environ.get('BUNNY_REFERER', '')
        if referer:
            opts['http_headers'] = {'Referer': referer}

    opts.update(extra or {})
    return opts


def _strategies(url: str) -> list:
    """Estrategias en orden: normal (con cookies), móvil sin cookies, solo iOS."""
    def no_cookies(clients):
        def apply(opts):
            opts.pop('cookiefile', None)
            opts['extractor_args'] = {'youtube': {'player_client': clients}}
        return apply
    strategies = [("normal", lambda o: None)]
    if host_matches(url, YOUTUBE_DOMAINS):
        strategies += [("móvil sin cookies", no_cookies(['android', 'ios'])), ("solo iOS", no_cookies(['ios']))]
    return strategies


def ytdlp_extract(url: str, extra: Optional[dict] = None) -> dict:
    """extract_info con reintentos (bloqueante)."""
    errors = []
    for name, tweak in _strategies(url):
        opts = get_robust_opts(url, extra)
        tweak(opts)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if info:
                return info
        except Exception as e:
            errors.append(f"{name}: {str(e)[:150]}")
            logger.debug(f"extract_info ({name}) falló: {e}")
    raise RuntimeError(" | ".join(errors) or "Sin información")


def ytdlp_download(url: str, extra: dict, done_check, on_attempt=None, cleanup=None):
    """
    Descarga con reintentos (bloqueante). done_check() decide si el intento
    produjo lo esperado (yt-dlp a veces "termina bien" sin bajar nada).
    cleanup() borra los restos de un intento fallido (archivos a medias) antes del
    siguiente intento y al fallar del todo.
    """
    errors = []
    for n, (name, tweak) in enumerate(_strategies(url), start=1):
        if on_attempt:
            on_attempt(n, name)
        opts = get_robust_opts(url, extra)
        tweak(opts)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            errors.append(f"{name}: {str(e)[:150]}")
            logger.debug(f"Descarga ({name}) falló: {e}")
        if done_check():
            return
        if cleanup:
            cleanup()
    raise RuntimeError(" | ".join(errors) or "yt-dlp no descargó ningún archivo")


# ─── BUNNY STREAM (videos embebidos en páginas web) ──────────────────────────

KNOWN_PLATFORMS = YOUTUBE_DOMAINS + INSTAGRAM_DOMAINS + TIKTOK_DOMAINS + TWITTER_DOMAINS + FACEBOOK_DOMAINS


def detect_bunny_embed(page_url: str) -> Optional[str]:
    """Busca un iframe de Bunny Stream o un m3u8 de Bunny CDN en una página web."""
    if 'mediadelivery.net' in page_url or 'b-cdn.net' in page_url:
        return None
    if host_matches(page_url, KNOWN_PLATFORMS) or not page_url.startswith(('http://', 'https://')):
        return None
    try:
        # Las cookies se pasan como "jar": requests manda a cada sitio SOLO las cookies de
        # ese dominio. (Antes se mandaban todas —incluidas las de YouTube— a cualquier página.)
        cookies = None
        cookie_path = next((p for p in (os.path.join(BASE_DIR, 'cookies.txt'), os.path.join(ROOT_DIR, 'cookies.txt'),
                                         os.path.join(HOME_DIR, 'cookies.txt'))
                            if os.path.exists(p)), None)
        if cookie_path:
            try:
                cookies = http.cookiejar.MozillaCookieJar(cookie_path)
                cookies.load(ignore_discard=True, ignore_expires=True)
            except Exception:
                cookies = None
        resp = requests.get(page_url, headers={'User-Agent': DESKTOP_UA, 'Accept-Language': 'es-419,es;q=0.9,en;q=0.8'},
                            cookies=cookies, timeout=15)
        if resp.status_code != 200:
            return None
        html = resp.text
        m = re.search(r'(https?://iframe\.mediadelivery\.net/embed/\d+/[a-f0-9\-]+)', html, re.I)
        if m:
            return m.group(1)
        m = re.search(r'mediadelivery\.net[^"\']*?/embed/(\d+)/([a-f0-9\-]{36})', html, re.I)
        if m:
            return f"https://iframe.mediadelivery.net/embed/{m.group(1)}/{m.group(2)}"
        m = re.search(r'(https?://[a-z0-9\-]+\.b-cdn\.net/[a-f0-9\-]+/playlist\.m3u8)', html, re.I)
        if m:
            return m.group(1)
    except Exception as e:
        logger.debug(f"detect_bunny_embed error para {page_url}: {e}")
    return None


async def resolve_url(raw_url: str) -> str:
    url = sanitize_url(raw_url)
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="La URL debe empezar con http:// o https://")
    bunny = await run_light(detect_bunny_embed, url)
    if bunny:
        logger.info(f"Bunny embed encontrado en {url} → {bunny}")
        return bunny
    return url


# ─── INSTAGRAM ───────────────────────────────────────────────────────────────

def get_instagram_info(url: str) -> dict:
    """Info de un Reel/Post de Instagram con instaloader (bloqueante)."""
    if not instaloader:
        raise RuntimeError("instaloader no está instalado")
    L = instaloader.Instaloader(download_videos=True, download_video_thumbnails=True, download_geotags=False,
                                download_comments=False, save_metadata=False, compress_json=False, quiet=True)
    ig_user, ig_pass = os.environ.get('IG_USER', ''), os.environ.get('IG_PASS', '')
    if ig_user and ig_pass:
        try:
            L.login(ig_user, ig_pass)
        except Exception as e:
            logger.debug(f"Instaloader login falló: {e}")
    match = re.search(r'/(reel|reels|p|tv)/([A-Za-z0-9_-]+)', url)
    if not match:
        raise RuntimeError("No se pudo extraer el código del post de Instagram")
    shortcode = match.group(2)
    post = instaloader.Post.from_shortcode(L.context, shortcode)
    try:
        thumbnail = post.url
    except Exception:
        thumbnail = None
    sidecar = None
    if getattr(post, 'typename', '') == 'GraphSidecar':
        sidecar = []
        for node in post.get_sidecar_nodes():
            is_video = bool(node.is_video)
            sidecar.append({'url': node.video_url if is_video else node.display_url, 'thumb': node.display_url,
                            'is_video': is_video, 'ext': 'mp4' if is_video else 'jpg'})
    return {
        'sidecar': sidecar,
        'caption': post.caption or '',
        'shortcode': shortcode,
        'title': post.caption[:100] if post.caption else f"Instagram Reel {shortcode}",
        'thumbnail': thumbnail,
        'duration': int(post.video_duration) if post.is_video and post.video_duration else None,
        'uploader': post.owner_username,
        'is_video': post.is_video,
        'video_url': post.video_url if post.is_video else None,
    }


_GALLERY_LOCK = threading.Lock()


def _gallery_dl_inprocess(url: str, cookies_path: Optional[str]) -> Optional[list]:
    """gallery-dl como biblioteca (Clipa.exe no tiene el ejecutable gallery-dl)."""
    try:
        from gallery_dl import config as gdl_config, job as gdl_job
    except ImportError:
        logger.warning("gallery-dl no está instalado (pip install gallery-dl)")
        return None
    try:
        with _GALLERY_LOCK:  # la configuración de gallery-dl es global
            gdl_config.clear()
            if cookies_path and os.path.exists(cookies_path):
                gdl_config.set(("extractor",), "cookies", cookies_path)
            job = gdl_job.DataJob(url, file=None)
            job.run()
        return [{"url": item[1], "metadata": item[2]} for item in job.data
                if isinstance(item, (list, tuple)) and len(item) >= 3 and item[0] == 3]
    except Exception:
        logger.exception("Error extrayendo carrusel con gallery-dl (biblioteca)")
        return None


def get_instagram_carousel_info(url: str, cookies_path: Optional[str] = None) -> Optional[list]:
    """Lista de imágenes/videos de un carrusel usando gallery-dl (bloqueante)."""
    candidates = [
        os.path.join(os.path.dirname(sys.executable), "gallery-dl.exe"),
        os.path.join(os.path.dirname(sys.executable), "gallery-dl"),
        os.path.join(BASE_DIR, "venv", "Scripts", "gallery-dl.exe"),
    ]
    gallery_dl = next((c for c in candidates if os.path.exists(c)), None) or shutil.which("gallery-dl")
    if not gallery_dl:
        return _gallery_dl_inprocess(url, cookies_path)
    cmd = [gallery_dl, "-j"]
    if cookies_path and os.path.exists(cookies_path):
        cmd += ["--cookies", cookies_path]
    cmd.append(url)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=120)
        if res.returncode != 0:
            logger.warning(f"gallery-dl falló ({res.returncode}): {res.stderr[:300]}")
            return None
        return [{"url": item[1], "metadata": item[2]} for item in json.loads(res.stdout)
                if isinstance(item, list) and len(item) >= 3 and item[0] == 3]
    except Exception:
        logger.exception("Error extrayendo carrusel con gallery-dl")
        return None


# ─── CARRUSELES (galería) ────────────────────────────────────────────────────

CAROUSEL_TTL = 15 * 60
_CAROUSEL_CACHE: dict = {}  # url → (timestamp, datos): evita volver a consultar Instagram al descargar


def _clean_ext(ext: Optional[str], is_video: bool) -> str:
    ext = re.sub(r'[^a-z0-9]', '', (ext or '').lower())[:5]
    return ext or ('mp4' if is_video else 'jpg')


def carousel_from_gallery(files: list) -> dict:
    """Normaliza la salida de gallery-dl a {items, username, description, shortcode}."""
    items = []
    for f in files:
        meta = f.get('metadata') or {}
        ext = (meta.get('extension') or '').lower()
        is_video = ext in ('mp4', 'mov', 'webm', 'm4v') or bool(meta.get('video_url'))
        thumb = meta.get('display_url') or (None if is_video else f.get('url'))
        items.append({'url': f.get('url'), 'thumb': thumb, 'is_video': is_video, 'ext': _clean_ext(ext, is_video)})
    meta = (files[0].get('metadata') or {}) if files else {}
    return {'items': [i for i in items if i['url']], 'username': meta.get('username') or 'instagram',
            'description': meta.get('description') or '', 'shortcode': meta.get('post_shortcode') or meta.get('shortcode') or ''}


def remember_carousel(url: str, data: dict) -> dict:
    now = time.time()
    for k in [k for k, (t, _) in _CAROUSEL_CACHE.items() if now - t > CAROUSEL_TTL]:
        _CAROUSEL_CACHE.pop(k, None)
    _CAROUSEL_CACHE[url] = (now, data)
    return data


def get_carousel(url: str, try_instaloader: bool = True) -> Optional[dict]:
    """Ítems de un carrusel de Instagram (bloqueante). Usa la caché, después instaloader y por último gallery-dl."""
    hit = _CAROUSEL_CACHE.get(url)
    if hit and time.time() - hit[0] < CAROUSEL_TTL:
        return hit[1]
    if try_instaloader and instaloader:
        try:
            ig = get_instagram_info(url)
            if ig.get('sidecar'):
                return remember_carousel(url, {'items': ig['sidecar'], 'username': ig.get('uploader') or 'instagram',
                                               'description': ig.get('caption') or '', 'shortcode': ig.get('shortcode') or ''})
        except Exception as e:
            logger.debug(f"instaloader no pudo leer el carrusel: {e}")
    files = get_instagram_carousel_info(url, find_cookie_file(url))
    if not files:
        return None
    data = carousel_from_gallery(files)
    return remember_carousel(url, data) if data['items'] else None


def carousel_info_response(data: dict) -> dict:
    """Respuesta de /api/video-info para un carrusel: incluye la lista de miniaturas para la galería."""
    items = data['items']
    n, n_videos = len(items), sum(1 for i in items if i['is_video'])
    title = data.get('description') or f"Carrusel de Instagram {data.get('shortcode', '')}".strip()
    first_thumb = next((i['thumb'] for i in items if i.get('thumb')), None)
    thumb = proxied_thumbnail(first_thumb)
    kind = 'archivos' if n_videos else 'imágenes'
    return {
        'title': title[:100] + ('...' if len(title) > 100 else ''), 'thumbnail': thumb, 'max_res_thumbnail': thumb,
        'duration': None, 'uploader': data.get('username') or 'Instagram', 'description': data.get('description') or '',
        'formats': [{'format_id': 'carousel_images', 'ext': 'zip', 'resolution': 'Carrusel (ZIP)', 'filesize': None,
                     'label': f"Todo el carrusel: {n} {kind} (.zip)"}],
        'carousel': [{'index': k, 'thumb': proxied_thumbnail(i.get('thumb')), 'is_video': i['is_video'], 'ext': i['ext']}
                     for k, i in enumerate(items)],
        'has_ffmpeg': HAS_FFMPEG, 'has_subtitles': False, 'can_transcribe': True,
    }


def proxied_thumbnail(url: Optional[str]) -> Optional[str]:
    return f"/api/proxy-thumbnail?url={quote(url, safe='')}" if url else None


def http_download(url: str, dest: str, headers: dict, timeout: int = 60):
    with requests.get(url, headers=headers, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)


# ─── MODELOS ─────────────────────────────────────────────────────────────────

class VideoRequest(BaseModel):
    url: str
    format_id: Optional[str] = "best"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    groq_api_key: Optional[str] = None
    uid: Optional[str] = None
    target_lang: Optional[str] = "es"  # es, en, original
    quality: Optional[str] = "compatible"  # compatible (H.264) | max (VP9/AV1)
    burn_subs: Optional[bool] = False      # quemar subtítulos en el recorte
    vertical: Optional[bool] = False       # recorte en 9:16 para redes
    segments: Optional[list] = None        # segmentos de la transcripción (para los subtítulos)
    items: Optional[List[int]] = None      # carrusel: posiciones elegidas (desde 0); vacío = todas


class ChatRequest(BaseModel):
    url: Optional[str] = ""
    question: str
    transcript: str
    groq_api_key: Optional[str] = None


class AnalyzeRequest(BaseModel):
    transcript: str
    mode: str  # summary | data | angle | diarization
    groq_api_key: Optional[str] = None


class QuotesRequest(BaseModel):
    transcript: str
    segments: list = []
    groq_api_key: Optional[str] = None


class ExportDocxRequest(BaseModel):
    title: str
    uploader: Optional[str] = ""
    url: Optional[str] = ""
    description: Optional[str] = ""
    transcript: str


def require_groq(api_key: Optional[str]):
    client = ai.get_groq_client(api_key)
    if not client:
        raise HTTPException(status_code=503, detail="Groq API no configurada. Cargá tu API Key en Configuración.")
    return client


def ai_error(e: Exception) -> HTTPException:
    if isinstance(e, ai.NoModelAvailableError):
        return HTTPException(status_code=503, detail=str(e))
    if isinstance(e, ai.RateLimitedError) or ai.is_rate_limit(e):
        return HTTPException(status_code=429, detail="⚠️ Límite de uso de Groq alcanzado. Podés:\n1. Esperar unos minutos e intentar de nuevo.\n2. Configurar tu propia API key de Groq en Configuración (gratis en console.groq.com).")
    logger.exception("Error de IA")
    return HTTPException(status_code=500, detail=f"Error al analizar: {e}")


# ─── ENDPOINTS: SALUD ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Chequeo rápido (no sale a internet)."""
    return {"status": "ok", "version": APP_VERSION, "ffmpeg": HAS_FFMPEG, "whisper_local": media.WHISPER_MODEL_AVAILABLE,
            "groq_server_key": ai.get_groq_client() is not None, "yt_dlp": yt_dlp.version.__version__,
            "has_cookies": find_cookie_file("https://www.youtube.com/") is not None}


@app.get("/api/health/cookies")
async def check_cookies():
    """Verifica si las cookies de YouTube siguen funcionando (prueba real, tarda unos segundos)."""
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    try:
        info = await run_light(lambda: yt_dlp.YoutubeDL(get_robust_opts(test_url)).extract_info(test_url, download=False))
        return {"status": "ok", "cookie_valid": True, "video_title": info.get('title'),
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        return {"status": "error", "cookie_valid": False, "error": friendly_error(e), "technical": str(e)[:300],
                "server_time": time.strftime("%Y-%m-%d %H:%M:%S")}


# ─── ENDPOINTS: INFO DE VIDEO ────────────────────────────────────────────────

MP3_FORMAT = {'format_id': 'mp3', 'ext': 'mp3', 'resolution': 'Solo audio', 'filesize': None, 'label': 'Solo audio (.mp3)'}
BEST_FORMAT = {'format_id': 'best', 'ext': 'mp4', 'resolution': 'Mejor calidad', 'filesize': None, 'label': 'Mejor calidad (.mp4)'}


@app.post("/api/video-info")
async def get_video_info(req: VideoRequest):
    url = await resolve_url(req.url)
    is_instagram = host_matches(url, INSTAGRAM_DOMAINS)

    if is_instagram and instaloader:
        try:
            ig = await run_light(get_instagram_info, url)
            if ig.get('sidecar'):
                return carousel_info_response(remember_carousel(url, {
                    'items': ig['sidecar'], 'username': ig.get('uploader') or 'instagram',
                    'description': ig.get('caption') or '', 'shortcode': ig.get('shortcode') or ''}))
            formats = [BEST_FORMAT, MP3_FORMAT] if ig['is_video'] else [
                {'format_id': 'best', 'ext': 'jpg', 'resolution': 'Imagen original', 'filesize': None, 'label': 'Imagen original (.jpg)'}]
            thumb = proxied_thumbnail(ig.get('thumbnail'))
            return {'title': ig['title'], 'thumbnail': thumb, 'max_res_thumbnail': thumb, 'duration': ig.get('duration'),
                    'uploader': ig.get('uploader') or 'Instagram', 'description': ig['title'], 'formats': formats,
                    'has_ffmpeg': HAS_FFMPEG, 'has_subtitles': False}
        except Exception as e:
            logger.debug(f"Instaloader falló, intentando con yt-dlp: {e}")

    try:
        info = await run_blocking(ytdlp_extract, url)
    except Exception as e:
        last_error = str(e)
        logger.error(f"No se pudo obtener info de {url}: {last_error[:300]}")
        if is_instagram:
            data = await run_blocking(get_carousel, url, False)
            if data:
                return carousel_info_response(data)
        raise HTTPException(status_code=400, detail=friendly_error(last_error))

    # Carrusel con varios videos: yt-dlp lo devuelve como lista → galería
    if is_instagram and (info.get('_type') == 'playlist' or info.get('entries')):
        data = await run_blocking(get_carousel, url, False)
        if data:
            return carousel_info_response(data)

    formats = build_format_list(info.get('formats') or [], HAS_FFMPEG)
    if not formats:
        formats.append(BEST_FORMAT)
    if HAS_FFMPEG:
        formats.append(MP3_FORMAT)

    thumbnail = info.get('thumbnail')
    if is_instagram:
        thumbnail = proxied_thumbnail(thumbnail)
    return {
        'title': info.get('title'),
        'thumbnail': thumbnail,
        'max_res_thumbnail': thumbnail,
        'duration': info.get('duration'),
        'uploader': info.get('uploader') or "Desconocido",
        'description': (info.get('description') or 'Sin descripción')[:200] + '...',
        'formats': formats,
        'has_ffmpeg': HAS_FFMPEG,
        'has_subtitles': bool(info.get('subtitles') or info.get('automatic_captions')),
        'has_manual_subtitles': bool(info.get('subtitles')),
    }


# ─── ENDPOINTS: TRANSCRIPCIÓN DE URL ─────────────────────────────────────────

def _find_file(folder: str, prefix: str, contains=()) -> Optional[str]:
    """Primer archivo TERMINADO con ese prefijo (ignora descargas a medias de yt-dlp)."""
    for f in sorted(os.listdir(folder)):
        if is_partial_download(f):
            continue
        if f.startswith(prefix) and (not contains or any(c in f for c in contains)):
            return os.path.join(folder, f)
    return None


def transcribe_from_subtitles(url: str, lang: str, tmpdir: str, uid: Optional[str]) -> Optional[dict]:
    """Intenta usar los subtítulos de YouTube (sin descargar audio). Bloqueante."""
    def has_subs():
        return _find_file(tmpdir, 'sub.') is not None

    extra = {'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True,
             'subtitleslangs': ['es.*', 'en.*'], 'subtitlesformat': 'vtt/srt/best',
             'outtmpl': os.path.join(tmpdir, 'sub.%(ext)s')}
    try:
        ytdlp_download(url, extra, has_subs,
                       on_attempt=lambda n, name: update_progress(uid, 5 + n * 5, f"Buscando subtítulos ({name})..."))
    except Exception as e:
        add_log(uid, f"Sin subtítulos: {str(e)[:200]}")
        return None

    sub_file = _find_file(tmpdir, 'sub.', ('.es',))
    is_english = False
    if not sub_file:
        sub_file = _find_file(tmpdir, 'sub.', ('.en',))
        is_english = sub_file is not None
    if not sub_file:
        return None

    with open(sub_file, 'r', encoding='utf-8', errors='replace') as f:
        segments = parse_subtitles_to_segments(f.read())
    if not segments:
        return None

    # Los subtítulos automáticos repiten texto entre segmentos: limpiar
    for seg in segments:
        seg["text"] = remove_repetitions(seg["text"])
    if is_english and lang == "es":
        update_progress(uid, 50, "Traduciendo subtítulos al español...")
        for seg, t in zip(segments, ai.translate_texts([s["text"] for s in segments], "es")):
            seg["text"] = t
    raw_text = remove_repetitions(' '.join(s["text"] for s in segments))
    return {"raw": raw_text, "segments": segments, "method": "subtitles"}


def transcribe_from_audio(url: str, lang: str, tmpdir: str, uid: Optional[str], client) -> dict:
    """Descarga el audio y lo transcribe (Groq → Whisper local). Bloqueante."""
    add_log(uid, "Descargando audio para transcribir...")
    extra = {'format': 'bestaudio/best', 'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s')}

    def has_audio():
        return _find_file(tmpdir, 'audio.') is not None

    ytdlp_download(url, extra, has_audio,
                   on_attempt=lambda n, name: update_progress(uid, 20 + n * 3, f"Descargando audio ({name})..."))
    audio_file = _find_file(tmpdir, 'audio.')
    if HAS_FFMPEG:
        update_progress(uid, 30, "Preparando audio...")
        audio_file = media.to_speech_mp3(audio_file, os.path.join(tmpdir, 'speech.mp3'))

    text, segments, method = media.transcribe_audio(
        audio_file, lang, client, tmpdir,
        progress=lambda p, t: update_progress(uid, p, t), log=lambda m: add_log(uid, m))
    return {"raw": remove_repetitions(text.strip()), "segments": segments, "method": method}


def transcribe_instagram_carousel(files: list, client, uid: Optional[str]) -> str:
    """OCR de un carrusel de imágenes con Groq Vision. Bloqueante."""
    parts = []
    for idx, item in enumerate(files):
        update_progress(uid, int(idx / len(files) * 90) + 5, f"Analizando diapositiva {idx + 1}/{len(files)}...")
        try:
            r = requests.get(item["url"], headers={'User-Agent': DESKTOP_UA}, timeout=20)
            r.raise_for_status()
            text = ai.ocr_image(client, base64.b64encode(r.content).decode('utf-8'))
        except Exception as e:
            logger.warning(f"OCR diapositiva {idx + 1} falló: {e}")
            text = f"[Error de extracción: {e}]"
        parts.append(f"--- DIAPOSITIVA {idx + 1} ---\n{text}")
    return "\n\n".join(parts)


def _only_images(files: list) -> bool:
    for f in files:
        meta = f.get("metadata", {})
        if meta.get("video_url") or (meta.get("extension") or "").lower() in ('mp4', 'mov', 'avi', 'mkv', 'webm'):
            return False
    return True


class TranscriptionError(Exception):
    """Error de transcripción con mensaje para el usuario (status HTTP incluido)."""
    def __init__(self, message: str, status: int = 500, technical: str = ""):
        super().__init__(message)
        self.status, self.technical = status, technical


async def transcribe_url(raw_url: str, lang: str, groq_api_key: Optional[str], uid: Optional[str]) -> dict:
    """
    Transcribe un enlace: caché → (Instagram con imágenes: OCR) → subtítulos de YouTube →
    audio con Groq / Whisper local → limpieza con IA. Lo usan /api/transcript y los
    trabajos en segundo plano. Lanza TranscriptionError con un mensaje claro.
    """
    lang = lang or "es"
    try:
        url = await resolve_url(raw_url)
    except HTTPException as e:
        raise TranscriptionError(str(e.detail), e.status_code)
    add_log(uid, f"Iniciando transcripción para: {url} | Idioma: {lang}")

    cache_key = f"{url}_{lang}"
    cached = await run_light(cache_get, cache_key)
    if cached:
        add_log(uid, "Resultado recuperado de la caché local.")
        update_progress(uid, 100, "¡Transcripción lista!")
        return {"transcript": ensure_paragraphs(cached.get("transcript", "")), "srt": cached.get("srt", ""),
                "segments": cached.get("segments", []), "raw_transcript": cached.get("raw_transcript", ""),
                "method": "cache", "resolved_url": url}

    client = ai.get_groq_client(groq_api_key)
    warnings: List[str] = []
    try:
        # Carrusel de Instagram solo con imágenes → OCR
        if host_matches(url, INSTAGRAM_DOMAINS):
            files = await run_blocking(get_instagram_carousel_info, url, find_cookie_file(url))
            if files and _only_images(files):
                if not client:
                    raise TranscriptionError("Para extraer texto de imágenes (OCR) necesitás configurar la API Key "
                                             "de Groq en Configuración.", 400)
                add_log(uid, f"Carrusel de {len(files)} imágenes: OCR con Groq Vision")
                text = await run_blocking(transcribe_instagram_carousel, files, client, uid)
                payload = {"transcript": text, "srt": "", "segments": [], "raw_transcript": text,
                           "method": "groq_vision_ocr"}
                await run_light(cache_set, cache_key, payload)
                update_progress(uid, 100, "¡Extracción de texto completa!")
                return {**payload, "resolved_url": url}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = None
            if host_matches(url, YOUTUBE_DOMAINS):
                add_log(uid, "Buscando subtítulos de YouTube...")
                result = await run_blocking(transcribe_from_subtitles, url, lang, tmpdir, uid)
            if not result:
                result = await run_blocking(transcribe_from_audio, url, lang, tmpdir, uid, client)

        raw_text = result["raw"]
        text = raw_text
        if client:
            update_progress(uid, 85, f"Aplicando puntuación y párrafos con IA ({lang})...")
            text = await run_blocking(ai.cleanup_transcript, text, client, lang, warnings)
        text = ensure_paragraphs(text)  # punto y aparte aunque la IA no lo haya hecho

        segments = result["segments"]
        payload = {"transcript": text, "srt": generate_srt_from_segments(segments), "segments": segments,
                   "raw_transcript": ensure_paragraphs(raw_text), "method": result["method"]}
        if warnings:
            payload["warnings"] = warnings  # no se cachea: la próxima vez se reintenta la limpieza
        else:
            await run_light(cache_set, cache_key, payload)
        update_progress(uid, 100, "¡Transcripción lista!")
        add_log(uid, f"Transcripción completada ({result['method']}).")
        return {**payload, "resolved_url": url}
    except TranscriptionError:
        raise
    except Exception as e:
        logger.exception("Error en transcripción")
        add_log(uid, f"Error: {e}")
        raise TranscriptionError(friendly_error(e), 500, str(e)[:400])


@app.post("/api/transcript")
async def get_transcript(req: VideoRequest):
    try:
        payload = await transcribe_url(req.url, req.target_lang or "es", req.groq_api_key, req.uid)
    except TranscriptionError as e:
        return JSONResponse(status_code=e.status, content={"error": str(e), "detail": str(e), "technical": e.technical})
    store_result(req.uid, payload)
    return payload


# ─── ENDPOINTS: TRANSCRIPCIÓN DE ARCHIVO ─────────────────────────────────────

ALLOWED_AUDIO_EXTENSIONS = {'.ogg', '.opus', '.mp3', '.m4a', '.wav', '.mp4', '.aac', '.weba', '.webm',
                            '.mov', '.avi', '.mkv', '.flac'}
VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}


async def save_upload(file: UploadFile, dest: str, max_mb: int) -> float:
    """Guarda el archivo subido en disco por partes (sin cargarlo entero en memoria)."""
    size = 0
    limit = max_mb * 1024 * 1024
    with open(dest, 'wb') as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise HTTPException(status_code=413, detail=f"El archivo es demasiado grande. Máximo: {max_mb} MB.")
            await run_light(out.write, chunk)
    return size / (1024 * 1024)


@app.post("/api/transcript-file")
async def transcript_audio_file(
    file: UploadFile = File(...),
    target_lang: str = Form(default="es"),
    uid: str = Form(default=None),
    groq_api_key: str = Form(default=None),
    is_local_video: Optional[str] = Form(default=None),
):
    """Transcribe un archivo subido (WhatsApp .ogg/.opus, grabaciones, videos)."""
    client = ai.get_groq_client(groq_api_key)
    if not client and not media.WHISPER_MODEL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Groq API no configurada. Configurá tu API Key en la interfaz o instalá faster-whisper para transcribir localmente.")

    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Formato no soportado: '{ext}'. Formatos válidos: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}")

    warnings: List[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, f"input{ext}")
        size_mb = await save_upload(file, input_path, MAX_UPLOAD_MB)
        update_progress(uid, 5, "Archivo recibido en el servidor...")
        add_log(uid, f"Archivo recibido: {file.filename} ({size_mb:.2f} MB)")

        try:
            audio_path = input_path
            if HAS_FFMPEG or media.AudioSegment:
                update_progress(uid, 10, "Convirtiendo audio...")
                try:
                    audio_path = await run_blocking(media.to_speech_mp3, input_path, os.path.join(tmpdir, "speech.mp3"))
                except Exception as e:
                    logger.warning(f"Conversión falló, se usa el archivo original: {e}")
            converted_mb = os.path.getsize(audio_path) / (1024 * 1024)
            if converted_mb >= GROQ_MAX_UPLOAD_MB and not HAS_FFMPEG and not media.WHISPER_MODEL_AVAILABLE:
                raise HTTPException(status_code=400, detail="El archivo es demasiado grande para Groq y no se puede dividir porque FFmpeg no está instalado. Instalá FFmpeg o subí un audio más corto.")

            update_progress(uid, 20, "Iniciando transcripción del audio...")
            text, segments, method = await run_blocking(
                media.transcribe_audio, audio_path, target_lang, client, tmpdir,
                progress=lambda p, t: update_progress(uid, p, t), log=lambda m: add_log(uid, m))
            text = remove_repetitions(text.strip())
            raw_text = text

            if client:
                update_progress(uid, 80, "Aplicando puntuación y párrafos con IA...")
                text = await run_blocking(ai.cleanup_transcript, text, client, target_lang, warnings)
            text = ensure_paragraphs(text)

            update_progress(uid, 100, "Completado")
            add_log(uid, "Transcripción de archivo completada.")
            payload = {"transcript": text, "srt": generate_srt_from_segments(segments), "segments": segments,
                       "raw_transcript": ensure_paragraphs(raw_text),
                       "method": method, "filename": file.filename, "size_mb": round(size_mb, 2)}
            if warnings:
                payload["warnings"] = warnings
            store_result(uid, payload)
            return payload
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Error transcribiendo archivo")
            add_log(uid, f"Error en transcripción de archivo: {e}")
            raise HTTPException(status_code=500, detail=friendly_error(e))


# ─── ENDPOINTS: DESCARGA ─────────────────────────────────────────────────────

def _remove_later(background_tasks: BackgroundTasks, *paths):
    def remove():
        for p in paths:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                logger.warning(f"No se pudo borrar {p}")
    background_tasks.add_task(remove)


def _carousel_name(index: int, item: dict) -> str:
    return f"{index + 1:02d}_{'video' if item['is_video'] else 'imagen'}.{item['ext']}"


def _fetch_carousel_item(item: dict) -> bytes:
    r = requests.get(item['url'], headers={'User-Agent': DESKTOP_UA, 'Referer': 'https://www.instagram.com/'}, timeout=60)
    r.raise_for_status()
    return r.content


def _build_carousel_zip(items: list, selected: list, zip_path: str) -> int:
    """Arma el ZIP con los ítems elegidos. Devuelve cuántos se pudieron bajar."""
    ok = 0
    with zipfile.ZipFile(zip_path, 'w') as zf:
        for idx in selected:
            try:
                zf.writestr(_carousel_name(idx, items[idx]), _fetch_carousel_item(items[idx]))
                ok += 1
            except Exception as e:
                logger.warning(f"Error descargando el archivo {idx + 1} del carrusel: {e}")
    return ok


def _save_carousel_item(item: dict, path: str):
    with open(path, 'wb') as f:
        f.write(_fetch_carousel_item(item))


def _instagram_download(ig: dict, uid: str, as_mp3: bool) -> str:
    tmp_mp4 = os.path.join(DOWNLOAD_FOLDER, f'instagram_{uid}.mp4')
    http_download(ig['video_url'], tmp_mp4, {'User-Agent': MOBILE_UA})
    if not as_mp3:
        return tmp_mp4
    mp3_path = os.path.join(DOWNLOAD_FOLDER, f'instagram_{uid}.mp3')
    try:
        media.run_ffmpeg(['-i', tmp_mp4, '-vn', '-acodec', 'libmp3lame', '-q:a', '2', mp3_path])
    finally:
        os.remove(tmp_mp4)
    return mp3_path


@app.post("/api/download")
async def download_video(req: VideoRequest, background_tasks: BackgroundTasks):
    url = await resolve_url(req.url)
    format_id = req.format_id
    file_uid = uuid.uuid4().hex

    # Carrusel de Instagram → un archivo suelto o un ZIP con los elegidos (o con todos)
    if format_id == 'carousel_images':
        data = await run_blocking(get_carousel, url)
        if not data:
            raise HTTPException(status_code=400, detail="No se pudieron leer los archivos del carrusel.")
        items = data['items']
        selected = sorted({i for i in (req.items or []) if isinstance(i, int) and 0 <= i < len(items)})
        if req.items and not selected:
            raise HTTPException(status_code=400, detail="Las fotos elegidas no están en el carrusel.")
        selected = selected or list(range(len(items)))
        user = safe_filename(data.get('username') or 'instagram', 30)
        if len(selected) == 1:
            idx = selected[0]
            path = os.path.join(DOWNLOAD_FOLDER, f"instagram_carousel_{file_uid}.{items[idx]['ext']}")
            try:
                await run_blocking(_save_carousel_item, items[idx], path)
            except Exception as e:
                raise HTTPException(status_code=502, detail=friendly_error(str(e)))
            _remove_later(background_tasks, path)
            media_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            return FileResponse(path, filename=f"carrusel_{user}_{_carousel_name(idx, items[idx])}", media_type=media_type)
        zip_path = os.path.join(DOWNLOAD_FOLDER, f"instagram_carousel_{file_uid}.zip")
        ok = await run_blocking(_build_carousel_zip, items, selected, zip_path)
        _remove_later(background_tasks, zip_path)
        if not ok:
            raise HTTPException(status_code=502, detail="Instagram no dejó bajar las fotos. Probá de nuevo en un rato.")
        return FileResponse(zip_path, filename=f"carrusel_{user}_{file_uid[:6]}.zip", media_type='application/zip')

    # Instagram con instaloader
    if host_matches(url, INSTAGRAM_DOMAINS) and instaloader:
        try:
            ig = await run_light(get_instagram_info, url)
            if not ig['is_video']:
                raise HTTPException(status_code=400, detail="Este post de Instagram no tiene video.")
            as_mp3 = format_id == 'mp3'
            if as_mp3 and not HAS_FFMPEG:
                raise HTTPException(status_code=400, detail="Para descargar como MP3 hace falta FFmpeg.")
            path = await run_blocking(_instagram_download, ig, file_uid, as_mp3)
            _remove_later(background_tasks, path)
            if not as_mp3 and (req.burn_subs or req.vertical):
                path = await run_blocking(postprocess_clip, path, req.segments or [], 0.0, float('inf'),
                                          bool(req.burn_subs), bool(req.vertical))
                _remove_later(background_tasks, path)
            ext = 'mp3' if as_mp3 else 'mp4'
            return FileResponse(path, filename=f"{safe_filename(ig['title'], 30)}_{file_uid[:6]}.{ext}",
                                media_type='audio/mpeg' if as_mp3 else 'video/mp4')
        except HTTPException:
            raise
        except Exception as e:
            logger.debug(f"Instaloader falló, intentando con yt-dlp: {e}")

    output_template = os.path.join(DOWNLOAD_FOLDER, f'%(title).80B_{file_uid}.%(ext)s')
    if format_id == 'mp3':
        if not HAS_FFMPEG:
            raise HTTPException(status_code=400, detail="Para descargar como MP3 hace falta FFmpeg.")
        extra = {'format': 'bestaudio/best', 'outtmpl': output_template,
                 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]}
    else:
        extra = {'outtmpl': output_template, **download_format_opts(format_id, req.quality, HAS_FFMPEG)}
        logger.info(f"Descarga: opción={format_id} calidad={normalize_quality(req.quality)} formato={extra['format']}")

    def hook(d):
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total:
                pct = d.get('downloaded_bytes', 0) / total * 100
                update_progress(req.uid, 20 + int(pct * 0.7), f"Descargando: {pct:.0f}%")
        elif d.get('status') == 'finished':
            update_progress(req.uid, 90, "Descarga completada, procesando con FFmpeg...")
    extra['progress_hooks'] = [hook]

    if req.start_time or req.end_time:
        from yt_dlp.utils import parse_duration, download_range_func
        start_sec = parse_duration(req.start_time) if req.start_time else 0
        end_sec = parse_duration(req.end_time) if req.end_time else float('inf')
        if start_sec is None or end_sec is None or end_sec <= start_sec:
            raise HTTPException(status_code=400, detail="Rango de tiempo inválido.")
        extra['download_ranges'] = download_range_func(None, [(start_sec, end_sec)])
        extra['force_keyframes_at_cuts'] = True
        if format_id != 'mp3':
            # Cortar justo en el segundo pedido obliga a recodificar: con calidad alta, no la de FFmpeg por defecto
            extra['external_downloader_args'] = {'ffmpeg_o': TRIM_FFMPEG_ARGS}

    def find_output():
        for f in os.listdir(DOWNLOAD_FOLDER):
            if file_uid in f and not is_partial_download(f):
                return os.path.join(DOWNLOAD_FOLDER, f)
        return None

    def remove_leftovers():
        # Restos de un intento fallido (.part, pistas sin unir): si quedan, se acumulan en disco
        for f in os.listdir(DOWNLOAD_FOLDER):
            if file_uid in f:
                try:
                    os.remove(os.path.join(DOWNLOAD_FOLDER, f))
                except OSError:
                    logger.warning(f"No se pudo borrar el resto de descarga {f}")

    update_progress(req.uid, 5, "Iniciando proceso...")
    try:
        await run_blocking(ytdlp_download, url, extra, lambda: find_output() is not None,
                           on_attempt=lambda n, name: update_progress(req.uid, 5 + n * 5, f"Conectando ({name})..."),
                           cleanup=remove_leftovers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=friendly_error(e))

    path = find_output()
    if not path:
        raise HTTPException(status_code=500, detail="El archivo no apareció después de la descarga.")
    _remove_later(background_tasks, path)
    if format_id != 'mp3' and (req.burn_subs or req.vertical):
        update_progress(req.uid, 93, "Agregando subtítulos / formato vertical...")
        clip_start = start_sec if (req.start_time or req.end_time) else 0.0
        clip_end = end_sec if (req.start_time or req.end_time) else float('inf')
        try:
            path = await run_blocking(postprocess_clip, path, req.segments or [], clip_start, clip_end,
                                      bool(req.burn_subs), bool(req.vertical))
        except Exception as e:
            raise HTTPException(status_code=500, detail=friendly_error(e))
        _remove_later(background_tasks, path)
    update_progress(req.uid, 100, "¡Archivo listo!")
    name = os.path.basename(path).replace(f"_{file_uid}", "").replace("_final.mp4", "_vertical.mp4" if req.vertical else ".mp4")
    return FileResponse(path, filename=name)


@app.get("/api/proxy-thumbnail")
async def proxy_thumbnail(url: str):
    """Proxy de miniaturas de Instagram (solo dominios de Instagram/Facebook CDN)."""
    if not is_allowed_thumbnail_url(url):
        raise HTTPException(status_code=400, detail="URL de miniatura no permitida.")
    headers = {'User-Agent': DESKTOP_UA, 'Referer': 'https://www.instagram.com/'}
    try:
        resp = await run_light(requests.get, url, headers=headers, timeout=10)
        resp.raise_for_status()
        ctype = resp.headers.get('Content-Type', 'image/jpeg')
        if not ctype.startswith('image/'):
            return Response(status_code=415)
        return Response(content=resp.content, media_type=ctype)
    except Exception as e:
        logger.debug(f"Proxy de miniatura falló: {e}")
        return Response(status_code=502)


@app.delete("/api/clear-downloads")
async def clear_downloads(request: Request):
    require_admin(request)
    def clear():
        shutil.rmtree(DOWNLOAD_FOLDER, ignore_errors=True)
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    try:
        await run_light(clear)
        return {"status": "success", "message": "Descargas locales eliminadas correctamente."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── ENDPOINTS: HERRAMIENTAS PERIODÍSTICAS ───────────────────────────────────

@app.post("/api/chat")
async def chat_with_transcript(req: ChatRequest):
    client = require_groq(req.groq_api_key)
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="La pregunta está vacía.")
    try:
        answer = await run_blocking(ai.chat_about_transcript, client, req.transcript, req.question)
        return {"answer": answer}
    except Exception as e:
        raise ai_error(e)


@app.post("/api/analyze")
async def analyze_transcript(req: AnalyzeRequest):
    """Modos: summary (resumen), data (datos duros), angle (ángulos), diarization (hablantes)."""
    client = require_groq(req.groq_api_key)
    if req.mode not in ai.JOURNALIST_PROMPTS:
        raise HTTPException(status_code=400, detail=f"Modo inválido. Opciones: {list(ai.JOURNALIST_PROMPTS)}")
    if len(req.transcript.strip()) < 50:
        raise HTTPException(status_code=400, detail="La transcripción es demasiado corta para analizar.")
    try:
        out = await run_blocking(ai.analyze_transcript, client, req.transcript, req.mode)
        return {"result": out["result"], "mode": req.mode, "model_used": out["model_used"], "parts": out["parts"]}
    except Exception as e:
        raise ai_error(e)


@app.post("/api/quotes")
async def extract_quotes_with_times(req: QuotesRequest):
    """Citas textuales con sus tiempos de entrada/salida en el video."""
    client = require_groq(req.groq_api_key)
    if len(req.transcript.strip()) < 50:
        raise HTTPException(status_code=400, detail="La transcripción es demasiado corta.")
    try:
        quotes, parts = await run_blocking(ai.extract_quotes, client, req.transcript)
    except Exception as e:
        raise ai_error(e)
    if not quotes and parts:
        raise HTTPException(status_code=500, detail="No se pudo interpretar la respuesta de la IA. Reintentá.")

    enriched = []
    for item in quotes:
        quote_text = str(item.get("quote", "")).strip()
        search_kw = str(item.get("search") or quote_text[:60]).strip()
        times = find_segment_times_for_quote(search_kw, req.segments) or find_segment_times_for_quote(quote_text, req.segments)
        enriched.append({"quote": quote_text, "note": str(item.get("note", "")).strip(), "search": search_kw,
                         "start": times.get("start"), "end": times.get("end"), "has_time": bool(times)})
    return {"quotes": enriched, "total": len(enriched), "parts": parts}


@app.post("/api/export-docx")
async def export_docx(req: ExportDocxRequest):
    try:
        import docx
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise HTTPException(status_code=500, detail="Falta la librería python-docx. Ejecutá: pip install python-docx")

    def build() -> io.BytesIO:
        doc = docx.Document()
        for section in doc.sections:
            section.top_margin = section.bottom_margin = Inches(1)
            section.left_margin = section.right_margin = Inches(1)
        normal = doc.styles['Normal'].font
        normal.name, normal.size, normal.color.rgb = 'Arial', Pt(11), RGBColor(0x33, 0x41, 0x55)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(12)
        r = p.add_run(req.title)
        r.bold, r.font.size, r.font.color.rgb = True, Pt(18), RGBColor(0x1e, 0x1b, 0x4b)

        if req.uploader or req.url:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(12)
            for label, value in (("Autor/Canal: ", req.uploader), ("Enlace: ", req.url)):
                if value:
                    p.add_run(label).bold = True
                    p.add_run(f"{value}\n")

        if req.description:
            r = doc.add_paragraph().add_run("Descripción / Copy:")
            r.bold, r.font.size = True, Pt(12)
            p = doc.add_paragraph(req.description)
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.space_after = Pt(18)

        sep = doc.add_paragraph("─" * 40)
        sep.alignment = WD_ALIGN_PARAGRAPH.CENTER

        r = doc.add_paragraph().add_run("Transcripción:")
        r.bold, r.font.size, r.font.color.rgb = True, Pt(14), RGBColor(0x4f, 0x46, 0xe5)

        for para in ensure_paragraphs(req.transcript).split("\n\n"):
            para = para.strip()
            if not para:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            if para.startswith("--- ") and para.endswith(" ---"):
                r = p.add_run(para)
                r.bold, r.font.size, r.font.color.rgb = True, Pt(12), RGBColor(0x63, 0x66, 0xf1)
            else:
                # Respetar **negritas** (nombres de hablantes en la diarización)
                for i, piece in enumerate(re.split(r'\*\*(.+?)\*\*', para)):
                    if piece:
                        p.add_run(piece).bold = (i % 2 == 1)
        stream = io.BytesIO()
        doc.save(stream)
        stream.seek(0)
        return stream

    try:
        stream = await run_light(build)
    except Exception as e:
        logger.exception("Error exportando DOCX")
        raise HTTPException(status_code=500, detail=f"No se pudo generar el archivo DOCX: {e}")
    fname = safe_filename(req.title, 60) or "transcripcion"
    return StreamingResponse(
        stream, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={'Content-Disposition': f"attachment; filename=\"transcripcion.docx\"; filename*=UTF-8''{quote(fname)}.docx"})


# ─── TRABAJOS EN SEGUNDO PLANO ───────────────────────────────────────────────
# Una transcripción larga ya no depende de que la pestaña quede abierta: corre en el
# servidor, el resultado se guarda solo en el historial y la app avisa al terminar.

JOBS: dict = {}
JOBS_TTL = 24 * 3600
JOBS_MAX = 100
_job_tasks: set = set()


class JobRequest(BaseModel):
    url: str
    target_lang: Optional[str] = "es"
    groq_api_key: Optional[str] = None
    title: Optional[str] = None
    uploader: Optional[str] = None
    duration: Optional[float] = None


def _job_public(job: dict, with_result: bool = False) -> dict:
    out = {k: v for k, v in job.items() if k not in ("result", "api_key")}
    prog = progress_store.get(job["id"]) or {}
    if job["status"] == "running":
        out["progress"], out["text"] = prog.get("progress", 0), prog.get("text", "Procesando...")
    if with_result and job.get("result") is not None:
        out["result"] = job["result"]
    return out


def _prune_jobs():
    now = time.time()
    for jid in [j for j, job in JOBS.items() if job["status"] in ("done", "error") and now - job["created"] > JOBS_TTL]:
        JOBS.pop(jid, None)
    finished = sorted((j for j in JOBS.values() if j["status"] in ("done", "error")), key=lambda j: j["created"])
    for job in finished[:max(0, len(JOBS) - JOBS_MAX)]:
        JOBS.pop(job["id"], None)


async def _fill_job_metadata(job: dict):
    """Título, autor y duración del video (si no los mandó la app) para el historial."""
    if job.get("title"):
        return
    try:
        url = await resolve_url(job["url"])
        if host_matches(url, INSTAGRAM_DOMAINS) and instaloader:
            ig = await run_light(get_instagram_info, url)
            job.update(title=ig.get("title"), uploader=ig.get("uploader"), duration=ig.get("duration"))
            return
        info = await run_light(ytdlp_extract, url)
        job.update(title=info.get("title"), uploader=info.get("uploader"), duration=info.get("duration"))
    except Exception as e:
        logger.debug(f"No se pudo obtener el título para el trabajo {job['id']}: {e}")


async def _run_job(job: dict):
    job["status"] = "running"
    update_progress(job["id"], 2, "Preparando...")
    try:
        await _fill_job_metadata(job)
        payload = await transcribe_url(job["url"], job["lang"], job.pop("api_key", None), job["id"])
        url = job["url"].strip()
        entry = {"url": url, "platform": job.get("platform") or "", "title": job.get("title") or url,
                 "uploader": job.get("uploader") or "", "duration": job.get("duration"), "lang": job["lang"],
                 "method": payload.get("method"), "transcript": payload["transcript"],
                 "raw_transcript": payload.get("raw_transcript", ""), "srt": payload.get("srt", ""),
                 "segments": payload.get("segments", [])}
        job["history_id"] = await run_light(hist.upsert, DB_FILE, entry)
        job["result"] = {**payload, "history_id": job["history_id"], "title": entry["title"],
                         "uploader": entry["uploader"], "duration": entry["duration"]}
        job["status"] = "done"
        job["title"] = entry["title"]
    except TranscriptionError as e:
        job.update(status="error", error=str(e), technical=e.technical)
    except Exception as e:  # pragma: no cover - red de seguridad
        logger.exception("Error en trabajo en segundo plano")
        job.update(status="error", error=friendly_error(e), technical=str(e)[:400])
    finally:
        job["finished"] = time.time()


@app.post("/api/jobs")
async def create_job(req: JobRequest):
    url = sanitize_url(req.url)
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="La URL debe empezar con http:// o https://")
    _prune_jobs()
    job_id = uuid.uuid4().hex[:16]
    platform = next((name for name, domains in (("youtube", YOUTUBE_DOMAINS), ("instagram", INSTAGRAM_DOMAINS),
                                                 ("tiktok", TIKTOK_DOMAINS), ("redes", TWITTER_DOMAINS + FACEBOOK_DOMAINS))
                     if host_matches(url, domains)), "bunny")
    job = {"id": job_id, "url": req.url.strip(), "lang": req.target_lang or "es", "status": "queued",
           "title": (req.title or "").strip() or None, "uploader": req.uploader, "duration": req.duration,
           "platform": platform, "created": time.time(), "finished": None, "error": None, "history_id": None,
           "api_key": req.groq_api_key}
    JOBS[job_id] = job
    task = asyncio.create_task(_run_job(job))
    _job_tasks.add(task)
    task.add_done_callback(_job_tasks.discard)
    return _job_public(job)


@app.get("/api/jobs")
async def list_jobs():
    _prune_jobs()
    jobs = sorted(JOBS.values(), key=lambda j: j["created"], reverse=True)
    return {"jobs": [_job_public(j) for j in jobs]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="El trabajo no existe (puede haber vencido o el servidor se reinició).")
    return _job_public(job, with_result=True)


@app.delete("/api/jobs/{job_id}")
async def dismiss_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return {"status": "ok"}
    if job["status"] in ("queued", "running"):
        raise HTTPException(status_code=409, detail="El trabajo todavía está corriendo.")
    JOBS.pop(job_id, None)
    return {"status": "ok"}


# ─── HISTORIAL (SQLite) ──────────────────────────────────────────────────────

class HistoryEntry(BaseModel):
    url: str
    platform: Optional[str] = ""
    title: Optional[str] = ""
    uploader: Optional[str] = ""
    duration: Optional[float] = None
    lang: Optional[str] = ""
    method: Optional[str] = ""
    transcript: str = ""
    raw_transcript: Optional[str] = ""
    srt: Optional[str] = ""
    segments: list = []
    date: Optional[str] = None


class HistoryPatch(BaseModel):
    transcript: Optional[str] = None
    title: Optional[str] = None


class HistoryImport(BaseModel):
    items: List[dict] = []


@app.get("/api/history")
async def history_list(q: str = "", limit: int = 200, offset: int = 0):
    return await run_light(hist.list_items, DB_FILE, q, max(1, min(limit, 1000)), max(0, offset))


@app.get("/api/history/{item_id}")
async def history_get(item_id: int):
    item = await run_light(hist.get, DB_FILE, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="La transcripción no existe en el historial.")
    return item


@app.post("/api/history")
async def history_save(entry: HistoryEntry):
    try:
        item_id = await run_light(hist.upsert, DB_FILE, entry.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": item_id}


@app.patch("/api/history/{item_id}")
async def history_update(item_id: int, patch: HistoryPatch):
    if not await run_light(hist.update, DB_FILE, item_id, patch.transcript, patch.title):
        raise HTTPException(status_code=404, detail="La transcripción no existe en el historial.")
    return {"status": "ok"}


@app.delete("/api/history/{item_id}")
async def history_delete(item_id: int):
    await run_light(hist.delete, DB_FILE, item_id)
    return {"status": "ok"}


@app.delete("/api/history")
async def history_clear(request: Request):
    require_admin(request)
    deleted = await run_light(hist.clear, DB_FILE)
    return {"status": "ok", "deleted": deleted}


@app.post("/api/history/import")
async def history_import(data: HistoryImport):
    """Trae el historial viejo que estaba guardado en el navegador."""
    imported = await run_light(hist.import_items, DB_FILE, data.items[:2000])
    return {"imported": imported}


# ─── VISUALIZADOR: VIDEO LIVIANO, FORMA DE ONDA, TRADUCCIÓN ─────────────────

MEDIA_DIR = os.path.join(DATA_DIR, 'media_cache')
MEDIA_MAX_BYTES = int(float(os.environ.get('MEDIA_CACHE_MB', '3000')) * 1024 * 1024)
MEDIA_MAX_AGE = 3 * 24 * 3600
_MEDIA_ID = re.compile(r"[a-f0-9]{16}")
_media_locks: dict = {}
os.makedirs(MEDIA_DIR, exist_ok=True)


class MediaRequest(BaseModel):
    url: str
    uid: Optional[str] = None


def media_id_for(url: str) -> str:
    import hashlib
    return hashlib.sha256(sanitize_url(url).encode()).hexdigest()[:16]


def _media_file(media_id: str) -> Optional[str]:
    if not _MEDIA_ID.fullmatch(media_id or ""):
        return None
    path = os.path.join(MEDIA_DIR, f"{media_id}.mp4")
    return path if os.path.exists(path) else None


def _prune_media_cache(keep: str = ""):
    """Borra los videos del visualizador viejos o si la carpeta pasa del límite."""
    try:
        files = [os.path.join(MEDIA_DIR, f) for f in os.listdir(MEDIA_DIR)]
        files = sorted((f for f in files if os.path.isfile(f)), key=os.path.getmtime)
        now, total = time.time(), sum(os.path.getsize(f) for f in files)
        for f in files:
            if f.startswith(os.path.join(MEDIA_DIR, keep)) and keep:
                continue
            if now - os.path.getmtime(f) > MEDIA_MAX_AGE or total > MEDIA_MAX_BYTES:
                total -= os.path.getsize(f)
                os.remove(f)
    except OSError as e:
        logger.debug(f"Limpieza de media_cache: {e}")


def _download_preview(url: str, media_id: str, uid: Optional[str]) -> str:
    """Baja una copia liviana (hasta 360p, MP4) para reproducir en el visualizador. Bloqueante."""
    final = os.path.join(MEDIA_DIR, f"{media_id}.mp4")
    tmp_prefix = f"{media_id}.dl"

    def done():
        return any(f.startswith(tmp_prefix) and not is_partial_download(f) for f in os.listdir(MEDIA_DIR))

    def cleanup():
        for f in os.listdir(MEDIA_DIR):
            if f.startswith(tmp_prefix):
                try:
                    os.remove(os.path.join(MEDIA_DIR, f))
                except OSError:
                    pass

    if host_matches(url, INSTAGRAM_DOMAINS) and instaloader:
        try:
            ig = get_instagram_info(url)
            if ig.get("video_url"):
                http_download(ig["video_url"], final, {'User-Agent': MOBILE_UA})
                return final
        except Exception as e:
            logger.debug(f"Instaloader falló para el visualizador: {e}")

    def hook(d):
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        if d.get('status') == 'downloading' and total:
            pct = d.get('downloaded_bytes', 0) / total * 100
            update_progress(uid, 10 + int(pct * 0.85), f"Preparando el video: {pct:.0f}%")

    fmt = ("b[height<=360][ext=mp4]/bv*[height<=360][ext=mp4]+ba[ext=m4a]/bv*[height<=360]+ba/b[height<=480]/b"
           if HAS_FFMPEG else "b[height<=480][ext=mp4]/b[ext=mp4]/b")
    extra = {'format': fmt, 'outtmpl': os.path.join(MEDIA_DIR, f"{tmp_prefix}.%(ext)s"), 'progress_hooks': [hook]}
    if HAS_FFMPEG:
        extra['merge_output_format'] = 'mp4'
    ytdlp_download(url, extra, done, cleanup=cleanup)
    produced = next(os.path.join(MEDIA_DIR, f) for f in os.listdir(MEDIA_DIR)
                    if f.startswith(tmp_prefix) and not is_partial_download(f))
    if not produced.endswith(".mp4") and HAS_FFMPEG:
        media.run_ffmpeg(['-i', produced, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-c:a', 'aac',
                          '-movflags', '+faststart', final])
        os.remove(produced)
    else:
        os.replace(produced, final)
    return final


@app.post("/api/media/prepare")
async def media_prepare(req: MediaRequest):
    """Deja listo un video liviano para el visualizador y devuelve su id."""
    url = await resolve_url(req.url)
    media_id = media_id_for(url)
    if _media_file(media_id):
        os.utime(os.path.join(MEDIA_DIR, f"{media_id}.mp4"))
        return {"id": media_id, "url": f"/api/media/{media_id}"}
    lock = _media_locks.setdefault(media_id, asyncio.Lock())
    async with lock:
        if not _media_file(media_id):
            update_progress(req.uid, 5, "Preparando el video para verlo...")
            await run_light(_prune_media_cache, media_id)
            try:
                await run_blocking(_download_preview, url, media_id, req.uid)
            except Exception as e:
                logger.warning(f"No se pudo preparar el video del visualizador: {e}")
                raise HTTPException(status_code=500, detail=friendly_error(e))
    update_progress(req.uid, 100, "Video listo")
    return {"id": media_id, "url": f"/api/media/{media_id}"}


def parse_range(header: str, size: int):
    """'bytes=100-199' → (100, 199). None si no hay rango válido."""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not m or (not m.group(1) and not m.group(2)):
        return None
    if m.group(1):
        start = int(m.group(1))
        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    else:  # sufijo: los últimos N bytes
        start, end = max(0, size - int(m.group(2))), size - 1
    if start > end or start >= size:
        return None
    return start, end


@app.get("/api/media/{media_id}")
async def media_serve(media_id: str, request: Request):
    """Video del visualizador, con soporte de Range (para poder saltar a cualquier minuto)."""
    path = _media_file(media_id)
    if not path:
        raise HTTPException(status_code=404, detail="El video ya no está disponible: preparalo de nuevo.")
    size = os.path.getsize(path)
    rng = parse_range(request.headers.get("range", ""), size)
    if not rng:
        return FileResponse(path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})
    start, end = rng

    def chunks():
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                data = f.read(min(1024 * 1024, left))
                if not data:
                    break
                left -= len(data)
                yield data
    return StreamingResponse(chunks(), status_code=206, media_type="video/mp4", headers={
        "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1)})


def compute_peaks(path: str, buckets: int = 1600) -> list:
    """Forma de onda: el volumen máximo de cada tramo, de 0 a 100. Bloqueante."""
    from array import array
    cmd = [FFMPEG_BIN or 'ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', path, '-vn', '-ac', '1',
           '-ar', '1000', '-f', 's16le', '-']
    res = subprocess.run(cmd, capture_output=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg falló: {res.stderr.decode(errors='replace')[-300:]}")
    samples = array('h')
    samples.frombytes(res.stdout[:len(res.stdout) // 2 * 2])
    if not samples:
        return []
    step = max(1, len(samples) // buckets)
    peaks = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i + step]
        peaks.append(max(max(chunk), -min(chunk)))
    top = max(peaks) or 1
    return [round(p * 100 / top) for p in peaks]


@app.get("/api/media/{media_id}/peaks")
async def media_peaks(media_id: str):
    path = _media_file(media_id)
    if not path:
        raise HTTPException(status_code=404, detail="El video ya no está disponible.")
    if not HAS_FFMPEG:
        return {"peaks": []}
    cache = path + ".peaks.json"
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            return {"peaks": json.load(f)}
    try:
        peaks = await run_blocking(compute_peaks, path)
    except Exception as e:
        logger.warning(f"No se pudo calcular la forma de onda: {e}")
        return {"peaks": []}
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(peaks, f)
    return {"peaks": peaks}


class TranslateSegmentsRequest(BaseModel):
    texts: List[str]
    target: str = "es"


@app.post("/api/translate-segments")
async def translate_segments(req: TranslateSegmentsRequest):
    """Traduce frase por frase (mantiene la relación con los tiempos para la vista bilingüe)."""
    if req.target not in ("es", "en", "pt", "fr", "it", "de"):
        raise HTTPException(status_code=400, detail="Idioma no soportado.")
    if len(req.texts) > 6000:
        raise HTTPException(status_code=400, detail="Demasiados segmentos para traducir de una vez.")
    try:
        texts = await run_blocking(ai.translate_texts, list(req.texts), req.target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=friendly_error(e))
    return {"texts": texts}


# ─── RECORTES: SUBTÍTULOS QUEMADOS Y FORMATO VERTICAL ───────────────────────

VERTICAL_FILTER = ("crop='min(iw,ih*9/16)':ih,scale=1080:1920:force_original_aspect_ratio=decrease,"
                   "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
SUBTITLE_STYLE = ("FontName=Arial,FontSize={size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                  "BorderStyle=1,Outline=2,Shadow=0,MarginV={margin},Alignment=2")


def postprocess_clip(path: str, segments: list, clip_start: float, clip_end: float,
                     burn_subs: bool, vertical: bool) -> str:
    """
    Quema los subtítulos del tramo y/o lo pasa a vertical 9:16 (para redes). Bloqueante.
    Devuelve la ruta del archivo nuevo (borra el original).
    """
    if not (burn_subs or vertical):
        return path
    if not HAS_FFMPEG:
        raise RuntimeError("Hace falta FFmpeg para quemar subtítulos o pasar a vertical.")
    filters = []
    with tempfile.TemporaryDirectory() as tmp:
        if vertical:
            filters.append(VERTICAL_FILTER)
        if burn_subs:
            subs = clip_segments(segments or [], clip_start, clip_end)
            if subs:
                with open(os.path.join(tmp, "subs.srt"), "w", encoding="utf-8") as f:
                    f.write(generate_srt_from_segments(subs))
                # Medidas sobre la resolución interna de los subtítulos (288 de alto), no en píxeles:
                # margen 40 ≈ 14 % desde abajo (deja lugar a la interfaz de TikTok / Reels).
                style = SUBTITLE_STYLE.format(size=13 if vertical else 18, margin=40 if vertical else 16)
                # Ruta relativa (cwd=tmp): las rutas de Windows rompen la sintaxis de filtros de FFmpeg
                filters.append(f"subtitles=subs.srt:charenc=UTF-8:force_style='{style}'")
        if not filters:
            return path
        root, _ = os.path.splitext(path)
        out = f"{root}_final.mp4"
        cmd = [FFMPEG_BIN or 'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', path,
               '-vf', ",".join(filters), *TRIM_FFMPEG_ARGS, out]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp, timeout=3600)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg falló: {res.stderr.strip()[-400:]}")
    os.remove(path)
    return out


@app.post("/api/clip-file")
async def clip_uploaded_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    start: float = Form(...),
    end: float = Form(...),
    burn_subs: bool = Form(default=False),
    vertical: bool = Form(default=False),
    segments: str = Form(default="[]"),
):
    """Recorta un video subido desde la PC (el visualizador de archivos propios)."""
    if not HAS_FFMPEG:
        raise HTTPException(status_code=400, detail="Para recortar hace falta FFmpeg.")
    if end <= start or start < 0:
        raise HTTPException(status_code=400, detail="Rango de tiempo inválido.")
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Formato no soportado: '{ext}'.")
    try:
        segs = json.loads(segments or "[]")
    except ValueError:
        segs = []
    file_uid = uuid.uuid4().hex
    src = os.path.join(DOWNLOAD_FOLDER, f"clipsrc_{file_uid}{ext}")
    is_video = ext in VIDEO_EXTS
    out = os.path.join(DOWNLOAD_FOLDER, f"clip_{file_uid}.{'mp4' if is_video else 'mp3'}")
    _remove_later(background_tasks, src, out)
    await save_upload(file, src, MAX_UPLOAD_MB)
    codec = TRIM_FFMPEG_ARGS if is_video else ['-vn', '-c:a', 'libmp3lame', '-q:a', '2']
    try:
        await run_blocking(media.run_ffmpeg, ['-ss', str(start), '-to', str(end), '-i', src, *codec, out])
        final = out
        if is_video and (burn_subs or vertical):
            final = await run_blocking(postprocess_clip, out, segs, start, end, burn_subs, vertical)
            _remove_later(background_tasks, final)
    except Exception as e:
        raise HTTPException(status_code=500, detail=friendly_error(e))
    base = safe_filename(os.path.splitext(file.filename or 'clip')[0], 40)
    name = f"{base}_{int(start)}s-{int(end)}s{'_vertical' if vertical else ''}.{'mp4' if is_video else 'mp3'}"
    return FileResponse(final, filename=name)


# ─── ENDPOINTS: MANTENIMIENTO ────────────────────────────────────────────────

def _pip_install_requirements() -> tuple:
    req_file = os.path.join(BASE_DIR, 'requirements.txt')
    res = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', req_file],
                         capture_output=True, text=True, timeout=900)
    return res.returncode == 0, (res.stderr or res.stdout).strip()[-500:]


GITHUB_REPO = os.environ.get('CLIPADSK_REPO', 'psherrera/clipadsk')
GITHUB_BRANCH = os.environ.get('CLIPADSK_BRANCH', 'main')
# Nunca se pisan al actualizar (datos y configuración del usuario)
UPDATE_SKIP = {'.env', 'cookies.txt', 'cookies_ig.txt', '.git'}
UPDATE_SKIP_DIRS = {os.path.join('backend', 'venv'), os.path.join('backend', 'downloads'), os.path.join('backend', 'model'),
                    os.path.join('backend', 'media_cache')}


def _update_from_zip(root: str) -> tuple:
    """Actualiza descargando el ZIP de GitHub (instalaciones sin git). Devuelve (archivos cambiados, error)."""
    import hashlib
    url = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, 'app.zip')
        try:
            http_download(url, zip_path, {'User-Agent': 'Clipadsk-Updater'}, timeout=120)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
        except Exception as e:
            return 0, f"No se pudo descargar la actualización de GitHub: {e}"
        tops = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
        if not tops or not os.path.exists(os.path.join(tmp, tops[0], 'backend', 'main.py')):
            return 0, "El ZIP descargado no tiene el formato esperado."
        src_root = os.path.join(tmp, tops[0])

        def digest(path):
            with open(path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()

        changed = 0
        for dirpath, dirnames, filenames in os.walk(src_root):
            rel_dir = os.path.relpath(dirpath, src_root)
            rel_dir = '' if rel_dir == '.' else rel_dir
            dirnames[:] = [d for d in dirnames if os.path.join(rel_dir, d) not in UPDATE_SKIP_DIRS and d != '.git']
            for name in filenames:
                rel = os.path.join(rel_dir, name)
                if name in UPDATE_SKIP and rel_dir == '':
                    continue
                src, dst = os.path.join(dirpath, name), os.path.join(root, rel)
                if os.path.exists(dst) and digest(dst) == digest(src):
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                changed += 1
        return changed, None


def _git(repo: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=repo, timeout=300)


def _update_with_git(repo: str) -> tuple:
    """
    git pull. Si hay cambios locales en archivos de la app (versiones viejas modificaban
    yt-dlp.exe al "Actualizar motor"), se guardan con git stash y se reintenta.
    Devuelve (hubo_cambios, salida, error).
    """
    try:
        res = _git(repo, "pull", "--ff-only", "origin", GITHUB_BRANCH)
        if res.returncode != 0:
            logger.info(f"git pull falló, se reintenta con stash: {res.stderr.strip()[-300:]}")
            _git(repo, "stash", "push", "-m", f"clipadsk-actualizar {time.strftime('%Y-%m-%d %H:%M')}")
            res = _git(repo, "pull", "--ff-only", "origin", GITHUB_BRANCH)
    except Exception as e:
        return False, "", str(e)
    out = res.stdout.strip()
    if res.returncode != 0:
        return False, out, f"git pull salió con código {res.returncode}: {res.stderr.strip()[-400:]}"
    return not ("Already up to date" in out or "Ya está actualizado" in out), out, None


FROZEN_UPDATE_MSG = ("Este Clipa.exe trae el programa adentro y no se puede actualizar desde la app. "
                     "Instalá Clipadsk en la carpeta (INSTALAR.bat) para que el exe use esa instalación, "
                     "o generá un exe nuevo con CREAR_EXE.bat.")


def _update_app() -> dict:
    if getattr(sys, 'frozen', False):
        return {"error": FROZEN_UPDATE_MSG}
    protected = [os.path.join(d, n) for d in (ROOT_DIR, BASE_DIR) for n in (".env", "cookies.txt", "cookies_ig.txt")]
    backups = {}
    for path in protected:
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    backups[path] = f.read()
            except OSError as e:
                logger.warning(f"No se pudo respaldar {path}: {e}")

    repo = os.environ.get('GIT_REPO_DIR', ROOT_DIR)
    use_git = os.path.isdir(os.path.join(repo, '.git')) and shutil.which('git')
    try:
        if use_git:
            changed, output, error = _update_with_git(repo)
            if error:  # último recurso: bajar el ZIP de GitHub y copiarlo encima
                logger.warning(f"Actualización con git falló ({error}); se usa el ZIP de GitHub")
                n, error = _update_from_zip(ROOT_DIR)
                changed, output = n > 0, f"{n} archivos actualizados desde GitHub (ZIP)"
        else:
            n, error = _update_from_zip(ROOT_DIR)
            changed, output = n > 0, f"{n} archivos actualizados desde GitHub"
    finally:
        for path, content in backups.items():
            try:
                with open(path, "wb") as f:
                    f.write(content)
            except OSError as e:
                logger.warning(f"No se pudo restaurar {path}: {e}")

    if error:
        return {"error": f"Error al actualizar: {error}"}
    if not changed:
        return {"status": "ok", "message": "La aplicación ya está actualizada. No hay cambios nuevos.", "output": output}

    ok, pip_out = _pip_install_requirements()
    msg = "✅ Aplicación actualizada. Cerrá y volvé a abrir Clipadsk para aplicar los cambios."
    if not ok:
        msg += f" ⚠️ No se pudieron instalar algunas dependencias: {pip_out}"
    return {"status": "ok", "message": msg, "output": output}


@app.post("/api/system/update-app")
async def update_app(request: Request):
    """git pull + reinstalar dependencias, protegiendo .env y cookies."""
    require_admin(request)
    result = await run_light(_update_app)
    if "error" in result:
        return JSONResponse(status_code=500, content=result)
    return result


def _update_engine() -> dict:
    if getattr(sys, 'frozen', False):
        return {"error": FROZEN_UPDATE_MSG}
    # El backend usa el paquete de Python yt_dlp, así que se actualiza ese (y el .exe si existe)
    res = subprocess.run([sys.executable, '-m', 'pip', 'install', '-U', '-q', 'yt-dlp[default]'],
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        return {"error": f"Error al actualizar motor: {(res.stderr or res.stdout)[-400:]}"}
    exe = os.path.join(ROOT_DIR, "yt-dlp.exe")
    if os.path.exists(exe):
        try:
            subprocess.run([exe, "-U"], capture_output=True, text=True, timeout=300)
        except Exception as e:
            logger.warning(f"No se pudo actualizar yt-dlp.exe: {e}")
    version = subprocess.run([sys.executable, '-m', 'yt_dlp', '--version'], capture_output=True, text=True).stdout.strip()
    return {"status": "ok",
            "message": f"Motor de descarga actualizado (yt-dlp {version}). Reiniciá Clipadsk para usar la nueva versión.",
            "output": version}


@app.post("/api/system/update-engine")
async def update_engine(request: Request):
    require_admin(request)
    result = await run_light(_update_engine)
    if "error" in result:
        return JSONResponse(status_code=500, content=result)
    return result


@app.post("/api/system/reset")
async def reset_system(request: Request):
    """Borra descargas y la caché de transcripciones."""
    require_admin(request)

    def reset():
        shutil.rmtree(DOWNLOAD_FOLDER, ignore_errors=True)
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
        shutil.rmtree(MEDIA_DIR, ignore_errors=True)   # copias livianas del visualizador
        os.makedirs(MEDIA_DIR, exist_ok=True)
        with db_connect() as conn:
            conn.execute("DELETE FROM transcripts")
    try:
        await run_light(reset)
        return {"status": "ok", "message": "Sistema reseteado (descargas y caché limpias)."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ─── FRONTEND (debe ir al final para no tapar las rutas /api) ────────────────
if os.path.exists(FRONTEND_DIR):
    FRONTEND_ROOT = Path(FRONTEND_DIR).resolve()
    INDEX_HTML = FRONTEND_ROOT / 'index.html'

    @app.head("/", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(INDEX_HTML)

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_static_or_index(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Endpoint no encontrado")
        try:
            resolved = (FRONTEND_ROOT / path).resolve()
            if FRONTEND_ROOT in resolved.parents and resolved.is_file():
                return FileResponse(resolved)
        except Exception as e:
            logger.debug(f"Error resolviendo ruta estática: {e}")
        return FileResponse(INDEX_HTML)  # rutas de la SPA
else:
    logger.warning(f"No se encontró la carpeta frontend en {FRONTEND_DIR}")


if __name__ == "__main__":
    import uvicorn
    if not IS_LOCAL_ONLY and not ADMIN_TOKEN:
        logger.warning(f"Escuchando en {HOST}: otras PCs pueden usar Clipadsk (descargas, transcripción y tu key de Groq). "
                       "El mantenimiento queda bloqueado hasta definir ADMIN_TOKEN en .env.")
    if os.environ.get('APP_PASSWORD'):
        logger.warning("APP_PASSWORD está en .env pero Clipadsk no lo usa: NO protege la app. "
                       "Para restringir el acceso mantené HOST=127.0.0.1 o poné un proxy con contraseña delante.")
    logger.info(f"Clipadsk en http://{'127.0.0.1' if HOST == '0.0.0.0' else HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, timeout_keep_alive=600)
