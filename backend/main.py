import os
import uuid
import json
import re
import tempfile
import requests
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from deep_translator import GoogleTranslator
import whisper

# ─────────────────────────────────────────────
#  CONFIGURACIÓN LOCAL
# ─────────────────────────────────────────────
# GROQ es opcional. Si existe la variable de entorno se usará primero,
# de lo contrario se cae al modelo Whisper local.
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except ImportError:
    groq_client = None

app = FastAPI(title="Clipadsk – Local Media Downloader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
#  RUTAS
# ─────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')
CACHE_FILE      = os.path.join(BASE_DIR, 'transcripts_cache.json')

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────
#  MODELO WHISPER LOCAL
# ─────────────────────────────────────────────
_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            cache_dir = os.environ.get(
                'WHISPER_CACHE_DIR',
                os.path.join(os.path.expanduser("~"), ".cache", "whisper")
            )
            print(f"Cargando modelo Whisper 'base' en {device}...")
            _whisper_model = whisper.load_model("base", device=device, download_root=cache_dir)
        except Exception as e:
            print(f"Error cargando Whisper: {e}")
    return _whisper_model

# ─────────────────────────────────────────────
#  CACHÉ DE TRANSCRIPCIONES
# ─────────────────────────────────────────────
def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache: dict):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

# ─────────────────────────────────────────────
#  TRADUCCIÓN
# ─────────────────────────────────────────────
def translate_to_spanish(text: str) -> str:
    if not text:
        return ""
    try:
        translator = GoogleTranslator(source='auto', target='es')
        if len(text) > 4000:
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            return " ".join(translator.translate(c) for c in chunks)
        return translator.translate(text)
    except Exception as e:
        print(f"Error traducción: {e}")
        return text

# ─────────────────────────────────────────────
#  HELPERS YT-DLP
# ─────────────────────────────────────────────
def build_ydl_opts(extra: dict = {}) -> dict:
    """Opciones base para yt-dlp. Agrega cookies.txt si existe en BASE_DIR."""
    cookie_path = os.path.join(BASE_DIR, 'cookies.txt')
    opts = {
        'quiet':              True,
        'no_warnings':        True,
        'cachedir':           False,
        'noplaylist':         True,
        'nocheckcertificate': True,
        'ignoreerrors':       True,
        'user_agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/121.0.0.0 Safari/537.36'
        ),
        **extra,
    }
    if os.path.exists(cookie_path):
        opts['cookiefile'] = cookie_path
    return opts

def add_youtube_clients(opts: dict) -> dict:
    """Fuerza clientes android/ios/tv para evitar 403 en YouTube."""
    opts['extractor_args'] = {'youtube': {'player_client': ['android', 'ios', 'tv']}}
    return opts

def is_youtube(url: str) -> bool:
    return 'youtube.com' in url or 'youtu.be' in url

# ─────────────────────────────────────────────
#  MODELOS PYDANTIC
# ─────────────────────────────────────────────
class VideoRequest(BaseModel):
    url: str
    format_id: Optional[str] = "best"

# ─────────────────────────────────────────────
#  ENDPOINTS
# ─────────────────────────────────────────────

@app.post("/api/video-info")
async def get_video_info(req: VideoRequest):
    import yt_dlp
    url  = req.url
    opts = build_ydl_opts()
    if is_youtube(url):
        opts = add_youtube_clients(opts)

    info       = None
    last_error = ""

    # Intento principal
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        last_error = str(e)

    # Fallback con cliente web
    if not info:
        try:
            fallback = build_ydl_opts(
                {'extractor_args': {'youtube': {'player_client': ['web', 'tv']}}}
            )
            with yt_dlp.YoutubeDL(fallback) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e2:
            last_error += f" | {e2}"

    if not info:
        raise HTTPException(
            status_code=500,
            detail=f"No se pudo obtener información: {last_error}"
        )

    # Procesar formatos (solo los que tienen video)
    formats      = []
    seen         = set()
    video_formats = sorted(
        [f for f in info.get('formats', []) if f.get('vcodec') != 'none'],
        key=lambda x: x.get('height') or 0,
        reverse=True,
    )
    for f in video_formats:
        res = f.get('resolution') or (f"{f.get('height')}p" if f.get('height') else None)
        if not res or res == "Nonep":
            res = f.get('format_note') or f.get('format_id') or "Calidad única"
        ext = f.get('ext', 'mp4')
        key = f"{res}_{ext}"
        if key not in seen:
            formats.append({
                'format_id':  f.get('format_id'),
                'ext':        ext,
                'resolution': res,
                'filesize':   f.get('filesize') or f.get('filesize_approx'),
                'label':      f"{res} (.{ext})",
            })
            seen.add(key)

    # Proxy thumbnail para Instagram
    thumbnail = info.get('thumbnail')
    if 'instagram.com' in url and thumbnail:
        thumbnail = f"/api/proxy-thumbnail?url={thumbnail}"

    return {
        'title':             info.get('title'),
        'thumbnail':         thumbnail,
        'max_res_thumbnail': thumbnail,
        'duration':          info.get('duration'),
        'uploader':          info.get('uploader') or "Desconocido",
        'description':       (info.get('description') or 'Sin descripción')[:200] + '...',
        'formats':           formats,
        'has_ffmpeg':        True,
        'has_subtitles':     bool(info.get('subtitles') or info.get('automatic_captions')),
    }


