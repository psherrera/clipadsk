"""
Funciones de IA (Groq): limpieza de transcripciones, traducción, análisis
periodístico, citas, chat y OCR. Todas son bloqueantes: usar run_blocking().
"""
import re
import time
from typing import Optional

from config import (
    logger, GROQ_API_KEY, GROQ_TEXT_MODELS, GROQ_CHAT_MODELS, GROQ_VISION_MODELS,
    AI_CHUNK_CHARS, AI_CLEANUP_MAX_CHARS, ANALYSIS_CHUNK_CHARS, CHAT_CONTEXT_CHARS,
)
from text_utils import split_text_chunks, pick_relevant_chunks, parse_json_from_llm

try:
    from groq import Groq
    import groq as groq_module
except ImportError:  # pragma: no cover
    Groq = None
    groq_module = None

try:
    from deep_translator import GoogleTranslator
except ImportError:  # pragma: no cover
    GoogleTranslator = None

_default_client = Groq(api_key=GROQ_API_KEY, max_retries=3) if (Groq and GROQ_API_KEY) else None
_client_cache: dict = {}


class RateLimitedError(Exception):
    """Todos los modelos devolvieron 'rate limit'."""


class NoModelAvailableError(Exception):
    """Ninguno de los modelos configurados existe para esta cuenta de Groq."""


def get_groq_client(api_key: Optional[str] = None):
    """Cliente con la key del usuario (si la mandó el navegador) o la del .env."""
    key = (api_key or "").strip()
    if key and Groq:
        if key not in _client_cache:
            _client_cache.clear()  # solo guardamos una (la última usada)
            _client_cache[key] = Groq(api_key=key, max_retries=3)
        return _client_cache[key]
    return _default_client


def is_rate_limit(err: Exception) -> bool:
    if groq_module is not None and isinstance(err, getattr(groq_module, "RateLimitError", ())):
        return True
    s = str(err)
    return "rate_limit_exceeded" in s or "429" in s


def is_model_error(err: Exception) -> bool:
    """El modelo no existe, fue retirado o la cuenta no tiene acceso."""
    s = str(err).lower()
    return any(k in s for k in ("model_not_found", "does not exist", "decommissioned",
                                "model_decommissioned", "not have access to", "model_terms_required"))


# ─── ELECCIÓN DE MODELO ──────────────────────────────────────────────────────
# Groq retira modelos cada tanto. En vez de nombres fijos, se pregunta a Groq qué
# modelos tiene la cuenta (se guarda 1 hora) y se usa el primero de la lista de
# preferencia que esté disponible. Los que fallan por "no existe" se descartan.

_MODELS_TTL = 3600
_available_cache: dict = {}   # id(cliente) -> (timestamp, set de ids | None)
_dead_models: set = set()


def available_models(client) -> Optional[set]:
    key = id(client)
    cached = _available_cache.get(key)
    if cached and time.time() - cached[0] < _MODELS_TTL:
        return cached[1]
    try:
        ids = {m.id for m in client.models.list().data}
    except Exception as e:
        logger.debug(f"No se pudo listar modelos de Groq: {e}")
        ids = None
    _available_cache[key] = (time.time(), ids)
    return ids


def pick_models(client, preferences: list) -> list:
    """Modelos a probar, en orden: los preferidos que la cuenta tiene disponibles."""
    ordered = [m for m in dict.fromkeys(preferences) if m not in _dead_models]
    ids = available_models(client)
    if ids:
        present = [m for m in ordered if m in ids]
        if present:
            return present
    return ordered or list(dict.fromkeys(preferences))


