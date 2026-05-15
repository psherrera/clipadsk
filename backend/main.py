"""
YT Downloader Pro - Backend
Optimized for Render.com deployment.
Features: 
- Heavy dependency removal (Whisper/Torch).
- Groq API & YouTube Subtitle fallback for transcription.
- Robust Bot-Evasion strategy using mobile client emulation.
- Automated cleanup of downloaded files.
"""
import os
import uuid
import json
import gc
import re
import tempfile
import yt_dlp
import requests
from typing import Optional, List
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
try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None

try:
    import instaloader
except ImportError:
    instaloader = None

from dotenv import load_dotenv

# --- CONFIGURACIÓN DE ENTORNO ---
load_dotenv() # Cargar variables desde .env
IS_RENDER = os.environ.get('RENDER') is not None
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except ImportError:
    groq_client = None

app = FastAPI(title="YT Downloader Pro API")

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MIDDLEWARE DE LOGGING ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Logeamos solo peticiones a la API para no saturar con estáticos
    if request.url.path.startswith("/api/"):
        print(f"DEBUG API: {request.method} {request.url.path}")
    response = await call_next(request)
    return response

# --- CONFIGURACIÓN DE RUTAS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Si se provee FRONTEND_DIR por env (Docker/Render), la usamos prioritariamente
FRONTEND_DIR = os.environ.get('FRONTEND_DIR')

# Fallback local: El ROOT_DIR del proyecto Pro es el padre de backend/
ROOT_DIR = os.path.dirname(BASE_DIR)

if not FRONTEND_DIR:
    FRONTEND_DIR = os.path.join(ROOT_DIR, 'frontend')

DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')
CACHE_FILE = os.path.join(BASE_DIR, 'transcripts_cache.json')

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# --- ROBUSTEZ FFMPEG ---
ffmpeg_extra_paths = [
    ROOT_DIR,
    os.path.join(ROOT_DIR, 'bin'),
    r'C:\Program Files\Red Giant\Trapcode Suite\Tools',
    r'C:\Program Files\SnapDownloader\resources\win',
]
current_path = os.environ.get("PATH", "")
nuevo_path = current_path
for p in ffmpeg_extra_paths:
    if os.path.exists(p) and p not in nuevo_path:
        nuevo_path = p + os.pathsep + nuevo_path
os.environ["PATH"] = nuevo_path

# --- CACHÉ ---

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

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
        print(f"Error traducción: {e}")
        return text

def cleanup_transcript_with_ai(text: str) -> str:
    """Usa la IA para limpiar repeticiones, corregir puntuación y añadir párrafos."""
    if not groq_client or len(text) < 100:
        return text
    
    try:
        # Truncar si es absurdamente largo para la limpieza
        safe_text = text[:8000] if len(text) > 8000 else text
        
        prompt = f"""
        Sos un editor experto. Tu tarea es LIMPIAR y FORMATEAR la siguiente transcripción de un video.
        
        INSTRUCCIONES:
        1. ELIMINÁ repeticiones de frases (a veces el sistema de transcripción repite lo mismo varias veces por error).
        2. AGREGÁ puntuación correcta (comas, puntos).
        3. DIVIDÍ el texto en párrafos lógicos (usá DOBLE SALTO DE LÍNEA entre párrafos) para que el texto sea legible.
        4. No resumas, mantené el contenido original pero bien escrito.
        5. Respondé SOLO con el texto limpio.
        
        TRANSCRIPCIÓN A LIMPIAR:
        {safe_text}
        """
        
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2048,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error limpiando transcripción: {e}")
        return text

# --- MODELOS DE DATOS ---
class VideoRequest(BaseModel):
    url: str
    format_id: Optional[str] = "best"
    start_time: Optional[str] = None
    end_time: Optional[str] = None

# --- ENDPOINTS ---


