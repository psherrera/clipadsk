"""3.2: ajustes, listas y canales, comentarios, canales vigilados y grabación de vivos."""
import asyncio
import os
import shutil
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

import extras
import history as hist
import main

client = TestClient(main.app)
HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "x.db")
    hist.init(path)
    extras.init(path)
    monkeypatch.setattr(main, "DB_FILE", path)
    return path


@pytest.fixture
def live():
    with TestClient(main.app) as c:
        yield c


async def _same(url):
    return url


# ─── Ajustes ────────────────────────────────────────────────────────────────

def test_settings_defaults_and_update(db):
    assert client.get("/api/settings").json() == extras.DEFAULT_SETTINGS
    r = client.put("/api/settings", json={"comments_enabled": True, "watch_interval_min": "15", "otra": 1})
    assert r.status_code == 200
    s = r.json()
    assert s["comments_enabled"] is True and s["watch_interval_min"] == 15 and "otra" not in s
    assert client.put("/api/settings", json={"subtitles_mode": "siempre"}).status_code == 400
    assert client.put("/api/settings", json={"watch_interval_min": 1}).status_code == 400
    assert extras.get_settings(db)["comments_enabled"] is True


def test_settings_without_tables_returns_defaults(tmp_path):
    assert extras.get_settings(str(tmp_path / "vacia.db")) == extras.DEFAULT_SETTINGS


def test_subtitles_mode_never_skips_subtitles(db, monkeypatch):
    extras.update_settings(db, {"subtitles_mode": "never"})
    called = []
    monkeypatch.setattr(main, "detect_bunny_embed", lambda u: None)
    monkeypatch.setattr(main, "cache_get", lambda k: None)
    monkeypatch.setattr(main, "cache_set", lambda k, v: None)
    monkeypatch.setattr(main, "transcribe_from_subtitles", lambda *a: called.append("subs") or None)
    monkeypatch.setattr(main, "transcribe_from_audio", lambda *a: {"raw": "hola a todos los que miran", "segments": [], "method": "groq"})
    monkeypatch.setattr(main.ai, "get_groq_client", lambda k=None: None)
    r = client.post("/api/transcript", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"})
    assert r.status_code == 200 and not called


def test_subtitles_mode_manual_disables_auto_captions(db, monkeypatch):
    extras.update_settings(db, {"subtitles_mode": "manual"})
    seen = {}
    monkeypatch.setattr(main, "detect_bunny_embed", lambda u: None)
    monkeypatch.setattr(main, "cache_get", lambda k: None)
    monkeypatch.setattr(main, "cache_set", lambda k, v: None)

    def fake_subs(url, lang, tmp, uid, auto):
        seen["auto"] = auto
        return {"raw": "texto de subtitulos del autor", "segments": [], "method": "subtitles"}
    monkeypatch.setattr(main, "transcribe_from_subtitles", fake_subs)
    monkeypatch.setattr(main.ai, "get_groq_client", lambda k=None: None)
    assert client.post("/api/transcript", json={"url": "https://www.youtube.com/watch?v=abcdefghijk"}).status_code == 200
    assert seen["auto"] is False


# ─── Listas y canales ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/playlist?list=PL123", True),
    ("https://www.youtube.com/@diario", True),
    ("https://www.youtube.com/@diario/videos", True),
    ("https://www.youtube.com/channel/UC123/streams", True),
    ("https://www.youtube.com/@diario/live", False),           # el vivo actual es un video
    ("https://www.youtube.com/watch?v=abc&list=PL123", False),  # video dentro de una lista
    ("https://youtu.be/abc", False),
    ("https://vimeo.com/channels/staffpicks", False),
])
def test_looks_like_list(url, expected):
    assert extras.looks_like_list(url) is expected