def _clean_output(text: str) -> str:
    # Algunos modelos (Qwen) devuelven el razonamiento entre <think>...</think>
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def chat_completion(client, prompt: str = "", *, system: str = None, models=None, max_tokens: int = 1500,
                    temperature: float = 0.3, json_mode: bool = False, messages: list = None) -> tuple:
    """
    Llama al primer modelo disponible de la lista. Si da rate limit o el modelo no existe,
    prueba el siguiente. Devuelve (texto, modelo usado).
    """
    if messages is None:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    rate_err, model_errs = None, []
    for model in pick_models(client, models or GROQ_TEXT_MODELS):
        base = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=temperature)
        extras = {}
        if model.startswith("openai/gpt-oss"):
            # Modelos de razonamiento: poco razonamiento y margen para la respuesta
            extras["reasoning_effort"] = "low"
            base["max_tokens"] = max_tokens + 1024
        if json_mode:
            extras["response_format"] = {"type": "json_object"}
        attempts = [{**base, **extras}] + ([base] if extras else [])
        for i, kwargs in enumerate(attempts):
            try:
                res = client.chat.completions.create(**kwargs)
                text = _clean_output(res.choices[0].message.content)
                if not text and i + 1 < len(attempts):
                    continue
                return text, model
            except Exception as e:
                if is_rate_limit(e):
                    logger.info(f"Rate limit en {model}, probando el siguiente modelo...")
                    rate_err = e
                    break
                if is_model_error(e):
                    logger.warning(f"Modelo de Groq no disponible: {model} ({str(e)[:120]})")
                    _dead_models.add(model)
                    model_errs.append(model)
                    break
                if i + 1 < len(attempts):  # parámetro no soportado (p. ej. reasoning_effort): reintentar simple
                    logger.debug(f"{model} rechazó parámetros extra, reintento simple: {str(e)[:120]}")
                    continue
                raise
    if rate_err:
        raise RateLimitedError(str(rate_err))
    raise NoModelAvailableError(
        "Ninguno de los modelos de IA configurados está disponible en tu cuenta de Groq "
        f"(probados: {', '.join(model_errs) or 'ninguno'}). Actualizá Clipadsk o definí GROQ_TEXT_MODELS en .env.")


# ─── LIMPIEZA DE TRANSCRIPCIONES ─────────────────────────────────────────────

LANG_NAMES = {"es": "español", "en": "inglés"}

CLEANUP_PROMPT = """Actuá como un corrector de estilo estricto. Tu único objetivo es tomar esta transcripción cruda y aplicar correcciones ortotipográficas para facilitar su lectura, manteniendo el 100% del contenido original hablado.

Instrucciones de edición:

Preservación absoluta: NO resumas, NO unifiques temas, NO omitas redundancias ni cambies las palabras de quienes hablan. Los periodistas necesitan la desgrabación exacta para extraer sus propias citas.

Corrección de formato: limitate a corregir puntuación (comas, puntos, signos de interrogación), mayúsculas y separar en párrafos (doble salto de línea) para que el texto sea legible.

Limpieza mínima: solo podés quitar tartamudeos o muletillas extremas ("eh...", "este...") si interrumpen gravemente la lectura. No elimines anécdotas, datos repetidos ni interacciones.
{translate_rule}
Regla estricta de formato (cero artefactos): respondé ÚNICAMENTE con la desgrabación procesada. Prohibido incluir saludos, introducciones ("Aquí tienes...", "Texto corregido:"), viñetas explicativas o conclusiones. Empezá directamente con la primera palabra y terminá con el último punto.
{part_note}
Procesá el texto que está entre [INICIO DEL TEXTO] y [FIN DEL TEXTO]:

[INICIO DEL TEXTO]
{text}
[FIN DEL TEXTO]"""


