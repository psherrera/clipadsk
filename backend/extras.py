"""
Funciones del motor de descarga que no son transcribir un video suelto (3.2):
ajustes guardados en la PC, listas y canales, comentarios, canales vigilados con avisos
y grabación de vivos. Acá está la lógica que se puede probar sin red; los endpoints
viven en main.py.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse

# ─── Ajustes ─────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "subtitles_mode": "auto",        # auto: subtítulos de YouTube si hay · manual: solo los del autor · never
    "comments_enabled": False,       # botón "Comentarios" en videos de YouTube
    "watch_enabled": False,          # revisar canales vigilados
    "watch_interval_min": 30,
    "watch_auto_transcribe": False,  # transcribir solo cada video nuevo
    "windows_toasts": True,          # aviso de Windows además del aviso del navegador
    "record_max_hours": 6,           # corte de seguridad de las grabaciones
}
_SETTING_RULES = {
    "subtitles_mode": lambda v: v in ("auto", "manual", "never"),
    "watch_interval_min": lambda v: isinstance(v, int) and 5 <= v <= 1440,
    "record_max_hours": lambda v: isinstance(v, (int, float)) and 0.25 <= v <= 24,
}


def _conn(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init(db: str):
    with _conn(db) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE NOT NULL, title TEXT,
                seen_ids TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL, last_check REAL,
                last_error TEXT, initialized INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS watch_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id INTEGER, channel TEXT, video_url TEXT NOT NULL,
                title TEXT, created REAL NOT NULL, job_id TEXT);
        """)


def get_settings(db: str) -> dict:
    out = dict(DEFAULT_SETTINGS)
    conn = _conn(db)
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    except sqlite3.OperationalError:  # base sin la tabla (todavía no se llamó a init)
        rows = []
    finally:
        conn.close()
    for row in rows:
        if row["key"] in out:
            try:
                out[row["key"]] = json.loads(row["value"])
            except ValueError:
                pass
    return out


def update_settings(db: str, patch: dict) -> dict:
    clean = {}
    for key, value in (patch or {}).items():
        if key not in DEFAULT_SETTINGS:
            continue
        default = DEFAULT_SETTINGS[key]
        if isinstance(default, bool):
            value = bool(value)
        elif isinstance(default, int) and not isinstance(default, bool) and isinstance(value, (int, float, str)):
            try:
                value = int(float(value)) if key != "record_max_hours" else float(value)
            except ValueError:
                raise ValueError(f"Valor inválido para {key}")
        rule = _SETTING_RULES.get(key)
        if rule and not rule(value):
            raise ValueError(f"Valor inválido para {key}")
        clean[key] = value
    with _conn(db) as conn:
        for key, value in clean.items():
            conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (key, json.dumps(value)))
    return get_settings(db)


# ─── Listas y canales ────────────────────────────────────────────────────────

_YT_CHANNEL = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")
_YT_CHANNEL_TAB = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/(videos|shorts|streams|playlists|featured)/?$")


