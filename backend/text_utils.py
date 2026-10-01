"""
Funciones puras de texto (sin red ni estado global).
Se mantienen separadas de main.py para poder testearlas con pytest.
"""
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# ─── TIEMPOS / SUBTÍTULOS ────────────────────────────────────────────────────

# Línea de tiempo SRT/VTT: 00:00:01.000 --> 00:00:04.000  (o MM:SS.mmm)
_CUE_RE = re.compile(r'(\d+(?::\d+)*[\.,]\d{3})\s*-->\s*(\d+(?::\d+)*[\.,]\d{3})')
# Etiquetas inline de VTT: <c.colorWhite>, <00:02:14.000>, </c>
_TAG_RE = re.compile(r'<[^>]*>')
# Timestamps sueltos SOLO si tienen milisegundos (00:02:14.000 / 02:14.000).
# Un "10:30" normal (hora dicha por alguien) NO se toca.
_INLINE_TS_RE = re.compile(r'\b(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}\b\s*')


def parse_time_to_seconds(t_str: str) -> float:
    t_str = t_str.replace(',', '.')
    parts = t_str.split(':')
    try:
        if len(parts) == 3:
            h, m, s = parts
            return float(h) * 3600 + float(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return float(m) * 60 + float(s)
        return float(parts[0])
    except ValueError:
        return 0.0


def clean_subtitle_line(line: str) -> str:
    line = _TAG_RE.sub('', line).strip()
    return _INLINE_TS_RE.sub('', line).strip()


def parse_subtitles_to_segments(content: str) -> list:
    """Convierte SRT/VTT en una lista de {start, end, text}."""
    segments = []
    lines = content.replace('\r\n', '\n').split('\n')
    i = 0
    while i < len(lines):
        match = _CUE_RE.search(lines[i].strip())
        if not match:
            i += 1
            continue
        start = parse_time_to_seconds(match.group(1))
        end = parse_time_to_seconds(match.group(2))
        text_lines = []
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            # Siguiente cue (o número de bloque SRT seguido de cue)
            if _CUE_RE.search(nxt) or (nxt.isdigit() and i + 1 < len(lines) and _CUE_RE.search(lines[i + 1])):
                break
            if nxt and not nxt.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
                cleaned = clean_subtitle_line(nxt)
                if cleaned:
                    text_lines.append(cleaned)
            i += 1
        text = " ".join(text_lines).strip()
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return segments


def format_srt_timestamp(seconds: float) -> str:
    total_ms = int(round(max(seconds, 0) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _seg_field(segment, name, default):
    if isinstance(segment, dict):
        return segment.get(name, default)
    return getattr(segment, name, default)


def normalize_segments(segments, offset: float = 0.0) -> list:
    """Acepta segmentos como dict u objeto (Groq / faster-whisper) y devuelve dicts."""
    out = []
    for seg in segments or []:
        text = (_seg_field(seg, "text", "") or "").strip()
        out.append({
            "start": float(_seg_field(seg, "start", 0) or 0) + offset,
            "end": float(_seg_field(seg, "end", 0) or 0) + offset,
            "text": text,
        })
    return out


def generate_srt_from_segments(segments) -> str:
    lines = []
    for i, seg in enumerate(normalize_segments(segments), start=1):
        lines += [str(i), f"{format_srt_timestamp(seg['start'])} --> {format_srt_timestamp(seg['end'])}", seg["text"], ""]
    return "\n".join(lines)


# ─── LIMPIEZA ────────────────────────────────────────────────────────────────

def remove_repetitions(text: str) -> str:
    """
    Elimina frases repetidas consecutivas (típico de Whisper y subtítulos VTT).
    "Cómo andan tanto tiempo Cómo andan tanto tiempo los extrañé"
      → "Cómo andan tanto tiempo los extrañé"
    Solo colapsa repeticiones de 4+ palabras para no tocar énfasis reales ("no, no, no").
    """
    if not text or len(text) < 30:
        return text
    words = text.split()
    if len(words) < 8:
        return text

    result = []
    i = 0
    max_phrase = min(30, len(words) // 2)
    while i < len(words):
        for phrase_len in range(max_phrase, 3, -1):
            if i + phrase_len * 2 > len(words):
                continue
            phrase = words[i:i + phrase_len]
            if phrase == words[i + phrase_len:i + phrase_len * 2]:
                result.extend(phrase)
                i += phrase_len
                while words[i:i + phrase_len] == phrase:
                    i += phrase_len
                break
        else:
            result.append(words[i])
            i += 1
    return ' '.join(result)


_SENTENCE_END_RE = re.compile(r'(?<=[.!?…])\s+')


def split_text_chunks(text: str, max_len: int) -> list:
    """
    Divide un texto en partes de hasta max_len caracteres sin cortar palabras,
    priorizando cortes en párrafos, luego en oraciones y por último en espacios.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    # Unidades: párrafos → oraciones → palabras (solo si hace falta)
    units = []
    for para in re.split(r'\n\s*\n', text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_len:
            units.append(para + "\n\n")
            continue
        for sent in _SENTENCE_END_RE.split(para):
            if len(sent) <= max_len:
                units.append(sent + " ")
            else:
                words = sent.split(" ")
                buf = ""
                for w in words:
                    if len(buf) + len(w) + 1 > max_len and buf:
                        units.append(buf)
                        buf = ""
                    buf += w + " "
                if buf:
                    units.append(buf)
        units[-1] = units[-1].rstrip() + "\n\n"

    chunks, current = [], ""
    for unit in units:
        if len(current) + len(unit) > max_len and current:
            chunks.append(current.strip())
            current = ""
        current += unit
    if current.strip():
        chunks.append(current.strip())
    return chunks


def pick_relevant_chunks(chunks: list, query: str, budget_chars: int) -> list:
    """
    Elige los fragmentos más relacionados con la pregunta (por palabras en común)
    hasta llenar budget_chars, y los devuelve en orden cronológico como (idx, texto).
    Siempre incluye el primer fragmento (suele presentar a los hablantes).
    """
    stop = {"que", "de", "la", "el", "en", "y", "a", "los", "las", "del", "se", "por", "un", "una",
            "con", "para", "es", "lo", "qué", "cómo", "cuál", "dijo", "the", "of", "and", "to", "is"}
    q_words = {w for w in re.findall(r'\w+', query.lower()) if len(w) > 2 and w not in stop}

    def score(chunk):
        c_words = re.findall(r'\w+', chunk.lower())
        return sum(1 for w in c_words if w in q_words)

    ranked = sorted(range(len(chunks)), key=lambda i: score(chunks[i]), reverse=True)
    selected, used = {0}, len(chunks[0]) if chunks else 0
    for idx in ranked:
        if idx in selected:
            continue
        if used + len(chunks[idx]) > budget_chars:
            continue
        selected.add(idx)
        used += len(chunks[idx])
    return [(i, chunks[i]) for i in sorted(selected)]


# ─── CITAS ───────────────────────────────────────────────────────────────────

def _norm_words(s: str) -> list:
    return re.findall(r'\w+', s.lower())


def find_segment_times_for_quote(search_phrase: str, segments: list) -> dict:
    """Busca la frase en los segmentos y devuelve start/end del tramo más probable."""
    if not segments or not search_phrase:
        return {}
    search_norm = " ".join(_norm_words(search_phrase))
    search_words = set(search_norm.split())
    if not search_words:
        return {}

    norm = [" ".join(_norm_words(seg.get('text', ''))) for seg in segments]
    # 1) La frase entera dentro de un segmento
    for i, seg_norm in enumerate(norm):
        if search_norm in seg_norm:
            return {"start": segments[i]["start"], "end": segments[i]["end"], "seg_idx": i}
    # 2) La frase cruzando el límite entre dos segmentos
    for i in range(len(segments) - 1):
        if search_norm in norm[i] + " " + norm[i + 1]:
            return {"start": segments[i]["start"], "end": segments[i + 1]["end"], "seg_idx": i}
    # 3) Coincidencia aproximada por palabras en común
    best_score, best_idx = 0, -1
    for i, seg_norm in enumerate(norm):
        overlap = len(search_words & set(seg_norm.split()))
        if overlap > best_score:
            best_score, best_idx = overlap, i

    if best_idx >= 0 and best_score >= max(2, len(search_words) // 2):
        end_idx = min(best_idx + 2, len(segments) - 1)
        return {"start": segments[best_idx]["start"], "end": segments[end_idx]["end"], "seg_idx": best_idx}
    return {}


def parse_json_from_llm(raw: str):
    """Extrae JSON de una respuesta de LLM (tolera ```json ... ``` y texto alrededor)."""
    import json
    clean = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.MULTILINE)
    clean = re.sub(r'```\s*$', '', clean.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        m = re.search(r'(\{.*\}|\[.*\])', clean, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        raise


# ─── URLS ────────────────────────────────────────────────────────────────────

def sanitize_url(url: str) -> str:
    """
    Normaliza URLs antes de pasarlas a yt-dlp:
    - youtu.be/ID?si=... → youtube.com/watch?v=ID (conserva ?t=)
    - quita parámetros de tracking de YouTube
    - deja intactas las URLs de Bunny CDN / MediaDelivery
    """
    url = (url or "").strip()
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if 'mediadelivery.net' in host or 'b-cdn.net' in host:
            return url
        if host in ('youtu.be', 'www.youtu.be'):
            video_id = parsed.path.lstrip('/')
            if video_id:
                qs = parse_qs(parsed.query)
                url = f"https://www.youtube.com/watch?v={video_id}"
                if 't' in qs:
                    url += f"&t={qs['t'][0]}"
                parsed = urlparse(url)
                host = parsed.netloc.lower()
        if host.endswith('youtube.com'):
            qs = parse_qs(parsed.query, keep_blank_values=False)
            clean = {k: v[0] for k, v in qs.items() if k in ('v', 'list', 'index', 't')}
            url = urlunparse(parsed._replace(query=urlencode(clean)))
    except Exception:
        pass
    return url


def host_matches(url: str, domains) -> bool:
    """True si el host de la URL es alguno de los dominios (o subdominio de ellos)."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


YOUTUBE_DOMAINS = ("youtube.com", "youtu.be")
INSTAGRAM_DOMAINS = ("instagram.com",)
TIKTOK_DOMAINS = ("tiktok.com",)
TWITTER_DOMAINS = ("twitter.com", "x.com", "t.co")
FACEBOOK_DOMAINS = ("facebook.com", "fb.watch", "fb.com")
THUMBNAIL_PROXY_DOMAINS = ("cdninstagram.com", "fbcdn.net", "instagram.com")


def is_allowed_thumbnail_url(url: str) -> bool:
    try:
        if urlparse(url).scheme != "https":
            return False
    except Exception:
        return False
    return host_matches(url, THUMBNAIL_PROXY_DOMAINS)


def safe_filename(name: str, max_len: int = 60) -> str:
    """Nombre de archivo seguro para Windows y para el header Content-Disposition."""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', name or "")
    name = re.sub(r'\s+', ' ', name).strip(' .')
    return name[:max_len].strip() or "archivo"