def cleanup_transcript(text: str, client, target_lang: str = "es", warnings: list = None) -> str:
    """
    Puntúa y separa en párrafos SIN cambiar lo dicho. Procesa por partes cortadas en
    oraciones. Si una parte falla (p. ej. rate limit) se deja esa parte cruda.
    """
    warnings = warnings if warnings is not None else []
    if not client or not text or len(text) < 50:
        return text
    if len(text) > AI_CLEANUP_MAX_CHARS:
        warnings.append(f"La transcripción es muy larga ({len(text):,} caracteres): se muestra sin la limpieza de puntuación con IA.")
        return text

    lang_name = LANG_NAMES.get(target_lang)
    translate_rule = (f"\nIdioma: el resultado debe estar en {lang_name}. Si el texto está en otro idioma, "
                      f"traducilo fielmente al {lang_name}, frase por frase, sin resumir ni omitir nada.\n") if lang_name else ""
    chunks = split_text_chunks(text, AI_CHUNK_CHARS)
    out, failed = [], 0
    for i, chunk in enumerate(chunks):
        part_note = (f"\nEste es el fragmento {i + 1} de {len(chunks)} de una transcripción más larga: "
                     "no agregues ni quites nada al principio o al final.\n") if len(chunks) > 1 else ""
        prompt = CLEANUP_PROMPT.format(translate_rule=translate_rule, part_note=part_note, text=chunk)
        try:
            cleaned, _ = chat_completion(client, prompt, max_tokens=4000, temperature=0.2)
            # Si el modelo devolvió algo sospechosamente corto, preferimos el original
            out.append(cleaned if cleaned and len(cleaned) > len(chunk) * 0.6 else chunk)
        except Exception as e:
            logger.warning(f"Limpieza IA falló en parte {i + 1}/{len(chunks)}: {e}")
            out.append(chunk)
            failed += 1
    if failed:
        warnings.append(f"{failed} de {len(chunks)} partes quedaron sin limpieza con IA (límite de Groq o error).")
    return "\n\n".join(out)


# ─── TRADUCCIÓN (Google, para subtítulos en inglés) ──────────────────────────

def translate_texts(texts: list, target: str = "es") -> list:
    """
    Traduce una lista de textos agrupándolos en bloques (una llamada por bloque
    en vez de una por segmento). Si algo falla, devuelve el original.
    """
    if not GoogleTranslator or not texts:
        return texts
    translator = GoogleTranslator(source='auto', target=target)
    result = list(texts)
    sep = "\n"
    batch, batch_idx, size = [], [], 0

    def flush():
        if not batch:
            return
        try:
            translated = translator.translate(sep.join(batch)) or ""
            parts = translated.split(sep)
            if len(parts) == len(batch):
                for i, p in zip(batch_idx, parts):
                    result[i] = p.strip()
                return
        except Exception as e:
            logger.warning(f"Traducción por bloque falló: {e}")
        for i, t in zip(batch_idx, batch):  # plan B: uno por uno
            try:
                result[i] = translator.translate(t) or t
            except Exception:
                pass

    for i, t in enumerate(texts):
        t = (t or "").replace("\n", " ").strip()
        if size + len(t) + 1 > 4500 and batch:
            flush()
            batch, batch_idx, size = [], [], 0
        batch.append(t)
        batch_idx.append(i)
        size += len(t) + 1
    flush()
    return result


# ─── HERRAMIENTAS PERIODÍSTICAS ──────────────────────────────────────────────

JOURNALIST_PROMPTS = {
    "summary": """Sos un asistente para periodistas especializados en comunicación política e imagen pública.
Dado el siguiente texto transcripto, generá un RESUMEN EJECUTIVO periodístico de máximo 5 oraciones.
Incluí: tema central, postura del hablante, y punto más relevante para una nota periodística.
Respondé solo con el resumen, sin encabezados ni explicaciones.

TRANSCRIPCIÓN:
{transcript}""",

    "data": """Sos un asistente para periodistas especializados en comunicación política e imagen pública.
Dado el siguiente texto transcripto, extraé todos los DATOS DUROS mencionados:
- Fechas, horarios y plazos
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
1. DETERMINÁ LOS NOMBRES REALES: deducí los nombres de los hablantes si se presentan, se saludan, se llaman por su nombre o se infiere por el contexto. Si los detectás, usá sus nombres reales como etiquetas (por ejemplo: **Juan**, **María**, **Entrevistador**) en lugar de "Hablante A" o "Hablante B".
2. Identificá los cambios de turno de palabra basándote en la coherencia y las preguntas/respuestas.
3. Formateá la salida como un diálogo claro, precediendo cada intervención con el nombre del hablante en negrita:
**Nombre del Hablante**: [texto original hablado en este turno]
4. Preservación absoluta: no resumas, no edites ni elimines contenido. Mantené el 100% de las palabras originales.
5. Respondé ÚNICAMENTE con el diálogo formateado, sin saludos, introducciones ni conclusiones.
{context}
TRANSCRIPCIÓN:
{transcript}""",
}

