"""
Historial de transcripciones en SQLite (antes vivía en el navegador, en localStorage,
que es chico y se pierde al borrar los datos de navegación).

Funciones puras sobre una ruta de base de datos: se testean con una base temporal.
Cada transcripción se identifica por su enlace (o "whatsapp:archivo" / "video:archivo"
para archivos subidos): volver a transcribir el mismo enlace actualiza la entrada.
"""
import json
import re
import sqlite3
import time
import unicodedata
from typing import Optional

PREVIEW_CHARS = 280
SNIPPET_RADIUS = 90

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    platform TEXT,
    title TEXT,
    uploader TEXT,
    duration REAL,
    lang TEXT,
    method TEXT,
    transcript TEXT,
    raw_transcript TEXT,
    srt TEXT,
    segments TEXT,
    search_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at DESC);
"""

_LIST_COLUMNS = "id, url, platform, title, uploader, duration, lang, method, created_at, updated_at, " \
                "substr(transcript, 1, 600) AS head, length(transcript) AS tlen, " \
                "(srt IS NOT NULL AND srt != '') AS has_srt, transcript"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def normalize_search(text: str) -> str:
    """Minúsculas y sin tildes, para que 'transcripcion' encuentre 'Transcripción'."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init(db_path: str):
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def _duration_from_segments(segments) -> Optional[float]:
    try:
        return float(segments[-1].get("end") or 0) or None if segments else None
    except (AttributeError, TypeError, ValueError, IndexError):
        return None


def _word_count(text: str) -> int:
    return len((text or "").split())


def _row_summary(row: sqlite3.Row, query_norm: str = "") -> dict:
    transcript = row["transcript"] or ""
    preview = transcript[:PREVIEW_CHARS].strip()
    if len(transcript) > PREVIEW_CHARS:
        preview += "..."
    item = {
        "id": row["id"], "url": row["url"], "platform": row["platform"], "title": row["title"],
        "uploader": row["uploader"], "duration": row["duration"], "lang": row["lang"], "method": row["method"],
        "date": row["created_at"], "updated_at": row["updated_at"], "preview": preview,
        "word_count": _word_count(transcript), "has_srt": bool(row["has_srt"]),
    }
    if query_norm:
        item["snippet"] = make_snippet(transcript, query_norm)
    return item


def make_snippet(text: str, query_norm: str) -> str:
    """Fragmento del texto alrededor de la primera coincidencia (para mostrar en la búsqueda)."""
    if not text or not query_norm:
        return ""
    norm = normalize_search(text)
    # normalize_search mantiene la longitud para el español (NFKD + quitar tildes = 1 a 1),
    # salvo casos raros; si no coincide, se busca en el texto original.
    pos = norm.find(query_norm) if len(norm) == len(text) else text.lower().find(query_norm)
    if pos < 0:
        return ""
    start, end = max(0, pos - SNIPPET_RADIUS), min(len(text), pos + len(query_norm) + SNIPPET_RADIUS)
    snippet = text[start:end].replace("\n", " ").strip()
    return ("..." if start else "") + snippet + ("..." if end < len(text) else "")


