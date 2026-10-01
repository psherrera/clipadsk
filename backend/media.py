"""
Audio y transcripción: conversión con FFmpeg, troceo para Groq y Whisper local.
Todas las funciones son bloqueantes: llamarlas desde endpoints con run_blocking().
"""
import os
import glob
import subprocess
from typing import Callable, Optional

from config import (
    logger, FFMPEG_BIN, HAS_FFMPEG, GROQ_WHISPER_MODELS, WHISPER_MODEL_SIZE,
    GROQ_MAX_UPLOAD_MB, AUDIO_CHUNK_SECONDS,
)
from text_utils import normalize_segments

try:
    from pydub import AudioSegment
    if FFMPEG_BIN:
        AudioSegment.converter = FFMPEG_BIN
except ImportError:
    AudioSegment = None

try:
    from faster_whisper import WhisperModel
    WHISPER_MODEL_AVAILABLE = True
except ImportError:
    WhisperModel = None
    WHISPER_MODEL_AVAILABLE = False

_whisper_model = None

ProgressCb = Optional[Callable[[int, str], None]]

MIME_BY_EXT = {
    '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.mp4': 'video/mp4', '.m4a': 'audio/mp4',
    '.webm': 'audio/webm', '.weba': 'audio/webm', '.ogg': 'audio/ogg', '.opus': 'audio/ogg',
    '.aac': 'audio/aac', '.flac': 'audio/flac',
}


def _ffmpeg() -> str:
    return FFMPEG_BIN or 'ffmpeg'