QUOTES_PROMPT = """¡IMPORTANTE! Respondé EXCLUSIVAMENTE con un objeto JSON válido con un array bajo la clave "quotes", sin texto antes ni después.

Sos un asistente para periodistas. Del siguiente texto transcripto, extraé las {n} CITAS TEXTUALES más noticiosas, llamativas o reveladoras.

Para cada cita devolvé un objeto con estos campos exactos:
- "quote": la cita textual EXACTA, copiada palabra por palabra del texto (sin comillas dobles internas; usá simples si hace falta)
- "note": una o dos oraciones sobre por qué es relevante para una nota periodística
- "search": una frase corta de 4-8 palabras copiada literalmente de la cita, para ubicarla en el texto

Formato (solo el JSON):
{{"quotes": [{{"quote": "...", "note": "...", "search": "..."}}]}}

TRANSCRIPCIÓN:
{transcript}"""

QUOTES_SELECT_PROMPT = """Sos editor periodístico. Estas son citas candidatas extraídas de distintas partes de una misma entrevista.
Elegí las 5 más noticiosas y reveladoras (sin repetir temas) y respondé SOLO con JSON: {{"indices": [números de las citas elegidas]}}

CITAS:
{candidates}"""

MAP_NOTES_PROMPT = """Sos asistente de un periodista. Esta es la parte {i} de {n} de una transcripción larga.
Tomá notas detalladas de esta parte para que luego se pueda analizar el total sin leer el original:
- temas tratados y postura de cada hablante
- TODOS los datos duros (fechas, horarios, cifras, montos, nombres y cargos, instituciones, lugares)
- frases textuales importantes, copiadas exactamente entre comillas
Respondé solo con las notas, sin introducción.

PARTE {i}/{n}:
{transcript}"""


def _extract_speakers(text: str) -> list:
    return list(dict.fromkeys(re.findall(r'^\*\*([^*\n]{1,40})\*\*\s*:', text, flags=re.MULTILINE)))


def analyze_transcript(client, transcript: str, mode: str) -> dict:
    """
    Corre una herramienta periodística sobre la transcripción COMPLETA.
    Si es larga: diarización se hace por partes (concatenadas) y el resto con
    un paso previo de notas por parte (map → reduce).
    """
    chunks = split_text_chunks(transcript, ANALYSIS_CHUNK_CHARS)
    n = len(chunks)

    if mode == "diarization":
        outputs, model_used = [], None
        for i, chunk in enumerate(chunks):
            speakers = _extract_speakers("\n".join(outputs))
            ctx = ""
            if n > 1:
                ctx = f"\nEsta es la parte {i + 1} de {n} de la conversación."
                if speakers:
                    ctx += f" Hablantes ya identificados en partes anteriores (usá los mismos nombres): {', '.join(speakers)}."
                ctx += "\n"
            prompt = JOURNALIST_PROMPTS["diarization"].format(context=ctx, transcript=chunk)
            out, model_used = chat_completion(client, prompt, max_tokens=6000)
            outputs.append(out)
        return {"result": "\n\n".join(outputs), "model_used": model_used, "parts": n}

    if n == 1:
        source = transcript
    else:
        notes = []
        for i, chunk in enumerate(chunks):
            note, _ = chat_completion(client, MAP_NOTES_PROMPT.format(i=i + 1, n=n, transcript=chunk), max_tokens=1500)
            notes.append(f"[Parte {i + 1}/{n}]\n{note}")
        source = ("(Notas detalladas de una transcripción larga, tomadas parte por parte)\n\n" + "\n\n".join(notes))
    result, model_used = chat_completion(client, JOURNALIST_PROMPTS[mode].format(transcript=source),
                                         max_tokens=2000 if mode == "data" else 1500)
    return {"result": result, "model_used": model_used, "parts": n}