# --- UNIFIED ROBUST OPTIONS (COOKIES & CLIENTS) ---
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
        local_paths = ['/etc/secrets/cookies_ig.txt', ig_cookie_path]
    else:
        cookie_b64 = os.environ.get('COOKIES_B64')
        local_paths = ['/etc/secrets/cookies.txt', cookie_path]

    # Cargar cookies desde variable de entorno
    if cookie_b64:
        try:
            cookie_data = base64.b64decode(cookie_b64).decode()
            temp_cookie = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
            temp_cookie.write(cookie_data)
            temp_cookie.close()
            opts['cookiefile'] = temp_cookie.name
            platform = 'Instagram' if is_instagram else 'YouTube'
            print(f"DEBUG: Cargando cookies [{platform}] desde variable de entorno (Temp: {temp_cookie.name})")
        except Exception as e:
            print(f"DEBUG: Error cargando cookies: {e}")

    # Fallback a archivo local
    if 'cookiefile' not in opts:
        for path_candidate in local_paths:
            if os.path.exists(path_candidate):
                print(f"DEBUG: Cargando cookies desde archivo {path_candidate}")
                opts['cookiefile'] = path_candidate
                break

    # Estrategia específica por plataforma
    if is_youtube:
        # Dejamos que yt-dlp use sus clientes por defecto (web, tv, etc.) para que encuentre todas las calidades (1080p, 720p)
        opts['user_agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1'
        print(f"DEBUG: Estrategia YouTube optimizada (Cookies: {'Si' if 'cookiefile' in opts else 'No'})")

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
            print(f"DEBUG: Instaloader login OK como {ig_user}")
        except Exception as e:
            print(f"DEBUG: Instaloader login falló: {e}")

    match = re.search(r'/(reel|p|tv)/([A-Za-z0-9_-]+)', url)
    if not match:
        raise Exception("No se pudo extraer el shortcode del URL de Instagram")

    shortcode = match.group(2)
    print(f"DEBUG: Instaloader extrayendo shortcode: {shortcode}")

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

# --- ENDPOINTS ---

@app.post("/api/video-info")
async def get_video_info(req: VideoRequest, request: Request):
    url = req.url
    is_instagram = 'instagram.com' in url

    # --- INSTAGRAM: usar instaloader ---
    if is_instagram and instaloader:
        try:
            ig_info = await asyncio.to_thread(get_instagram_info, url)
            if ig_info['is_video']:
                formats = [{'format_id': 'best', 'ext': 'mp4', 'resolution': 'Mejor calidad', 'filesize': None, 'label': 'Mejor calidad (.mp4)'}]
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
            print(f"DEBUG: Instaloader falló, intentando con yt-dlp: {e}")

    is_youtube = 'youtube.com' in url or 'youtu.be' in url

    info = None
    last_error = ""
    
    # --- INTENTO 1: Estrategia Optimizada (Basada en get_robust_opts) ---
    try:
        print("DEBUG: Intento 1 - Estrategia optimizada...")
        opts = get_robust_opts(url)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        last_error = str(e)
        print(f"DEBUG: Intento 1 falló: {last_error[:100]}")

    # --- INTENTO 2: Forzar Móvil SIN COOKIES (Para saltar n-challenge) ---
    if not info and is_youtube:
        try:
            print("DEBUG: Intento 2 - Forzando móvil SIN cookies...")
            opts = get_robust_opts(url)
            opts.pop('cookiefile', None) # Quitamos cookies para que no las ignore
            opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios']}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            last_error += f" | Intento 2: {str(e)[:100]}"
            print(f"DEBUG: Intento 2 falló: {str(e)[:100]}")

    # --- INTENTO 3: Forzar iOS (Último recurso) ---
    if not info and is_youtube:
        try:
            print("DEBUG: Intento 3 - Forzando solo iOS...")
            opts = get_robust_opts(url)
            opts.pop('cookiefile', None)
            opts['extractor_args'] = {'youtube': {'player_client': ['ios']}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            last_error += f" | Intento 3: {str(e)[:100]}"
            print(f"DEBUG: Intento 3 falló: {str(e)[:100]}")

    if not info:
        print(f"DEBUG: EXTRACT_INFO FAILED for {url}.")
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
        res = f.get('resolution') or f"{f.get('height')}p"
        if res == "Nonep" or not f.get('height'):
            res = f.get('format_note') or f.get('format_id') or "Calidad única"
        
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

    # Proxy para miniaturas de Instagram
    # Se añade encoding y el prefijo /api/ para resolver problemas de carga en el frontend
    thumbnail = info.get('thumbnail')
    if 'instagram.com' in url and thumbnail:
        from urllib.parse import quote
        thumbnail = f"/api/proxy-thumbnail?url={quote(thumbnail, safe='')}"
        print(f"DEBUG: Instagram Thumbnail proxied (with encoding): {thumbnail}")

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

@app.post("/api/transcript")
async def get_transcript(req: VideoRequest):
    url = req.url
    is_youtube = 'youtube.com' in url or 'youtu.be' in url
    cache = load_cache()
    if url in cache:
        return {"transcript": cache[url], "method": "cache"}

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            if is_youtube:
                # --- INTENTO DE SUBS CON 3 ESTRATEGIAS ---
                sub_extracted = False
                
                # 1. Celular sin cookies
                try:
                    opts = get_robust_opts(url, {'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 'subtitleslangs': ['es.*', 'en.*'], 'outtmpl': os.path.join(tmpdir, 'sub.%(ext)s')})
                    opts.pop('cookiefile', None)
                    opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios']}}
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                        sub_extracted = True
                except: pass

                # 2. Con cookies
                if not sub_extracted:
                    try:
                        opts = get_robust_opts(url, {'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True, 'subtitleslangs': ['es.*', 'en.*'], 'outtmpl': os.path.join(tmpdir, 'sub.%(ext)s')})
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            ydl.download([url])
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
                        content = f.read()
                    content = re.sub(r'WEBVTT.*?\n\n', '', content, flags=re.DOTALL)
                    content = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}.*?\n', '', content)
                    content = re.sub(r'^\d+\n', '', content, flags=re.MULTILINE)
                    content = re.sub(r'<[^>]*>', '', content)
                    final_text = ' '.join([line.strip() for line in content.split('\n') if line.strip()])
                    if is_english: final_text = translate_to_spanish(final_text)
                    
                    # Limpieza con IA opcional para mejorar legibilidad
                    final_text = cleanup_transcript_with_ai(final_text)
                    
                    cache[url] = final_text
                    save_cache(cache)
                    return {"transcript": final_text, "method": "subtitles"}

            raise Exception("No direct subtitles")

        except Exception:
            # 2. Descargar audio y usar Whisper con 3 estrategias
            audio_downloaded = False
            audio_file = None
            
            # Estrategia 1: Móvil sin cookies
            try:
                audio_opts = get_robust_opts(url, {'format': 'bestaudio/best', 'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'), 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '64'}]})
                audio_opts.pop('cookiefile', None)
                audio_opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios']}}
                with yt_dlp.YoutubeDL(audio_opts) as ydl:
                    ydl.download([url])
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
                    with yt_dlp.YoutubeDL(audio_opts) as ydl:
                        ydl.download([url])
                        for f in os.listdir(tmpdir):
                            if f.startswith('audio.'):
                                audio_file = os.path.join(tmpdir, f)
                                audio_downloaded = True
                                break
                except: pass

            if audio_downloaded and audio_file:
                # 2.1 Intentar con Groq API (Más rápido y ligero)
                if groq_client:
                    try:
                        file_size_mb = os.path.getsize(audio_file) / (1024 * 1024)
                        transcription = ""
                        if AudioSegment:
                            # Lógica de troceado si es necesario
                            if file_size_mb >= 20:
                                print(f"Dividiendo audio de {file_size_mb:.1f}MB en partes de 20 min...")
                                audio = AudioSegment.from_file(audio_file)
                                chunk_length_ms = 20 * 60 * 1000 # 20 minutos por trozo
                                chunks = []
                                for i in range(0, len(audio), chunk_length_ms):
                                    chunks.append(audio[i:i + chunk_length_ms])
                                
                                for idx, chunk in enumerate(chunks):
                                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as c_file:
                                        chunk.export(c_file.name, format="mp3", bitrate="64k")
                                        print(f"Transcribiendo parte {idx+1}/{len(chunks)}...")
                                        with open(c_file.name, "rb") as f:
                                            part_text = groq_client.audio.transcriptions.create(
                                                file=(c_file.name, f.read()),
                                                model="whisper-large-v3",
                                                response_format="text",
                                                language="es"
                                            )
                                            transcription += part_text + " "
                                        os.remove(c_file.name)
                            else:
                                with open(audio_file, "rb") as f:
                                    transcription = groq_client.audio.transcriptions.create(
                                        file=(audio_file, f.read()),
                                        model="whisper-large-v3",
                                        response_format="text",
                                        language="es"
                                    )
                        else:
                            # Fallback sin pydub (solo si file < 25MB)
                            with open(audio_file, "rb") as f:
                                transcription = groq_client.audio.transcriptions.create(
                                    file=(audio_file, f.read()),
                                    model="whisper-large-v3",
                                    response_format="text",
                                    language="es"
                                )
                        
                        # Limpieza con IA
                        transcription = cleanup_transcript_with_ai(transcription.strip())
                        
                        cache[url] = transcription
                        save_cache(cache)
                        return {"transcript": transcription, "method": "groq_whisper_v3"}
                    except Exception as ge:
                        print(f"Error en Groq: {ge}")
                        raise Exception(f"Error en Groq API: {str(ge)}")

                raise Exception("Groq API no configurada y no se encontraron subtítulos.")

            raise Exception("No se pudo descargar el audio para la transcripción por ningún medio.")
        except Exception as final_e:
            return JSONResponse(status_code=500, content={"error": str(final_e)})


class ChatRequest(BaseModel):
    url: str
    question: str
    transcript: str

@app.post("/api/chat")
async def chat_with_transcript(req: ChatRequest):
    if not groq_client:
        raise HTTPException(status_code=500, detail="Groq API no configurada")
    
    # --- RECORTE DE SEGURIDAD PARA RATE LIMITS (6000 TPM) ---
    # Si la transcripcion es muy larga, la recortamos para que quepa en el limite gratuito de Groq.
    # 20,000 caracteres son aprox 5,000 tokens, lo que deja margen para la respuesta.
    transcript_safe = req.transcript
    if len(transcript_safe) > 12000:
        print(f"Aviso: Transcripcion muy larga ({len(transcript_safe)} chars). Recortando para evitar error 413.")
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
        
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.question}
            ],
            temperature=0.7,
            max_tokens=1024,
        )
        
        return {"answer": completion.choices[0].message.content}
    except Exception as e:
        print(f"Error en Chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/download")