def is_youtube(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "youtu.be" or host.endswith("youtube.com")


def looks_like_list(url: str) -> bool:
    """¿El enlace es una lista o un canal (y no un video suelto)?"""
    if not is_youtube(url):
        return False
    p = urlparse(url)
    if p.path.rstrip("/") == "/playlist" and parse_qs(p.query).get("list"):
        return True
    return bool(_YT_CHANNEL.match(p.path) or _YT_CHANNEL_TAB.match(p.path))


def list_url(url: str) -> str:
    """Canal sin pestaña → pestaña de videos (si no, YouTube devuelve las pestañas como lista)."""
    p = urlparse(url)
    if is_youtube(url) and _YT_CHANNEL.match(p.path):
        return f"https://www.youtube.com{p.path.rstrip('/')}/videos"
    m = _YT_CHANNEL_TAB.match(p.path) if is_youtube(url) else None
    if m and m.group(2) == "featured":
        return f"https://www.youtube.com/{m.group(1)}/videos"
    return url


def entry_url(entry: dict) -> Optional[str]:
    url = entry.get("url") or entry.get("webpage_url")
    if url and url.startswith("http"):
        return url
    vid = entry.get("id")
    if vid and (entry.get("ie_key") or "").lower().startswith("youtube"):
        return f"https://www.youtube.com/watch?v={vid}"
    return url


def normalize_entries(info: dict, limit: int = 200) -> list:
    """Entradas de una lista de yt-dlp (extract_flat) → [{id, url, title, duration, thumbnail, live}]."""
    out = []
    for e in info.get("entries") or []:
        if not isinstance(e, dict):
            continue
        if e.get("_type") == "playlist" and e.get("entries"):  # pestañas anidadas
            out += normalize_entries(e, limit - len(out))
            continue
        url = entry_url(e)
        if not url:
            continue
        thumbs = e.get("thumbnails") or []
        thumb = e.get("thumbnail") or (thumbs[-1].get("url") if thumbs and isinstance(thumbs[-1], dict) else None)
        out.append({"id": e.get("id") or url, "url": url, "title": e.get("title") or url,
                    "duration": e.get("duration"), "thumbnail": thumb,
                    "live": e.get("live_status") in ("is_live", "is_upcoming") or bool(e.get("is_live"))})
        if len(out) >= limit:
            break
    return out


# ─── Comentarios ─────────────────────────────────────────────────────────────

def normalize_comments(info: dict, limit: int) -> list:
    out = []
    for c in info.get("comments") or []:
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        out.append({"author": c.get("author") or "Anónimo", "text": text, "likes": c.get("like_count") or 0,
                    "when": c.get("_time_text") or "", "timestamp": c.get("timestamp"),
                    "reply": c.get("parent") not in (None, "root"), "pinned": bool(c.get("is_pinned")),
                    "by_uploader": bool(c.get("author_is_uploader"))})
        if len(out) >= limit:
            break
    return out


def comments_as_text(title: str, url: str, comments: list) -> str:
    lines = [f"Comentarios de: {title}", url, ""]
    for c in comments:
        mark = "  ↳ " if c["reply"] else ""
        extra = " · autor del video" if c["by_uploader"] else ""
        lines.append(f"{mark}{c['author']} ({c['likes']} me gusta{extra}{' · ' + c['when'] if c['when'] else ''}):")
        lines.append(f"{mark}{c['text']}")
        lines.append("")
    return "\n".join(lines)


# ─── Canales vigilados ───────────────────────────────────────────────────────

def list_watches(db: str) -> list:
    with _conn(db) as conn:
        rows = conn.execute("SELECT id, url, title, created, last_check, last_error, seen_ids FROM watches ORDER BY id").fetchall()
    return [{"id": r["id"], "url": r["url"], "title": r["title"] or r["url"], "created": r["created"],
             "last_check": r["last_check"], "last_error": r["last_error"], "known": len(json.loads(r["seen_ids"] or "[]"))}
            for r in rows]


def add_watch(db: str, url: str, title: str = "") -> int:
    with _conn(db) as conn:
        row = conn.execute("SELECT id FROM watches WHERE url = ?", (url,)).fetchone()
        if row:
            return row["id"]
        return conn.execute("INSERT INTO watches(url, title, created) VALUES(?, ?, ?)", (url, title, time.time())).lastrowid


def delete_watch(db: str, watch_id: int):
    with _conn(db) as conn:
        conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))


def due_watches(db: str, interval_min: int, now: Optional[float] = None) -> list:
    now = now or time.time()
    with _conn(db) as conn:
        rows = conn.execute("SELECT id, url, title FROM watches WHERE last_check IS NULL OR last_check <= ?",
                            (now - interval_min * 60,)).fetchall()
    return [dict(r) for r in rows]