def _quotes_from(raw: str) -> list:
    parsed = parse_json_from_llm(raw)
    if isinstance(parsed, dict):
        parsed = next((v for v in parsed.values() if isinstance(v, list)), [])
    return [q for q in parsed if isinstance(q, dict) and q.get("quote")] if isinstance(parsed, list) else []


def extract_quotes(client, transcript: str) -> tuple:
    """Devuelve (lista de citas, cantidad de partes analizadas)."""
    chunks = split_text_chunks(transcript, ANALYSIS_CHUNK_CHARS)
    n = len(chunks)
    per_chunk = 5 if n == 1 else 3
    candidates = []
    for chunk in chunks:
        raw, _ = chat_completion(client, QUOTES_PROMPT.format(n=per_chunk, transcript=chunk),
                                 max_tokens=2000, json_mode=True)
        try:
            candidates.extend(_quotes_from(raw))
        except Exception as e:
            logger.warning(f"No se pudo parsear JSON de citas: {e}. Raw: {raw[:300]}")
    if n == 1 or len(candidates) <= 5:
        return candidates[:5], n

    listing = "\n".join(f"{i}. \"{q.get('quote', '')}\"" for i, q in enumerate(candidates))
    try:
        raw, _ = chat_completion(client, QUOTES_SELECT_PROMPT.format(candidates=listing), max_tokens=200, json_mode=True)
        data = parse_json_from_llm(raw)
        idx = data.get("indices", []) if isinstance(data, dict) else data
        chosen = [candidates[int(i)] for i in idx if str(i).isdigit() and int(i) < len(candidates)]
        if chosen:
            return chosen[:5], n
    except Exception as e:
        logger.warning(f"Selección de citas falló, uso las primeras: {e}")
    return candidates[:5], n


CHAT_SYSTEM = """Sos un asistente experto que analiza transcripciones de videos.
Respondé preguntas basándote únicamente en la transcripción que sigue.{partial}

--- TRANSCRIPCIÓN ---
{transcript}
--- FIN ---

Respondé de forma concisa, útil y en español.
REGLAS DE FORMATO:
1. Usá **negritas** para nombres, marcas o conceptos clave.
2. Dejá una línea en blanco entre párrafos o ítems de una lista.
Si la respuesta no está en la transcripción, decilo amablemente."""


def chat_about_transcript(client, transcript: str, question: str) -> str:
    chunks = split_text_chunks(transcript, 3000)
    partial = ""
    if len(transcript) > CHAT_CONTEXT_CHARS:
        picked = pick_relevant_chunks(chunks, question, CHAT_CONTEXT_CHARS)
        transcript = "\n\n[...]\n\n".join(c for _, c in picked)
        partial = (" La transcripción es larga: se incluyen solo los fragmentos más relacionados con la pregunta "
                   "(marcados con [...] los saltos). Si la respuesta podría estar en otra parte, aclaralo.")
    answer, _ = chat_completion(client, question, system=CHAT_SYSTEM.format(partial=partial, transcript=transcript),
                                models=GROQ_CHAT_MODELS, max_tokens=1024, temperature=0.5)
    return answer


def ocr_image(client, b64_jpeg: str) -> str:
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Extract all readable text from this image. Return only the extracted text, keeping logical line breaks. Do not add any introductory or extra conversational text."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_jpeg}"}},
    ]}]
    text, _ = chat_completion(client, messages=messages, models=GROQ_VISION_MODELS, max_tokens=1024, temperature=0.1)
    return text


__all__ = ["get_groq_client", "chat_completion", "cleanup_transcript", "translate_texts",
           "analyze_transcript", "extract_quotes", "chat_about_transcript", "ocr_image",
           "RateLimitedError", "NoModelAvailableError", "is_rate_limit", "is_model_error", "JOURNALIST_PROMPTS"]