def upsert(db_path: str, entry: dict) -> int:
    """Crea o actualiza (por enlace) una transcripción. Devuelve su id."""
    url = (entry.get("url") or "").strip()
    if not url:
        raise ValueError("Falta el enlace (url) de la transcripción.")
    segments = entry.get("segments") or []
    transcript = entry.get("transcript") or ""
    title = (entry.get("title") or "").strip() or url
    duration = entry.get("duration") or _duration_from_segments(segments)
    now = _now()
    created = entry.get("date") or now
    values = {
        "key": url, "url": url, "platform": entry.get("platform") or "", "title": title,
        "uploader": entry.get("uploader") or "", "duration": duration, "lang": entry.get("lang") or "",
        "method": entry.get("method") or "", "transcript": transcript,
        "raw_transcript": entry.get("raw_transcript") or "", "srt": entry.get("srt") or "",
        "segments": json.dumps(segments, ensure_ascii=False),
        "search_text": normalize_search(" ".join([title, entry.get("uploader") or "", url, transcript])),
        "created_at": created, "updated_at": now,
    }
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO history (key, url, platform, title, uploader, duration, lang, method, transcript,
                                    raw_transcript, srt, segments, search_text, created_at, updated_at)
               VALUES (:key, :url, :platform, :title, :uploader, :duration, :lang, :method, :transcript,
                       :raw_transcript, :srt, :segments, :search_text, :created_at, :updated_at)
               ON CONFLICT(key) DO UPDATE SET
                   platform = excluded.platform, title = excluded.title,
                   uploader = COALESCE(NULLIF(excluded.uploader, ''), history.uploader),
                   duration = COALESCE(excluded.duration, history.duration),
                   lang = excluded.lang, method = excluded.method, transcript = excluded.transcript,
                   raw_transcript = excluded.raw_transcript, srt = excluded.srt, segments = excluded.segments,
                   search_text = excluded.search_text, created_at = :now, updated_at = :now""",
            {**values, "now": now})
        row = conn.execute("SELECT id FROM history WHERE key = ?", (url,)).fetchone()
    return row["id"]


def list_items(db_path: str, query: str = "", limit: int = 200, offset: int = 0) -> dict:
    query_norm = normalize_search(query).strip()
    where, params = "", []
    if query_norm:
        where = "WHERE search_text LIKE ? ESCAPE '\\'"
        params.append("%" + re.sub(r"([%_\\])", r"\\\1", query_norm) + "%")
    with _connect(db_path) as conn:
        total = conn.execute(f"SELECT count(*) FROM history {where}", params).fetchone()[0]
        rows = conn.execute(f"SELECT {_LIST_COLUMNS} FROM history {where} ORDER BY created_at DESC, id DESC "
                            f"LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    return {"items": [_row_summary(r, query_norm) for r in rows], "total": total}


def get(db_path: str, item_id: int) -> Optional[dict]:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM history WHERE id = ?", (item_id,)).fetchone()
    if not row:
        return None
    try:
        segments = json.loads(row["segments"] or "[]")
    except ValueError:
        segments = []
    return {
        "id": row["id"], "url": row["url"], "platform": row["platform"], "title": row["title"],
        "uploader": row["uploader"], "duration": row["duration"], "lang": row["lang"], "method": row["method"],
        "transcript": row["transcript"] or "", "raw_transcript": row["raw_transcript"] or "",
        "srt": row["srt"] or "", "segments": segments, "date": row["created_at"], "updated_at": row["updated_at"],
    }


def update(db_path: str, item_id: int, transcript: Optional[str] = None, title: Optional[str] = None) -> bool:
    item = get(db_path, item_id)
    if not item:
        return False
    transcript = item["transcript"] if transcript is None else transcript
    title = item["title"] if title is None else (title.strip() or item["title"])
    search_text = normalize_search(" ".join([title, item["uploader"] or "", item["url"], transcript]))
    with _connect(db_path) as conn:
        conn.execute("UPDATE history SET transcript = ?, title = ?, search_text = ?, updated_at = ? WHERE id = ?",
                     (transcript, title, search_text, _now(), item_id))
    return True


def delete(db_path: str, item_id: int) -> bool:
    with _connect(db_path) as conn:
        return conn.execute("DELETE FROM history WHERE id = ?", (item_id,)).rowcount > 0


def clear(db_path: str) -> int:
    with _connect(db_path) as conn:
        return conn.execute("DELETE FROM history").rowcount


def import_items(db_path: str, items: list) -> int:
    """
    Trae el historial viejo del navegador. No pisa lo que ya está en la base
    (si un enlace ya existe, se conserva la versión del servidor). Devuelve cuántos importó.
    """
    with _connect(db_path) as conn:
        existing = {r[0] for r in conn.execute("SELECT key FROM history")}
    imported = 0
    valid = [e for e in (items or []) if isinstance(e, dict)]
    for entry in sorted(valid, key=lambda e: str(e.get("date") or "")):
        url = str(entry.get("url") or "").strip()
        if not url or url in existing or not entry.get("transcript"):
            continue
        upsert(db_path, entry)
        existing.add(url)
        imported += 1
    return imported