async def download_video(req: VideoRequest, background_tasks: BackgroundTasks):
    url = req.url
    format_id = req.format_id
    uid = str(uuid.uuid4())

    # --- INSTAGRAM: usar instaloader para descarga ---
    if 'instagram.com' in url and instaloader:
        try:
            ig_info = await asyncio.to_thread(get_instagram_info, url)
            if not ig_info['is_video']:
                raise HTTPException(status_code=400, detail="Este post de Instagram no tiene video.")

            video_url = ig_info['video_url']
            headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15'}
            r = requests.get(video_url, headers=headers, stream=True, timeout=60)
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
            print(f"DEBUG: Instaloader download falló, intentando con yt-dlp: {e}")

    output_template = os.path.join(DOWNLOAD_FOLDER, f'%(title)s_{uid}.%(ext)s')
    
    if format_id and format_id not in ('best', 'bestvideo+bestaudio', None):
        fmt = f"{format_id}/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    else:
        fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'

    extra_opts = {
        'format': fmt,
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
    }

    if req.start_time or req.end_time:
        from yt_dlp.utils import parse_duration, download_range_func
        start_sec = parse_duration(req.start_time) if req.start_time else 0
        end_sec = parse_duration(req.end_time) if req.end_time else float('inf')
        extra_opts['download_ranges'] = download_range_func(None, [(start_sec, end_sec)])
        extra_opts['force_keyframes_at_cuts'] = True

    # Intentar descarga con 3 estrategias
    downloaded = False
    last_err = ""

    # --- ESTRATEGIA 1: Celular sin cookies (La que funcionó para info) ---
    try:
        print("DEBUG: Descarga Intento 1 - Celular sin cookies...")
        opts = get_robust_opts(url, extra_opts)
        opts.pop('cookiefile', None)
        opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios']}}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
            downloaded = True
    except Exception as e:
        last_err = str(e)
        print(f"DEBUG: Descarga Intento 1 falló: {last_err[:100]}")

    # --- ESTRATEGIA 2: Navegador con Cookies ---
    if not downloaded:
        try:
            print("DEBUG: Descarga Intento 2 - Con cookies...")
            opts = get_robust_opts(url, extra_opts)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
                downloaded = True
        except Exception as e:
            last_err += f" | Intento 2: {str(e)[:100]}"
            print(f"DEBUG: Descarga Intento 2 falló: {str(e)[:100]}")

    # --- ESTRATEGIA 3: Forzar iOS ---
    if not downloaded:
        try:
            print("DEBUG: Descarga Intento 3 - Forzando iOS...")
            opts = get_robust_opts(url, extra_opts)
            opts.pop('cookiefile', None)
            opts['extractor_args'] = {'youtube': {'player_client': ['ios']}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
                downloaded = True
        except Exception as e:
            last_err += f" | Intento 3: {str(e)[:100]}"
            print(f"DEBUG: Descarga Intento 3 falló: {str(e)[:100]}")

    if downloaded:
        # Encontrar archivo
        for f in os.listdir(DOWNLOAD_FOLDER):
            if uid in f:
                file_path = os.path.join(DOWNLOAD_FOLDER, f)
                def remove_file(path: str):
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                            print(f"DEBUG: Archivo borrado: {file_path}")
                    except Exception as e:
                        print(f"Error borrando archivo: {e}")
                
                background_tasks.add_task(remove_file, file_path)
                return FileResponse(file_path, filename=f)
        raise Exception("Archivo no encontrado tras descarga exitosa")
    else:
        raise HTTPException(status_code=500, detail=f"No se pudo descargar: {last_err[:200]}")

@app.get("/api/proxy-thumbnail")
async def proxy_thumbnail(url: str):
    print(f"DEBUG: Proxy request for: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Referer': 'https://www.instagram.com/'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        print(f"DEBUG: Proxy success, Content-Type: {resp.headers.get('Content-Type')}")
        return Response(content=resp.content, media_type=resp.headers.get('Content-Type', 'image/jpeg'))
    except Exception as e:
        print(f"DEBUG: Proxy FAILED: {e}")
        return Response(status_code=500)

# --- HEALTHCHECKS ---
@app.get("/api/health/cookies")
async def check_cookies():
    """Verifica si las cookies actuales siguen siendo válidas con un video de prueba."""
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    try:
        def get_info():
            opts = get_robust_opts(test_url)
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(test_url, download=False)
        
        # Ejecutamos en un thread pool para no bloquear el loop de FastAPI
        info = await asyncio.to_thread(get_info)
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

ALLOWED_AUDIO_EXTENSIONS = {'.ogg', '.opus', '.mp3', '.m4a', '.wav', '.mp4', '.aac', '.weba', '.webm'}
MAX_AUDIO_SIZE_MB = 50

@app.post("/api/transcript-file")
async def transcript_audio_file(
    file: UploadFile = File(...),
    language: str = Form(default="es")
):
    """
    Transcribe un archivo de audio subido directamente.
    Soporta WhatsApp (.ogg/.opus), grabaciones de voz (.m4a/.mp3), y más.
    """
    if not groq_client:
        raise HTTPException(status_code=503, detail="Groq API no configurada. Agregá GROQ_API_KEY en las variables de entorno.")

    # Validar extensión
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato no soportado: '{ext}'. Formatos válidos: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}"
        )

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

        print(f"DEBUG: Archivo recibido: {file.filename} ({size_mb:.2f} MB), ext: {ext}")

        # Convertir a MP3 si es necesario (WhatsApp usa .ogg/opus)
        audio_path = input_path
        if ext in {'.ogg', '.opus', '.m4a', '.wav', '.aac', '.weba', '.webm'}:
            converted_path = os.path.join(tmpdir, "converted.mp3")
            import subprocess
            result = subprocess.run(
                ['ffmpeg', '-i', input_path, '-ar', '16000', '-ac', '1', '-b:a', '64k', converted_path],
                capture_output=True, text=True
            )
            if result.returncode == 0 and os.path.exists(converted_path):
                audio_path = converted_path
                print(f"DEBUG: Convertido a MP3 exitosamente")
            else:
                print(f"DEBUG: ffmpeg error: {result.stderr}")
                # Intentar con el archivo original si la conversión falla
                audio_path = input_path

        try:
            file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            transcription = ""

            if AudioSegment and file_size_mb >= 20:
                # Archivos grandes: trocear en partes de 20 minutos
                print(f"Dividiendo audio de {file_size_mb:.1f}MB en partes...")
                audio = AudioSegment.from_file(audio_path)
                chunk_length_ms = 20 * 60 * 1000
                chunks = [audio[i:i + chunk_length_ms] for i in range(0, len(audio), chunk_length_ms)]

                for idx, chunk in enumerate(chunks):
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as c_file:
                        chunk.export(c_file.name, format="mp3", bitrate="64k")
                        print(f"Transcribiendo parte {idx+1}/{len(chunks)}...")
                        with open(c_file.name, "rb") as cf:
                            part_text = groq_client.audio.transcriptions.create(
                                file=(c_file.name, cf.read()),
                                model="whisper-large-v3",
                                response_format="text",
                                language=language
                            )
                            transcription += str(part_text) + " "
                        os.remove(c_file.name)
            else:
                with open(audio_path, "rb") as f:
                    transcription = groq_client.audio.transcriptions.create(
                        file=(os.path.basename(audio_path), f.read()),
                        model="whisper-large-v3",
                        response_format="text",
                        language=language
                    )

            transcript_text = str(transcription).strip()
            # Limpieza con IA
            transcript_text = cleanup_transcript_with_ai(transcript_text)
            
            return {
                "transcript": transcript_text,
                "method": "groq_whisper_v3_file",
                "filename": file.filename,
                "size_mb": round(size_mb, 2)
            }

        except Exception as e:
            print(f"Error en transcripción de archivo: {e}")
            raise HTTPException(status_code=500, detail=f"Error al transcribir: {str(e)}")


