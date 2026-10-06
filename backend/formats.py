"""
Calidad de descarga de video (funciones puras, sin red: se testean con datos simulados).

- build_format_list: arma el menú de resoluciones. Cada opción es "h<altura>" y en la
  descarga yt-dlp elige la MEJOR variante de esa altura según el modo de calidad.
  (Antes el menú guardaba un format_id fijo y, por cómo se deduplicaba, quedaba la
  PEOR variante de cada resolución. Además los format_id cambian entre clientes de
  YouTube, así que en los reintentos ni siquiera eran válidos.)
- download_format_opts: opciones de yt-dlp según opción elegida y modo de calidad.
- TRIM_FFMPEG_ARGS: al recortar, FFmpeg tiene que recodificar; sin esto usa sus
  valores por defecto (CRF 23), que se notan.
"""
import re
from typing import Optional

QUALITY_COMPATIBLE = "compatible"   # H.264 + AAC: abre en cualquier editor, WhatsApp, PCs viejas
QUALITY_MAX = "max"                 # VP9/AV1 si hay: mejor imagen, puede pedir códecs extra
QUALITY_MODES = (QUALITY_COMPATIBLE, QUALITY_MAX)

# Orden de preferencia dentro de la altura elegida (yt-dlp agrega sus criterios después).
# "hdr:sdr" evita las variantes HDR, que en reproductores comunes se ven lavadas.
FORMAT_SORT = {
    QUALITY_COMPATIBLE: ["res", "+vcodec:avc", "fps", "hdr:sdr"],
    QUALITY_MAX: ["res", "fps", "hdr:sdr"],
}

# Recodificación al recortar: calidad visualmente sin pérdidas y archivo compatible.
TRIM_FFMPEG_ARGS = [
    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
]

_HEIGHT_ID = re.compile(r"h(\d{2,4})")


def normalize_quality(quality: Optional[str]) -> str:
    return quality if quality in QUALITY_MODES else QUALITY_COMPATIBLE


def is_h264(fmt: dict) -> bool:
    return (fmt.get("vcodec") or "").lower().startswith(("avc", "h264"))


def has_audio(fmt: dict) -> bool:
    return (fmt.get("acodec") or "none") != "none"


def _dimensions(fmt: dict):
    height, width = fmt.get("height"), fmt.get("width")
    res_str = fmt.get("resolution") or ""
    if not height and "x" in res_str:
        try:
            width, height = (int(v) for v in res_str.split("x")[:2])
        except ValueError:
            pass
    return width, height


def resolution_label(height: Optional[int], fmt: dict) -> str:
    """Etiqueta legible. `height` es el lado corto (un vertical 1080x1920 es 1080p)."""
    if height:
        for min_h, label in ((2160, "2160p (4K UHD)"), (1440, "1440p (2K QHD)"), (1080, "1080p (Full HD)"),
                             (720, "720p (HD)"), (480, "480p (SD)"), (360, "360p (SD)")):
            if height >= min_h:
                return label
        return f"{height}p"
    note = fmt.get("format_note")
    if note and not re.search(r"\d+x\d+", note) and len(note) < 15:
        return note
    return "Calidad estándar"


def _size(fmt: dict):
    return fmt.get("filesize") or fmt.get("filesize_approx")


def build_format_list(formats: list, has_ffmpeg: bool = True) -> list:
    """
    Una opción por resolución. yt-dlp entrega los formatos de PEOR a MEJOR, así que se
    recorren al revés: la primera variante vista de cada altura es la mejor.

    Cada opción trae `compatible` (hay H.264 en esa altura), `filesize` (mejor variante)
    y `filesize_compatible` (mejor H.264), para que el frontend muestre lo que va a bajar
    según el modo elegido en Configuración.
    """
    candidates = []
    for f in reversed(formats or []):
        if f.get("vcodec") == "none":
            continue
        if not has_ffmpeg and not has_audio(f):
            continue  # sin FFmpeg no se puede unir video + audio
        width, height = _dimensions(f)
        candidates.append((f, width, height))
    # Orden estable: de mayor a menor altura, conservando "mejor primero" dentro de cada altura
    candidates.sort(key=lambda c: c[2] or 0, reverse=True)

    options, by_label = [], {}
    for f, width, height in candidates:
        short_side = min(width, height) if (width and height) else height
        label = resolution_label(short_side, f)
        opt = by_label.get(label)
        if opt is None:
            ext = "mp4" if has_ffmpeg else (f.get("ext") or "mp4")
            opt = {
                "format_id": f"h{height}" if height else f.get("format_id"),
                "ext": ext,
                "resolution": label,
                "label": f"{label} (.{ext})",
                "filesize": _size(f),
                "filesize_compatible": None,
                "compatible": False,
            }
            by_label[label] = opt
            options.append(opt)
        if is_h264(f) and not opt["compatible"]:
            opt["compatible"] = True
            opt["filesize_compatible"] = _size(f)
    return options


def download_format_opts(format_id: Optional[str], quality: Optional[str], has_ffmpeg: bool) -> dict:
    """Opciones de yt-dlp ('format', 'format_sort', 'merge_output_format') para descargar video."""
    quality = normalize_quality(quality)
    m = _HEIGHT_ID.fullmatch(format_id or "")
    cap = f"[height<={m.group(1)}]" if m else ""

    if not has_ffmpeg:
        return {"format": f"b{cap}[ext=mp4]/b{cap}/b", "format_sort": FORMAT_SORT[quality]}

    if format_id and not m and format_id not in ("best", "bestvideo+bestaudio"):
        # format_id puntual (versión vieja del frontend u otra plataforma sin altura)
        fmt = (f"{format_id}+bestaudio[ext=m4a]/{format_id}+bestaudio/{format_id}"
               f"/bv*+ba[ext=m4a]/bv*+ba/b")
    else:
        fmt = f"bv*{cap}+ba[ext=m4a]/bv*{cap}+ba/b{cap}/b"
    return {"format": fmt, "format_sort": FORMAT_SORT[quality], "merge_output_format": "mp4"}