def run_ffmpeg(args: list, timeout: int = 3600):
    """Ejecuta ffmpeg y lanza un error legible si falla."""
    cmd = [_ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', *args]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg falló: {res.stderr.strip()[-400:]}")


def to_speech_mp3(input_path: str, output_path: str) -> str:
    """
    Convierte cualquier audio/video a MP3 mono 16 kHz 32 kbps (ideal para Whisper:
    ~14 MB por hora). Usa FFmpeg directo (no carga el archivo en memoria).
    """
    if HAS_FFMPEG:
        run_ffmpeg(['-i', input_path, '-vn', '-ac', '1', '-ar', '16000', '-b:a', '32k', '-f', 'mp3', output_path])
    elif AudioSegment:
        audio = AudioSegment.from_file(input_path).set_frame_rate(16000).set_channels(1)
        audio.export(output_path, format="mp3", bitrate="32k")
    else:
        raise RuntimeError("FFmpeg no está instalado: no se puede convertir el audio.")
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("La conversión de audio no produjo resultado (¿el archivo tiene audio?).")
    return output_path


def split_audio(path: str, out_dir: str, chunk_seconds: int = AUDIO_CHUNK_SECONDS) -> list:
    """Parte un audio en trozos de chunk_seconds. Devuelve [(ruta, offset_segundos)]."""
    pattern = os.path.join(out_dir, 'chunk_%03d.mp3')
    run_ffmpeg(['-i', path, '-f', 'segment', '-segment_time', str(chunk_seconds),
                '-ac', '1', '-ar', '16000', '-b:a', '32k', '-reset_timestamps', '1', pattern])
    files = sorted(glob.glob(os.path.join(out_dir, 'chunk_*.mp3')))
    return [(f, i * chunk_seconds) for i, f in enumerate(files)]


# ─── GROQ WHISPER ────────────────────────────────────────────────────────────

_dead_whisper: set = set()


def _groq_transcribe_one(client, path: str, lang: str):
    """Transcribe un archivo. Si Groq retiró el modelo de Whisper, prueba el siguiente de la lista."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        data = f.read()
    last_err = None
    for model in [m for m in GROQ_WHISPER_MODELS if m not in _dead_whisper] or GROQ_WHISPER_MODELS:
        try:
            res = client.audio.transcriptions.create(
                file=(os.path.basename(path), data, MIME_BY_EXT.get(ext, 'audio/mpeg')),
                model=model,
                response_format="verbose_json",
                language=lang if lang in ("es", "en") else None,
            )
            return (getattr(res, "text", "") or ""), (getattr(res, "segments", None) or [])
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ("model_not_found", "does not exist", "decommissioned", "not have access to")):
                logger.warning(f"Modelo de Whisper no disponible en Groq: {model}")
                _dead_whisper.add(model)
                last_err = e
                continue
            raise
    raise RuntimeError(f"Ningún modelo de Whisper disponible en Groq: {last_err}")


def transcribe_with_groq(client, audio_path: str, lang: str, work_dir: str, progress: ProgressCb = None):
    """Transcribe con Groq; si el archivo supera el límite lo parte en trozos."""
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if size_mb < GROQ_MAX_UPLOAD_MB:
        if progress:
            progress(40, "Transcribiendo con Groq Whisper...")
        text, segs = _groq_transcribe_one(client, audio_path, lang)
        return text.strip(), normalize_segments(segs)

    if not HAS_FFMPEG:
        raise RuntimeError(f"El audio pesa {size_mb:.1f} MB y hace falta FFmpeg para dividirlo.")
    chunk_dir = os.path.join(work_dir, 'chunks')
    os.makedirs(chunk_dir, exist_ok=True)
    chunks = split_audio(audio_path, chunk_dir)
    logger.info(f"Audio de {size_mb:.1f} MB dividido en {len(chunks)} partes")

    texts, segments = [], []
    for idx, (chunk_path, offset) in enumerate(chunks):
        if progress:
            progress(25 + int(idx / len(chunks) * 50), f"Transcribiendo parte {idx + 1}/{len(chunks)} con Groq Whisper...")
        text, segs = _groq_transcribe_one(client, chunk_path, lang)
        texts.append(text.strip())
        segments.extend(normalize_segments(segs, offset=offset))
        os.remove(chunk_path)
    return " ".join(t for t in texts if t), segments


# ─── WHISPER LOCAL ───────────────────────────────────────────────────────────

def get_whisper_model():
    global _whisper_model
    if not WHISPER_MODEL_AVAILABLE:
        return None
    if _whisper_model is None:
        logger.info(f"Cargando modelo Whisper local: {WHISPER_MODEL_SIZE}")
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


def transcribe_with_local_whisper(audio_path: str, lang: str = "es", progress: ProgressCb = None):
    model = get_whisper_model()
    if not model:
        raise RuntimeError("No hay modelo Whisper local. Instalá faster-whisper para usar este modo.")
    if progress:
        progress(40, "Transcribiendo en local con Whisper (puede tardar)...")
    segs, info = model.transcribe(audio_path, beam_size=5, vad_filter=True,
                                  language=lang if lang in ("es", "en") else None)
    segments = normalize_segments(list(segs))
    text = " ".join(s["text"] for s in segments if s["text"])
    logger.info(f"Whisper local terminado ({getattr(info, 'duration', '?')} s de audio)")
    return text, segments


# ─── CASCADA ─────────────────────────────────────────────────────────────────

def transcribe_audio(audio_path: str, lang: str, groq_client, work_dir: str,
                     progress: ProgressCb = None, log: Callable[[str], None] = None):
    """
    Groq Whisper → (si falla) Whisper local.
    Devuelve (texto, segmentos, método).
    """
    log = log or (lambda m: None)
    if groq_client:
        try:
            text, segments = transcribe_with_groq(groq_client, audio_path, lang, work_dir, progress)
            return text, segments, "groq_whisper_v3_file"
        except Exception as e:
            log(f"Error en Groq Whisper: {e}")
            if not WHISPER_MODEL_AVAILABLE:
                raise RuntimeError(f"Error en Groq API: {e}")
            log("Probando con Whisper local...")
    elif not WHISPER_MODEL_AVAILABLE:
        raise RuntimeError("No hay API Key de Groq configurada ni Whisper local instalado.")

    text, segments = transcribe_with_local_whisper(audio_path, lang, progress)
    return text, segments, "local_whisper"