# --- HERRAMIENTAS PERIODÍSTICAS (IA) ---

class AnalyzeRequest(BaseModel):
    transcript: str
    mode: str  # "summary" | "quotes" | "data" | "angle"

JOURNALIST_PROMPTS = {
    "summary": """Sos un asistente para periodistas especializados en comunicación política e imagen pública.
Dado el siguiente texto transcripto, generá un RESUMEN EJECUTIVO periodístico de máximo 5 oraciones.
Incluí: tema central, postura del hablante, y punto más relevante para una nota periodística.
Respondé solo con el resumen, sin encabezados ni explicaciones.

TRANSCRIPCIÓN:
{transcript}""",

    "quotes": """Sos un asistente para periodistas especializados en comunicación política e imagen pública.
Dado el siguiente texto transcripto, extraé las CITAS TEXTUALES más relevantes para una nota periodística.
Para cada cita, indicá en formato:

• **[cita textual]** — [contexto breve de por qué es relevante]

Separá cada cita con un DOBLE SALTO DE LÍNEA para que el texto sea legible.
Seleccioná máximo 5 citas. Si no hay citas claras, indicalo.
Respondé solo con las citas, sin introducción.

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
{transcript}"""
}

@app.post("/api/analyze")
async def analyze_transcript(req: AnalyzeRequest):
    """
    Analiza una transcripción con IA para uso periodístico.
    Modos: summary (resumen), quotes (citas), data (datos duros), angle (ángulos de nota)
    """
    if not groq_client:
        raise HTTPException(status_code=503, detail="Groq API no configurada.")

    if req.mode not in JOURNALIST_PROMPTS:
        raise HTTPException(status_code=400, detail=f"Modo inválido. Opciones: {list(JOURNALIST_PROMPTS.keys())}")

    if len(req.transcript.strip()) < 50:
        raise HTTPException(status_code=400, detail="La transcripción es demasiado corta para analizar.")

    # Truncar si es muy larga (Groq tiene límite de tokens)
    transcript = req.transcript
    if len(transcript) > 12000:
        transcript = transcript[:6000] + "\n\n[...] [Parte omitida por longitud] [...] \n\n" + transcript[-6000:]

    prompt = JOURNALIST_PROMPTS[req.mode].format(transcript=transcript)

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.3
        )
        result = response.choices[0].message.content.strip()
        return {"result": result, "mode": req.mode}

    except Exception as e:
        print(f"Error en análisis periodístico: {e}")
        raise HTTPException(status_code=500, detail=f"Error al analizar: {str(e)}")


# --- SERVIDO DE FRONTEND ---
# Este bloque DEBE ir al final para no interceptar rutas de la API
if os.path.exists(FRONTEND_DIR):
    @app.get("/{path:path}")
    async def serve_static_or_index(path: str):
        # Si la ruta está vacía, servimos index.html
        if not path:
            return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))
        
        # Intentamos buscar el archivo en la carpeta frontend
        file_path = os.path.join(FRONTEND_DIR, path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        
        # Si no existe (para rutas de SPA o errores), servimos index.html como fallback
        return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))

    # Soporte explícito para HEAD / (Render HealthCheck)
    @app.head("/", include_in_schema=False)
    @app.get("/", include_in_schema=False)
    async def serve_index():
        if os.path.exists(os.path.join(FRONTEND_DIR, 'index.html')):
            return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))
        return Response(content="StreamVault API Root", media_type="text/plain")
else:
    print(f"ADVERTENCIA: No se encontró la carpeta frontend en {FRONTEND_DIR}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