@app.post("/api/transcript")
async def get_transcript(req: VideoRequest):
    import yt_dlp
    url   = req.url
    cache = load_cache()

    if url in cache:
        return {"transcript": cache[url], "method": "cache"}

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── PASO 1: subtítulos directos (YouTube) ─────────────────────
        if is_youtube(url):
            try:
                sub_opts = build_ydl_opts({
                    'skip_download':     True,
                    'writesubtitles':    True,
                    'writeautomaticsub': True,
                    'subtitleslangs':    ['es.*', 'en.*'],
                    'outtmpl':           os.path.join(tmpdir, 'sub.%(ext)s'),
                })
                sub_opts = add_youtube_clients(sub_opts)

                with yt_dlp.YoutubeDL(sub_opts) as ydl:
                    ydl.extract_info(url, download=True)

                sub_file   = None
                is_english = False

                for fname in os.listdir(tmpdir):
                    if fname.startswith('sub.') and ('.es' in fname or '.es-419' in fname):
                        sub_file = os.path.join(tmpdir, fname)
                        break
                if not sub_file:
                    for fname in os.listdir(tmpdir):
                        if fname.startswith('sub.') and ('.en' in fname or '.en-US' in fname):
                            sub_file   = os.path.join(tmpdir, fname)
                            is_english = True
                            break

                if sub_file:
                    with open(sub_file, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # Limpiar VTT
                    content = re.sub(r'WEBVTT.*?\n\n', '', content, flags=re.DOTALL)
                    content = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}.*?\n', '', content)
                    content = re.sub(r'^\d+\n', '', content, flags=re.MULTILINE)
                    content = re.sub(r'<[^>]*>', '', content)
                    final   = ' '.join(l.strip() for l in content.split('\n') if l.strip())

                    if is_english:
                        final = translate_to_spanish(final)

                    cache[url] = final
                    save_cache(cache)
                    return {"transcript": final, "method": "subtitles"}
            except Exception:
                pass  # cae a Whisper

        # ── PASO 2: descargar audio y transcribir ─────────────────────
        try:
            audio_opts = build_ydl_opts({
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(tmpdir, 'audio.%(ext)s'),
                'postprocessors': [{
                    'key':              'FFmpegExtractAudio',
                    'preferredcodec':   'mp3',
                    'preferredquality': '128',
                }],
            })
            if is_youtube(url):
                audio_opts = add_youtube_clients(audio_opts)

            with yt_dlp.YoutubeDL(audio_opts) as ydl:
                ydl.download([url])

            audio_file = next(
                (os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith('audio.')),
                None
            )
            if not audio_file:
                raise Exception("No se pudo descargar el audio")

            # 2a. Groq (si está configurado y el archivo < 25 MB)
            if groq_client:
                try:
                    size_mb = os.path.getsize(audio_file) / (1024 * 1024)
                    if size_mb < 25:
                        print(f"Transcribiendo con Groq ({size_mb:.1f} MB)...")
                        with open(audio_file, "rb") as f:
                            transcription = groq_client.audio.transcriptions.create(
                                file=(audio_file, f.read()),
                                model="whisper-large-v3",
                                response_format="text",
                                language="es",
                            )
                        cache[url] = transcription
                        save_cache(cache)
                        return {"transcript": transcription, "method": "groq_whisper_v3"}
                    else:
                        print(f"Audio muy grande ({size_mb:.1f} MB), usando Whisper local...")
                except Exception as ge:
                    print(f"Groq falló, usando Whisper local: {ge}")

            # 2b. Whisper local
            model = get_whisper_model()
            if not model:
                raise Exception(
                    "Whisper local no disponible. Verifica la instalación de torch y openai-whisper."
                )

            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            # fp16=False es obligatorio en CPU para evitar errores
            use_fp16 = (device == "cuda")

            print(f"Transcribiendo localmente con Whisper 'base' ({device})...")
            result = model.transcribe(audio_file, fp16=use_fp16)
            text   = result.get('text', '').strip()

            if result.get('language') != 'es':
                print("Traduciendo al español...")
                text = translate_to_spanish(text)

            cache[url] = text
            save_cache(cache)
            return {"transcript": text, "method": f"whisper_local_{device}"}

        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/download")
async def download_video(req: VideoRequest):
    import yt_dlp
    url      = req.url
    uid      = str(uuid.uuid4())
    template = os.path.join(DOWNLOAD_FOLDER, f'%(title)s_{uid}.%(ext)s')

    opts = build_ydl_opts({'format': req.format_id, 'outtmpl': template})
    if is_youtube(url):
        opts = add_youtube_clients(opts)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        for fname in os.listdir(DOWNLOAD_FOLDER):
            if uid in fname:
                return FileResponse(
                    os.path.join(DOWNLOAD_FOLDER, fname),
                    filename=fname,
                )
        raise Exception("Archivo no encontrado tras la descarga")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/proxy-thumbnail")
async def proxy_thumbnail(url: str):
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/121.0.0.0 Safari/537.36'
        ),
        'Referer': 'https://www.instagram.com/',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        return Response(
            content=resp.content,
            media_type=resp.headers.get('Content-Type', 'image/jpeg'),
        )
    except Exception:
        return Response(status_code=500)


# ─────────────────────────────────────────────
#  ARRANQUE LOCAL
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀  Clipadsk backend corriendo en http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False)