def test_list_url_uses_videos_tab():
    assert extras.list_url("https://www.youtube.com/@diario") == "https://www.youtube.com/@diario/videos"
    assert extras.list_url("https://www.youtube.com/@diario/featured") == "https://www.youtube.com/@diario/videos"
    assert extras.list_url("https://www.youtube.com/@diario/streams") == "https://www.youtube.com/@diario/streams"


def test_normalize_entries_flat_and_nested():
    info = {"entries": [
        {"id": "a1", "url": "https://www.youtube.com/watch?v=a1", "title": "Uno", "duration": 60,
         "thumbnails": [{"url": "t1"}, {"url": "t2"}]},
        {"id": "b2", "ie_key": "Youtube", "title": "Dos", "live_status": "is_live"},
        {"_type": "playlist", "entries": [{"id": "c3", "url": "https://www.youtube.com/watch?v=c3", "title": "Tres"}]},
        None, {"title": "sin url"},
    ]}
    out = extras.normalize_entries(info)
    assert [e["id"] for e in out] == ["a1", "b2", "c3"]
    assert out[0]["thumbnail"] == "t2" and out[1]["url"] == "https://www.youtube.com/watch?v=b2" and out[1]["live"]
    assert len(extras.normalize_entries(info, limit=2)) == 2


def test_video_info_returns_playlist(monkeypatch):
    monkeypatch.setattr(main, "resolve_url", _same)
    monkeypatch.setattr(main, "extract_list", lambda url, limit=200: {
        "title": "Entrevistas", "uploader": "Diario", "entries": [{"id": "v1", "url": "https://www.youtube.com/watch?v=v1", "title": "Ministro"}]})
    r = client.post("/api/video-info", json={"url": "https://www.youtube.com/playlist?list=PL1"})
    assert r.status_code == 200
    d = r.json()
    assert d["playlist"][0]["title"] == "Ministro" and d["can_transcribe"] is False


# ─── Comentarios ────────────────────────────────────────────────────────────

def test_comments_endpoint(monkeypatch):
    monkeypatch.setattr(main, "resolve_url", _same)
    info = {"title": "Debate", "comment_count": 3, "comments": [
        {"author": "@ana", "text": "Muy bueno", "like_count": 12, "parent": "root", "_time_text": "hace 2 días"},
        {"author": "@canal", "text": "Gracias", "parent": "x1", "author_is_uploader": True},
        {"author": "@vacio", "text": "  "},
    ]}

    class FakeYDL:
        def __init__(self, opts):
            assert opts["getcomments"] is True
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def extract_info(self, url, download=False):
            return info
    monkeypatch.setattr(main.yt_dlp, "YoutubeDL", FakeYDL)
    r = client.post("/api/comments", json={"url": "https://www.youtube.com/watch?v=x", "limit": 50})
    assert r.status_code == 200
    d = r.json()
    assert [c["author"] for c in d["comments"]] == ["@ana", "@canal"]
    assert d["comments"][1]["reply"] and d["comments"][1]["by_uploader"]
    assert "↳ @canal" in d["text"] and "12 me gusta" in d["text"]


# ─── Canales vigilados ──────────────────────────────────────────────────────

def _entries(*ids):
    return [{"id": i, "url": f"https://www.youtube.com/watch?v={i}", "title": f"Video {i}"} for i in ids]


def test_record_check_first_time_does_not_notify(db):
    wid = extras.add_watch(db, "https://www.youtube.com/@diario", "Diario")
    assert extras.record_check(db, wid, _entries("a", "b")) == []
    events = extras.record_check(db, wid, _entries("c", "d", "a", "b"), "Diario")
    assert [e["title"] for e in events] == ["Video d", "Video c"]  # del más viejo al más nuevo
    assert extras.record_check(db, wid, _entries("c", "d", "a", "b")) == []
    assert [e["title"] for e in extras.list_events(db)] == ["Video c", "Video d"]
    assert extras.list_events(db, after=events[0]["id"])[0]["title"] == "Video c"


