"""
Clipa para Claude (servidor MCP).

Le da a Claude Desktop herramientas que usan el Clipadsk de esta PC: transcribir enlaces y
archivos, buscar en el historial, traducir, resumir y sacar citas. El trabajo pesado
(descargar, transcribir con Groq/Whisper, traducir) lo hace Clipa; a Claude le llega solo
el texto final, así no gasta tokens ni tiempo en eso.

Se instala con INSTALAR_MCP.bat. Variables opcionales (en la configuración de Claude Desktop):
  CLIPA_URL       dirección de Clipadsk (por defecto http://127.0.0.1:5000)
  CLIPA_DIR       carpeta de Clipadsk, para abrirlo solo si está cerrado
  CLIPA_GROQ_KEY  key de Groq, si no está en el .env de Clipadsk
"""
import asyncio
import contextlib
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

try:  # mcp 2.x
    from mcp.server.mcpserver import Context, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import Context, FastMCP as _Server

logging.getLogger("httpx").setLevel(logging.WARNING)

CLIPA_URL = os.environ.get("CLIPA_URL", "http://127.0.0.1:5000").rstrip("/")
API = CLIPA_URL + "/api"
CLIPA_DIR = os.environ.get("CLIPA_DIR") or str(Path(__file__).resolve().parent.parent)
GROQ_KEY = os.environ.get("CLIPA_GROQ_KEY") or None
LANGS = {"es": "es", "español": "es", "en": "en", "inglés": "en", "ingles": "en", "original": "original"}
ANALYSIS = {"resumen": "summary", "datos": "data", "angulos": "angle", "ángulos": "angle", "hablantes": "diarization"}

mcp = _Server(
    "clipa",
    instructions=(
        "Clipa es la herramienta de transcripción del usuario (periodista). Para transcribir, traducir o resumir "
        "audios y videos (YouTube, Instagram, TikTok, X, Facebook, Drive, archivos de la PC, notas de WhatsApp) "
        "usá estas herramientas en lugar de hacerlo vos: el trabajo lo hace Clipa en la PC del usuario. "
        "Para resúmenes, datos o citas de una transcripción larga preferí `analizar` y `citas` (las hace Clipa) "
        "antes que leer el texto completo. Todo lo transcripto queda en el historial de Clipa."
    ),
)


# ─── Conexión con Clipadsk ───────────────────────────────────────────────────

class ClipaError(Exception):
    pass


