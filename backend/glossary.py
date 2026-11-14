"""
Glosario de nombres propios (3.4).

Una línea por nombre en Configuración:
    Anthropic                     -> nombre correcto (se le pasa a Whisper y a la limpieza con IA)
    Yemini = Gemini               -> corrige siempre "Yemini" por "Gemini"
    Cloud | Clod = Claude         -> varias formas mal escuchadas
Las líneas que empiezan con # se ignoran.

El texto vive en un estado del módulo (lo cargan el arranque y el guardado de ajustes), así
las funciones de transcripción y limpieza lo usan sin tener que pasarlo por todos lados.
"""
import re
import threading

MAX_PROMPT_CHARS = 600      # Whisper admite ~224 tokens de prompt
MAX_GLOSSARY_CHARS = 6000
_SEPARATORS = ("=", "→", "->")

_lock = threading.Lock()
_text = ""
_compiled: list = []        # [(regex, correcto)]
_terms: list = []           # nombres correctos, sin repetir y en orden
_pairs: list = []           # [(mal, bien)]


def parse(text: str):
    """Devuelve (nombres correctos, [(forma mal escuchada, forma correcta)])."""
    terms, pairs = [], []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        right, wrongs = line, []
        for sep in _SEPARATORS:
            if sep in line:
                left, right = line.split(sep, 1)
                wrongs = [w.strip() for w in left.split("|") if w.strip()]
                right = right.strip()
                break
        if not right:
            continue
        if right not in terms:
            terms.append(right)
        for wrong in wrongs:
            if wrong.lower() != right.lower() or wrong != right:
                pairs.append((wrong, right))
    return terms, pairs


def _compile(pairs):
    out = []
    # Las formas más largas primero: "Open AI" antes que "Open"
    for wrong, right in sorted(pairs, key=lambda p: -len(p[0])):
        out.append((re.compile(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)", re.IGNORECASE | re.UNICODE), right))
    return out


def set_text(text: str):
    global _text, _compiled, _terms, _pairs
    text = (text or "")[:MAX_GLOSSARY_CHARS]
    terms, pairs = parse(text)
    with _lock:
        _text, _terms, _pairs, _compiled = text, terms, pairs, _compile(pairs)


def get_text() -> str:
    return _text


def terms() -> list:
    return list(_terms)


def pairs() -> list:
    return list(_pairs)


def whisper_prompt() -> str:
    """Pista para Whisper con la escritura correcta de los nombres ('' si no hay glosario)."""
    if not _terms:
        return ""
    out = "Nombres propios: "
    for i, term in enumerate(_terms):
        piece = term + (", " if i < len(_terms) - 1 else ".")
        if len(out) + len(piece) > MAX_PROMPT_CHARS:
            break
        out += piece
    return out.rstrip(", ") + ("" if out.endswith(".") else ".")


def apply(text: str) -> str:
    """Reemplaza las formas mal escuchadas por la correcta (palabra completa, sin importar mayúsculas)."""
    if not text or not _compiled:
        return text
    for regex, right in _compiled:
        text = regex.sub(right, text)
    return text


def apply_to_segments(segments: list) -> list:
    """Aplica el glosario al texto de los segmentos y de sus palabras (en el lugar)."""
    if not _compiled:
        return segments
    for seg in segments or []:
        if isinstance(seg, dict):
            seg["text"] = apply(seg.get("text", ""))
            for w in seg.get("words") or []:
                if isinstance(w, dict) and "w" in w:
                    w["w"] = apply(w["w"])
    return segments


def ai_rule() -> str:
    """Párrafo para el prompt de limpieza ('' si no hay glosario)."""
    if not _terms:
        return ""
    rule = ("\nNombres propios: escribilos EXACTAMENTE así cuando aparezcan: " + ", ".join(_terms[:60]) + ".")
    if _pairs:
        shown = "; ".join(f'"{w}" → "{r}"' for w, r in _pairs[:40])
        rule += f" Correcciones fijas de cosas mal escuchadas: {shown}."
    return rule + " No cambies ninguna otra palabra por esta regla.\n"