def test_record_check_error_keeps_state(db):
    wid = extras.add_watch(db, "https://www.youtube.com/@x")
    extras.record_check(db, wid, [], error="sin conexión")
    w = extras.list_watches(db)[0]
    assert w["last_error"] == "sin conexión" and w["last_check"]


def test_due_watches_respects_interval(db):
    wid = extras.add_watch(db, "https://www.youtube.com/@x")
    assert len(extras.due_watches(db, 30)) == 1
    extras.record_check(db, wid, _entries("a"))
    assert extras.due_watches(db, 30) == []
    assert len(extras.due_watches(db, 30, now=time.time() + 31 * 60)) == 1


def test_watch_endpoints(db, monkeypatch):
    calls = {"n": 0}

    def fake_list(url, limit=200):
        calls["n"] += 1
        ids = ("a", "b") if calls["n"] == 1 else ("z", "a", "b")
        return {"uploader": "Diario", "entries": _entries(*ids)}
    monkeypatch.setattr(main, "extract_list", fake_list)
    monkeypatch.setattr(main.extras, "windows_toast", lambda *a: True)
    assert client.post("/api/watch", json={"url": "https://youtu.be/abc"}).status_code == 400
    r = client.post("/api/watch", json={"url": "https://www.youtube.com/@diario"})
    assert r.status_code == 200 and r.json()["title"] == "Diario"
    r = client.post("/api/watch/check")
    assert r.json()["new"] == 1 and r.json()["events"][0]["title"] == "Video z"
    assert client.get("/api/watch/events").json()["events"][0]["url"].endswith("v=z")
    wid = client.get("/api/watch").json()["watches"][0]["id"]
    assert client.delete(f"/api/watch/{wid}").json()["watches"] == []


def test_watch_auto_transcribe_queues_job(db, monkeypatch, live):
    extras.update_settings(db, {"watch_auto_transcribe": True, "windows_toasts": False})
    wid = extras.add_watch(db, "https://www.youtube.com/@diario")
    extras.record_check(db, wid, _entries("a"))
    monkeypatch.setattr(main, "extract_list", lambda url, limit=200: {"uploader": "Diario", "entries": _entries("n", "a")})

    async def fake_transcribe(url, lang, key, uid):
        return {"transcript": "Texto.", "raw_transcript": "texto", "srt": "", "method": "x", "segments": []}
    monkeypatch.setattr(main, "transcribe_url", fake_transcribe)
    monkeypatch.setattr(main, "_fill_job_metadata", lambda job: asyncio.sleep(0))
    r = live.post("/api/watch/check").json()
    assert r["new"] == 1 and r["events"][0]["job_id"]
    job_id = r["events"][0]["job_id"]
    for _ in range(100):
        job = live.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "done":
            break
        time.sleep(0.05)
    assert job["status"] == "done" and job["title"] == "Video n"


# ─── Grabar vivos ───────────────────────────────────────────────────────────

FAKE_YTDLP = r'''
import os, shutil, sys, time
args = sys.argv[1:]
out = args[args.index("-o") + 1].replace("%(ext)s", "mp4")
src = os.environ["CLIPA_TEST_TS"]
mode = os.environ.get("CLIPA_TEST_MODE", "forever")
shutil.copy(src, out)
if mode == "end":
    sys.exit(0)
if mode == "fail":
    os.remove(out)
    print("ERROR: [youtube] abc: This live event has ended.")
    sys.exit(1)
while True:
    time.sleep(0.2)
'''