async def _alive(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get(f"{API}/health", timeout=3)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _start_clipa() -> bool:
    """Abre Clipadsk sin navegador (Clipa.exe o la instalación de backend/venv)."""
    root = Path(CLIPA_DIR)
    exe = root / "Clipa.exe"
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    common = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    if exe.exists():
        subprocess.Popen([str(exe), "--sin-navegador"], cwd=str(root), **common)
        return True
    for py in (root / "backend/venv/Scripts/pythonw.exe", root / "backend/venv/Scripts/python.exe",
               root / "backend/venv/bin/python"):
        if py.exists():
            subprocess.Popen([str(py), str(root / "backend/main.py")], cwd=str(root / "backend"), **common)
            return True
    return False


@contextlib.asynccontextmanager
async def clipa():
    """Cliente HTTP conectado a Clipadsk (lo abre si está cerrado)."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=900), trust_env=False) as client:
        if not await _alive(client):
            started = _start_clipa()
            for _ in range(90 if started else 0):
                await asyncio.sleep(1)
                if await _alive(client):
                    break
            else:
                raise ClipaError(f"Clipadsk no está abierto en {CLIPA_URL}. Abrilo (Clipa.exe o iniciar.bat) y probá de nuevo.")
        yield client


async def _call(client: httpx.AsyncClient, method: str, path: str, **kw):
    r = await client.request(method, API + path, **kw)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail") or r.text
        except ValueError:
            detail = r.text
        raise ClipaError(str(detail)[:600])
    return r


def _fmt_time(sec) -> str:
    sec = int(float(sec or 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _with_times(segments: list) -> str:
    return "\n".join(f"[{_fmt_time(s.get('start'))}] {str(s.get('text', '')).strip()}" for s in segments or [])


def _cut(text: str, max_chars: int) -> str:
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + f"\n\n[... recortado: {len(text) - max_chars} caracteres más. Pedí más con max_caracteres=0]"
    return text


def _render(item: dict, con_tiempos: bool, max_caracteres: int) -> str:
    body = _with_times(item.get("segments") or []) if con_tiempos and item.get("segments") else (item.get("transcript") or "")
    head = [f"Título: {item.get('title') or '(sin título)'}"]
    if item.get("uploader"):
        head.append(f"Autor/canal: {item['uploader']}")
    if item.get("url"):
        head.append(f"Fuente: {item['url']}")
    if item.get("duration"):
        head.append(f"Duración: {_fmt_time(item['duration'])}")
    if item.get("id") or item.get("history_id"):
        head.append(f"ID en el historial de Clipa: {item.get('id') or item.get('history_id')}")
    return "\n".join(head) + "\n\n" + _cut(body.strip(), max_caracteres)


def _lang(idioma: str) -> str:
    lang = LANGS.get((idioma or "es").strip().lower())
    if not lang:
        raise ClipaError("idioma tiene que ser 'es', 'en' u 'original'.")
    return lang


async def _transcript_text(client, id_historial: Optional[int], texto: Optional[str]) -> tuple:
    """(texto, segmentos) desde el historial o del texto dado."""
    if id_historial:
        item = (await _call(client, "GET", f"/history/{int(id_historial)}")).json()
        return item.get("transcript") or "", item.get("segments") or []
    if texto and texto.strip():
        return texto, []
    raise ClipaError("Pasá id_historial (de una transcripción de Clipa) o texto.")


def _safe(fn):
    """Devuelve los errores de Clipa como texto claro en vez de un error de protocolo."""
    import functools

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except ClipaError as e:
            msg = f"Clipa no pudo hacerlo: {e}"
            if "Groq" in str(e) and ("configur" in str(e) or "API Key" in str(e)):
                msg += (" Para usar Clipa desde Claude, la key de Groq tiene que estar en el archivo .env de Clipadsk "
                        "(GROQ_API_KEY=...) o en CLIPA_GROQ_KEY de la configuración de Claude Desktop.")
            return msg
        except httpx.HTTPError as e:
            return f"No hubo respuesta de Clipadsk ({CLIPA_URL}): {e}"
    return wrapper


# ─── Herramientas ────────────────────────────────────────────────────────────

@mcp.tool()
@_safe
async def transcribir_enlace(url: str, idioma: str = "es", con_tiempos: bool = False,
                             max_caracteres: int = 0, espera_max_segundos: int = 600,
                             ctx: Context = None) -> str:
    """Transcribe un video o audio de internet con Clipa (YouTube, Instagram, TikTok, X, Facebook, Drive y más).

    idioma: "es" (traduce al español), "en" (al inglés) u "original" (sin traducir).
    con_tiempos: True para devolver cada frase con su minuto [mm:ss].
    max_caracteres: 0 = todo el texto; un número para recibir solo el principio.
    Si tarda más que espera_max_segundos devuelve el número de trabajo para consultarlo con resultado_trabajo.
    """
    async with clipa() as client:
        payload = {"url": url, "target_lang": _lang(idioma)}
        if GROQ_KEY:
            payload["groq_api_key"] = GROQ_KEY
        job = (await _call(client, "POST", "/jobs", json=payload)).json()
        return await _wait_job(client, job["id"], con_tiempos, max_caracteres, espera_max_segundos, ctx)


async def _wait_job(client, job_id: str, con_tiempos: bool, max_caracteres: int, espera: int, ctx) -> str:
    deadline = time.time() + max(10, espera)
    while True:
        job = (await _call(client, "GET", f"/jobs/{job_id}")).json()
        if job["status"] == "done":
            res = job.get("result") or {}
            res.setdefault("url", job.get("url"))
            text = _render(res, con_tiempos, max_caracteres)
            if res.get("warnings"):
                text += "\n\nAvisos de Clipa: " + " / ".join(map(str, res["warnings"]))
            return text
        if job["status"] == "error":
            raise ClipaError(job.get("error") or "falló la transcripción")
        if time.time() > deadline:
            return (f"La transcripción sigue en curso ({job.get('progress', 0)} %: {job.get('text', '')}). "
                    f"Número de trabajo: {job_id}. Consultalo con resultado_trabajo.")
        if ctx is not None:
            try:
                await ctx.report_progress(float(job.get("progress") or 0), 100.0, job.get("text") or "Procesando")
            except Exception:
                pass
        await asyncio.sleep(2)


@mcp.tool()
@_safe
async def resultado_trabajo(trabajo_id: str, con_tiempos: bool = False, max_caracteres: int = 0,
                            espera_max_segundos: int = 600, ctx: Context = None) -> str:
    """Espera y devuelve el resultado de una transcripción que quedó en curso (por número de trabajo)."""
    async with clipa() as client:
        return await _wait_job(client, trabajo_id, con_tiempos, max_caracteres, espera_max_segundos, ctx)


@mcp.tool()
@_safe
async def transcribir_archivo(ruta: str, idioma: str = "es", con_tiempos: bool = False,
                              max_caracteres: int = 0) -> str:
    """Transcribe un archivo de audio o video de esta PC (mp3, m4a, wav, ogg/opus de WhatsApp, mp4, mov, mkv...).

    ruta: ruta completa del archivo, por ejemplo C:\\Users\\yo\\Downloads\\entrevista.mp3
    El resultado queda guardado en el historial de Clipa.
    """
    path = Path(ruta.strip().strip('"')).expanduser()
    if not path.is_file():
        raise ClipaError(f"No existe el archivo {path}")
    async with clipa() as client:
        data = {"target_lang": _lang(idioma)}
        if GROQ_KEY:
            data["groq_api_key"] = GROQ_KEY
        is_video = path.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm")
        if is_video:
            data["is_local_video"] = "true"
        with path.open("rb") as f:
            res = (await _call(client, "POST", "/transcript-file", data=data,
                               files={"file": (path.name, f, "application/octet-stream")})).json()
        transcript = res.get("transcript") or res.get("text") or ""
        entry = {"url": f"archivo:{path.name}", "title": path.name, "platform": "video" if is_video else "whatsapp",
                 "lang": data["target_lang"], "transcript": transcript, "segments": res.get("segments") or [],
                 "srt": res.get("srt") or "", "raw_transcript": res.get("raw_transcript") or ""}
        try:
            saved = (await _call(client, "POST", "/history", json=entry)).json()
            res["history_id"] = saved.get("id")
        except ClipaError:
            pass
        res.update(title=path.name, transcript=transcript)
        return _render(res, con_tiempos, max_caracteres)


@mcp.tool()
@_safe
async def buscar_historial(consulta: str = "", limite: int = 10) -> str:
    """Busca en el historial de Clipa por título o por lo que se dijo (sin importar tildes). Vacío = las últimas."""
    async with clipa() as client:
        data = (await _call(client, "GET", "/history", params={"q": consulta, "limit": max(1, min(limite, 50))})).json()
    items = data.get("items") or []
    if not items:
        return "No hay transcripciones que coincidan." if consulta else "El historial está vacío."
    lines = [f"{data.get('total', len(items))} resultado(s):"]
    for it in items:
        date = str(it.get("created_at") or it.get("date") or "")[:10]
        dur = f" · {_fmt_time(it['duration'])}" if it.get("duration") else ""
        snippet = re.sub(r"\s+", " ", str(it.get("snippet") or it.get("preview") or ""))[:160]
        lines.append(f"- ID {it['id']} · {it.get('title') or '(sin título)'} · {date}{dur}\n  {snippet}")
    return "\n".join(lines)


@mcp.tool()
@_safe
async def leer_transcripcion(id_historial: int, con_tiempos: bool = False, max_caracteres: int = 0) -> str:
    """Devuelve una transcripción guardada en Clipa (por su ID del historial)."""
    async with clipa() as client:
        item = (await _call(client, "GET", f"/history/{int(id_historial)}")).json()
    return _render(item, con_tiempos, max_caracteres)


@mcp.tool()
@_safe
async def analizar(modo: str = "resumen", id_historial: Optional[int] = None, texto: Optional[str] = None) -> str:
    """Analiza una transcripción con la IA de Clipa (Groq), sin gastar a Claude.

    modo: "resumen", "datos" (datos duros: cifras, nombres, fechas), "angulos" (ángulos periodísticos)
    o "hablantes" (separa quién dice qué). Pasá id_historial o texto.
    """
    mode = ANALYSIS.get((modo or "").strip().lower())
    if not mode:
        raise ClipaError("modo tiene que ser resumen, datos, angulos o hablantes.")
    async with clipa() as client:
        transcript, _ = await _transcript_text(client, id_historial, texto)
        body = {"transcript": transcript, "mode": mode}
        if GROQ_KEY:
            body["groq_api_key"] = GROQ_KEY
        return (await _call(client, "POST", "/analyze", json=body)).json().get("result") or "(sin resultado)"


@mcp.tool()
@_safe
async def citas(id_historial: int) -> str:
    """Saca las citas textuales más fuertes de una transcripción de Clipa, con su minuto en el video."""
    async with clipa() as client:
        item = (await _call(client, "GET", f"/history/{int(id_historial)}")).json()
        body = {"transcript": item.get("transcript") or "", "segments": item.get("segments") or []}
        if GROQ_KEY:
            body["groq_api_key"] = GROQ_KEY
        res = (await _call(client, "POST", "/quotes", json=body)).json()
    out = []
    for q in res.get("quotes") or []:
        when = f"[{_fmt_time(q['start'])}] " if q.get("has_time") else ""
        note = f" — {q['note']}" if q.get("note") else ""
        out.append(f"{when}«{q['quote']}»{note}")
    return "\n".join(out) or "No se encontraron citas."


@mcp.tool()
@_safe
async def traducir(idioma: str = "es", id_historial: Optional[int] = None, texto: Optional[str] = None) -> str:
    """Traduce con el traductor de Clipa (no usa tokens de Claude). idioma: es, en, pt, fr, it o de.

    Con id_historial traduce frase por frase y conserva los minutos; con texto traduce párrafo por párrafo.
    """
    target = (idioma or "es").strip().lower()[:2]
    async with clipa() as client:
        transcript, segments = await _transcript_text(client, id_historial, texto)
        parts = [str(s.get("text", "")) for s in segments] if segments else [p for p in re.split(r"\n\s*\n|\n", transcript) if p.strip()]
        out: list = []
        for i in range(0, len(parts), 400):
            out += (await _call(client, "POST", "/translate-segments", json={"texts": parts[i:i + 400], "target": target})).json()["texts"]
    if out == parts:
        return "El traductor de Clipa no respondió (¿sin internet?): el texto quedó sin traducir."
    if segments:
        return "\n".join(f"[{_fmt_time(s.get('start'))}] {t}" for s, t in zip(segments, out))
    return "\n\n".join(out)


@mcp.tool()
@_safe
async def info_enlace(url: str) -> str:
    """Datos de un enlace sin descargarlo: título, autor, duración, formatos y si es un carrusel."""
    async with clipa() as client:
        d = (await _call(client, "POST", "/video-info", json={"url": url})).json()
    lines = [f"Título: {d.get('title')}", f"Autor: {d.get('uploader')}"]
    if d.get("duration"):
        lines.append(f"Duración: {_fmt_time(d['duration'])}")
    if d.get("carousel"):
        n_vid = sum(1 for c in d["carousel"] if c.get("is_video"))
        lines.append(f"Carrusel de {len(d['carousel'])} archivos ({n_vid} videos)")
    lines.append("Formatos: " + ", ".join(f.get("label", f.get("format_id", "")) for f in d.get("formats") or []))
    if d.get("description"):
        lines.append(f"Descripción: {str(d['description'])[:800]}")
    return "\n".join(lines)


@mcp.tool()
@_safe
async def descargar(url: str, carpeta: str = "", formato: str = "best") -> str:
    """Descarga un video/audio (o un carrusel completo en .zip) a una carpeta de la PC.

    formato: "best" (mejor calidad mp4) o "mp3" (solo audio). carpeta: por defecto Descargas.
    """
    dest_dir = Path(carpeta.strip().strip('"')).expanduser() if carpeta.strip() else Path.home() / "Downloads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    async with clipa() as client:
        fmt = formato
        info = (await _call(client, "POST", "/video-info", json={"url": url})).json()
        if info.get("carousel"):
            fmt = "carousel_images"
        async with client.stream("POST", f"{API}/download", json={"url": url, "format_id": fmt}) as r:
            if r.status_code >= 400:
                await r.aread()
                try:
                    raise ClipaError(r.json().get("detail") or r.text)
                except ValueError:
                    raise ClipaError(r.text[:400])
            cd = r.headers.get("content-disposition", "")
            m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
            from urllib.parse import unquote
            name = unquote(m.group(1)) if m else "clipa_descarga"
            name = re.sub(r'[\\/:*?"<>|]', "_", name)
            path = dest_dir / name
            with path.open("wb") as f:
                async for chunk in r.aiter_bytes(1 << 16):
                    f.write(chunk)
    return f"Descargado: {path} ({path.stat().st_size / 1_048_576:.1f} MB)"


def main():
    if "--probar" in sys.argv:  # chequeo rápido desde la consola
        async def check():
            async with clipa() as c:
                print((await _call(c, "GET", "/health")).json())
        asyncio.run(check())
        return
    mcp.run()


if __name__ == "__main__":
    main()
