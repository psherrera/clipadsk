"""
Traduce los errores técnicos (yt-dlp, Groq, FFmpeg, red) a mensajes que dicen la causa
y qué hacer. El texto técnico original se sigue guardando en los logs.
"""
import re

COOKIES_HINT = "Renová las cookies en Configuración → Cookies (exportalas de nuevo desde el navegador) y reintentá."

# (patrón, mensaje). El primero que coincide gana: los más específicos van primero.
_RULES = [
    (r"sign in to confirm|not a bot|confirm you.?re not a bot",
     "YouTube pide verificar que no sos un robot. " + COOKIES_HINT),
    (r"cookies? (are|is) no longer valid|cookies? .*(expired|invalid)|the provided youtube account cookies",
     "Las cookies de YouTube vencieron. " + COOKIES_HINT),
    (r"confirm your age|age.?restricted|inappropriate for some users",
     "El video tiene restricción de edad: hacen falta cookies de una cuenta mayor de 18. " + COOKIES_HINT),
    (r"private video|this video is private|is only available to (registered|logged)|login required|"
     r"requested content is not available|rate-limit reached or login required",
     "El video es privado o la plataforma pide iniciar sesión para verlo. Si tenés acceso, cargá cookies de esa "
     "cuenta en Configuración; si no, no se puede descargar."),
    (r"not available in your country|geo.?restrict|blocked it in your country",
     "La plataforma bloquea este video en tu país."),
    (r"members.only|join this channel",
     "Es un video solo para miembros del canal: hacen falta cookies de una cuenta que sea miembro."),
    (r"premieres in|this live event will begin|is not live|live event has ended",
     "Es una transmisión en vivo o un estreno que todavía no terminó: probá cuando termine."),
    (r"video unavailable|has been removed|no longer available|does not exist|http error 404|404: not found",
     "El video no existe o fue borrado. Revisá que el enlace esté completo."),
    (r"unsupported url|no suitable extractor|is not a valid url",
     "Ese enlace no es de un video compatible. Copiá el enlace directo del video (no de la página de inicio "
     "ni de un perfil)."),
    (r"no video formats found|this post (does not|doesn.t) contain",
     "Esta publicación no tiene video (es una foto o un texto)."),
    (r"requested format is not available",
     "La calidad elegida no está disponible para este video: elegí otra opción en el menú de calidad."),
    (r"invalid.?api.?key|invalid_api_key|incorrect api key|401",
     "La API Key de Groq no es válida. Revisala en Configuración → API Key (se crea gratis en console.groq.com)."),
    (r"rate.?limit|rate_limit_exceeded|too many requests.*groq|tokens per (minute|day)",
     "Groq llegó al límite de uso gratis. Esperá unos minutos y reintentá, o cargá tu propia API Key en "
     "Configuración."),
    (r"unable to connect|unable to download (api|webpage)|failed to establish a new connection|"
     r"nodename nor servname|name or service not known|no route to host|connection error",
     "No hay conexión con la plataforma: revisá que la PC tenga internet (y que ningún firewall o proxy bloquee "
     "Clipadsk) y reintentá."),
    (r"http error 429|too many requests",
     "La plataforma limitó las descargas desde tu conexión por hacer muchas seguidas. Esperá unos minutos y "
     "reintentá."),
    (r"http error 403|forbidden",
     "La plataforma rechazó la descarga. Suele arreglarse actualizando el motor (Configuración → Actualizar motor "
     "de descarga) o renovando las cookies."),
    (r"certificate verify failed|ssl: certificate|self.signed certificate",
     "Un antivirus o proxy está interceptando las conexiones seguras. Agregá YTDLP_NO_CHECK_CERTIFICATE=1 al "
     "archivo .env y reiniciá Clipadsk."),
    (r"ffmpeg (no está|not found|is not installed)|ffprobe and ffmpeg not found|hace falta ffmpeg",
     "Falta FFmpeg. Reinstalá Clipadsk con INSTALAR.bat (lo instala solo)."),
    (r"ffmpeg falló",
     "No se pudo procesar el audio o el video con FFmpeg. Puede que el archivo esté dañado o no tenga audio."),
    (r"no hay api key de groq configurada ni whisper local",
     "Para transcribir audio hace falta la API Key de Groq (gratis): cargala en Configuración → API Key."),
    (r"timed? ?out|read timeout|connection (reset|aborted|refused)|temporary failure in name resolution|"
     r"getaddrinfo failed|network is unreachable|max retries exceeded",
     "Problema de conexión a internet o la plataforma no respondió a tiempo. Revisá la conexión y reintentá."),
    (r"no space left on device|espacio insuficiente",
     "No queda espacio en el disco. Liberá espacio (por ejemplo, Configuración → Vaciar descargas) y reintentá."),
]
_COMPILED = [(re.compile(p, re.I), msg) for p, msg in _RULES]
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def friendly_error(raw) -> str:
    """Mensaje claro (causa + qué hacer) para un error técnico."""
    text = _ANSI.sub("", str(raw or ""))
    for pattern, message in _COMPILED:
        if pattern.search(text):
            return message
    short = re.sub(r"\s+", " ", text).strip()
    return f"No se pudo completar la operación. Detalle técnico: {short[:220]}" if short else \
        "No se pudo completar la operación."


def error_payload(raw) -> dict:
    """Para respuestas JSON: mensaje claro + detalle técnico corto (para el reporte de error)."""
    message = friendly_error(raw)
    technical = _ANSI.sub("", str(raw or ""))[:400]
    return {"error": message, "detail": message, "technical": technical}