@pytest.fixture
def fake_record(tmp_path, monkeypatch, db):
    if not HAS_FFMPEG:
        pytest.skip("sin ffmpeg")
    ts = tmp_path / "muestra.ts"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac", "-f", "mpegts",
                    str(ts)], check=True)
    script = tmp_path / "fake_ytdlp.py"
    script.write_text(FAKE_YTDLP)
    monkeypatch.setenv("CLIPA_TEST_TS", str(ts))
    monkeypatch.setattr(main.extras, "ytdlp_command", lambda dirs: [sys.executable, str(script)])
    monkeypatch.setattr(main, "resolve_url", _same)
    monkeypatch.setattr(main, "ytdlp_extract", lambda url, extra=None: {"title": "Sesión en vivo", "live_status": "is_live", "uploader": "Congreso"})
    rec_dir = tmp_path / "grabaciones"
    rec_dir.mkdir()
    monkeypatch.setattr(main, "RECORD_DIR", str(rec_dir))
    return rec_dir


def _wait(c, job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.1)
    raise AssertionError("no terminó")


def test_record_stop_saves_mp4(fake_record, live):
    r = live.post("/api/record", json={"url": "https://www.youtube.com/watch?v=vivo"})
    assert r.status_code == 200
    job_id = r.json()["id"]
    time.sleep(1.5)
    running = live.get(f"/api/jobs/{job_id}").json()
    assert running["status"] == "running" and "Grabando" in running["text"]
    assert live.post(f"/api/jobs/{job_id}/stop").status_code == 200
    job = _wait(live, job_id)
    assert job["status"] == "done", job
    assert job["result"]["file"].endswith(".mp4")
    f = live.get(f"/api/record/{job_id}/file")
    assert f.status_code == 200 and len(f.content) > 1000
    assert not [x for x in os.listdir(fake_record) if x.startswith(".grabando")]


def test_record_ends_when_live_ends(fake_record, live, monkeypatch):
    monkeypatch.setenv("CLIPA_TEST_MODE", "end")
    job_id = live.post("/api/record", json={"url": "https://www.youtube.com/watch?v=vivo"}).json()["id"]
    job = _wait(live, job_id)
    assert job["status"] == "done" and job["result"]["file"].startswith("Sesi")


def test_record_failure_is_reported(fake_record, live, monkeypatch):
    monkeypatch.setenv("CLIPA_TEST_MODE", "fail")
    job_id = live.post("/api/record", json={"url": "https://www.youtube.com/watch?v=vivo"}).json()["id"]
    job = _wait(live, job_id)
    assert job["status"] == "error" and job["error"]


def test_record_rejects_videos_that_are_not_live(fake_record, monkeypatch):
    monkeypatch.setattr(main, "ytdlp_extract", lambda url, extra=None: {"title": "x", "live_status": "was_live"})
    r = client.post("/api/record", json={"url": "https://www.youtube.com/watch?v=viejo"})
    assert r.status_code == 400 and "no está en vivo" in r.json()["detail"]


def test_only_records_can_be_stopped(db):
    main.JOBS["t1"] = {"id": "t1", "kind": "transcribe", "status": "running"}
    try:
        assert client.post("/api/jobs/t1/stop").status_code == 400
    finally:
        main.JOBS.pop("t1", None)


def test_record_args():
    args = extras.record_args("https://youtu.be/x", "/tmp/base", True, "/c.txt")
    assert "--live-from-start" in args and "--hls-use-mpegts" in args and args[-1] == "https://youtu.be/x"
    assert args[args.index("--cookies") + 1] == "/c.txt" and args[args.index("-o") + 1] == "/tmp/base.%(ext)s"
    assert "--live-from-start" not in extras.record_args("u", "b", False, None)


def test_record_keeps_file_when_transcription_fails(fake_record, live, monkeypatch):
    monkeypatch.setenv("CLIPA_TEST_MODE", "end")
    monkeypatch.setattr(main.ai, "get_groq_client", lambda k=None: None)
    monkeypatch.setattr(main.media, "WHISPER_MODEL_AVAILABLE", False)
    job_id = live.post("/api/record", json={"url": "https://www.youtube.com/watch?v=vivo", "transcribe": True}).json()["id"]
    job = _wait(live, job_id)
    assert job["status"] == "done" and "Groq" in job["warning"] and job["file"]