def record_check(db: str, watch_id: int, entries: list, title: str = "", error: str = "") -> list:
    """Guarda el resultado de una revisión y devuelve los videos nuevos (eventos creados).
    La primera revisión solo toma nota de lo que ya había: no avisa de videos viejos."""
    now = time.time()
    with _conn(db) as conn:
        row = conn.execute("SELECT seen_ids, initialized, title FROM watches WHERE id = ?", (watch_id,)).fetchone()
        if not row:
            return []
        if error:
            conn.execute("UPDATE watches SET last_check = ?, last_error = ? WHERE id = ?", (now, error[:300], watch_id))
            return []
        seen = json.loads(row["seen_ids"] or "[]")
        seen_set = set(seen)
        fresh = [e for e in entries if e["id"] not in seen_set]
        channel = title or row["title"] or ""
        events = []
        if row["initialized"]:
            for e in reversed(fresh):  # del más viejo al más nuevo
                eid = conn.execute("INSERT INTO watch_events(watch_id, channel, video_url, title, created) VALUES(?,?,?,?,?)",
                                   (watch_id, channel, e["url"], e["title"], now)).lastrowid
                events.append({"id": eid, "watch_id": watch_id, "channel": channel, "url": e["url"], "title": e["title"]})
        seen = ([e["id"] for e in fresh] + seen)[:500]
        conn.execute("UPDATE watches SET seen_ids = ?, last_check = ?, last_error = NULL, initialized = 1, title = ? WHERE id = ?",
                     (json.dumps(seen), now, channel, watch_id))
    return events


def set_event_job(db: str, event_id: int, job_id: str):
    with _conn(db) as conn:
        conn.execute("UPDATE watch_events SET job_id = ? WHERE id = ?", (job_id, event_id))


def list_events(db: str, after: int = 0, limit: int = 50) -> list:
    with _conn(db) as conn:
        rows = conn.execute("SELECT id, watch_id, channel, video_url, title, created, job_id FROM watch_events "
                            "WHERE id > ? ORDER BY id DESC LIMIT ?", (after, limit)).fetchall()
    return [{"id": r["id"], "watch_id": r["watch_id"], "channel": r["channel"], "url": r["video_url"],
             "title": r["title"], "created": r["created"], "job_id": r["job_id"]} for r in rows]


def windows_toast(title: str, body: str) -> bool:
    """Aviso nativo de Windows (sin módulos extra). Devuelve False si no se pudo."""
    if os.name != "nt":
        return False

    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "''")[:200]
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
        f"$xml = '<toast><visual><binding template=\"ToastGeneric\"><text>{esc(title)}</text><text>{esc(body)}</text>"
        "</binding></visual></toast>';"
        "$doc = New-Object Windows.Data.Xml.Dom.XmlDocument; $doc.LoadXml($xml);"
        "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
        "[Windows.UI.Notifications.ToastNotification]::new($doc))"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


# ─── Grabación de vivos ──────────────────────────────────────────────────────

def ytdlp_command(home_dirs: tuple) -> Optional[list]:
    """yt-dlp como programa aparte (hace falta para poder cortar la grabación cuando se pide)."""
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "yt_dlp"]
    for d in home_dirs:
        exe = os.path.join(d, "yt-dlp.exe")
        if os.path.exists(exe):
            return [exe]
    return None


def record_args(url: str, out_base: str, from_start: bool, cookies: Optional[str], max_height: int = 720) -> list:
    """Argumentos de yt-dlp para grabar un vivo en un archivo que sirve aunque se corte en el medio."""
    args = ["--no-part", "--hls-use-mpegts", "--downloader", "m3u8:native", "--no-playlist", "--newline",
            "--no-colors", "--no-mtime", "-f", f"best[height<={max_height}]/bestvideo[height<={max_height}]+bestaudio/best",
            "-o", out_base + ".%(ext)s"]
    if from_start:
        args.append("--live-from-start")
    if cookies:
        args += ["--cookies", cookies]
    return args + [url]


def kill_tree(proc: subprocess.Popen):
    """Corta yt-dlp (y lo que haya lanzado). En Windows terminate() no mata los hijos."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
