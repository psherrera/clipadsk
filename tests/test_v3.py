"""Versión 3: historial en SQLite, trabajos en segundo plano, errores claros, visualizador y recortes."""
import asyncio
import json
import os
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

import history as hist
import main
from errors import friendly_error
from text_utils import attach_words, clip_segments, normalize_segments, normalize_words

client = TestClient(main.app)
HAS_FFMPEG = shutil.which("ffmpeg") is not None


# ─── Historial ──────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "h.db")
    hist.init(path)
    monkeypatch.setattr(main, "DB_FILE", path)
    return path


def test_history_upsert_list_get_update_delete(db):
    item_id = hist.upsert(db, {"url": "https://youtu.be/a", "title": "Entrevista al Ministro", "transcript": "Hola " * 200,
                               "segments": [{"start": 0, "end": 125.5, "text": "Hola"}], "platform": "youtube"})
    listed = hist.list_items(db)
    assert listed["total"] == 1
    item = listed["items"][0]
    assert item["id"] == item_id and item["duration"] == 125.5 and item["word_count"] == 200
    assert len(item["preview"]) < 300 and "transcript" not in item and "segments" not in item

    assert hist.upsert(db, {"url": "https://youtu.be/a", "title": "Nuevo título", "transcript": "otro"}) == item_id
    assert hist.get(db, item_id)["title"] == "Nuevo título"

    assert hist.update(db, item_id, transcript="texto editado")
    assert hist.get(db, item_id)["transcript"] == "texto editado"
    assert hist.delete(db, item_id) and hist.get(db, item_id) is None


def test_history_search_ignores_accents_and_case(db):
    hist.upsert(db, {"url": "u1", "title": "Conferencia", "transcript": "La inflación de octubre bajó al 2 por ciento."})
    hist.upsert(db, {"url": "u2", "title": "Otra", "transcript": "Nada que ver."})
    res = hist.list_items(db, "INFLACION")
    assert res["total"] == 1 and "inflación de octubre" in res["items"][0]["snippet"]
    assert hist.list_items(db, "100%")["total"] == 0  # los comodines de SQL no rompen la búsqueda


def test_history_import_keeps_server_version(db):
    hist.upsert(db, {"url": "u1", "title": "Del servidor", "transcript": "nuevo"})
    n = hist.import_items(db, [
        {"url": "u1", "title": "Viejo", "transcript": "viejo", "date": "2026-01-01T00:00:00Z"},
        {"url": "u2", "title": "Solo en el navegador", "transcript": "texto", "date": "2026-02-01T00:00:00Z"},
        {"url": "u3", "title": "Sin texto", "transcript": ""},
        "basura",
    ])
    assert n == 1
    titles = {i["title"] for i in hist.list_items(db)["items"]}
    assert titles == {"Del servidor", "Solo en el navegador"}


def test_history_api(db):
    r = client.post("/api/history", json={"url": "https://x.com/a/status/1", "title": "Hilo", "transcript": "texto largo"})
    item_id = r.json()["id"]
    assert client.get("/api/history", params={"q": "largo"}).json()["total"] == 1
    assert client.patch(f"/api/history/{item_id}", json={"transcript": "editado"}).status_code == 200
    assert client.get(f"/api/history/{item_id}").json()["transcript"] == "editado"
    assert client.post("/api/history/import", json={"items": [{"url": "v", "transcript": "t"}]}).json()["imported"] == 1
    assert client.delete("/api/history").json()["deleted"] == 2
    assert client.get(f"/api/history/{item_id}").status_code == 404


# ─── Errores claros ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", "cookies"),
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "privado"),
    ("ERROR: [youtube] abc: Video unavailable", "no existe"),
    ("ERROR: Unsupported URL: https://example.com", "no es de un video"),
    ("Error code: 429 - {'error': {'code': 'rate_limit_exceeded'}}", "Groq"),
    ("Error code: 401 - invalid_api_key", "API Key"),
    ("urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", "YTDLP_NO_CHECK_CERTIFICATE"),
    ("HTTPSConnectionPool: Read timed out.", "conexión"),
    ("ERROR: [youtube] x: Unable to download API page: ('Unable to connect to proxy', OSError('Tunnel connection "
     "failed: 403 Forbidden'))", "No hay conexión"),
    ("ERROR: [youtube] x: HTTP Error 403: Forbidden", "rechazó"),
])
def test_friendly_error(raw, expected):
    assert expected in friendly_error(raw)


def test_friendly_error_unknown_keeps_detail():
    msg = friendly_error("\x1b[0;31mERROR:\x1b[0m algo rarísimo")
    assert "algo rarísimo" in msg and "\x1b" not in msg


def test_video_info_error_is_friendly(monkeypatch):
    def fail(url, extra=None):
        raise RuntimeError("normal: ERROR: [youtube] x: Video unavailable")
    monkeypatch.setattr(main, "ytdlp_extract", fail)
    monkeypatch.setattr(main, "detect_bunny_embed", lambda u: None)
    r = client.post("/api/video-info", json={"url": "https://www.youtube.com/watch?v=x"})
    assert r.status_code == 400 and "no existe" in r.json()["detail"]


# ─── Tiempos por palabra y recortes ─────────────────────────────────────────

def test_words_are_attached_to_their_segments():
    segs = normalize_segments([{"start": 0, "end": 2, "text": "hola que tal"}, {"start": 2, "end": 4, "text": "muy bien"}])
    words = normalize_words([{"word": " hola", "start": 0.1, "end": 0.4}, {"word": "que", "start": 0.5, "end": 0.7},
                             {"word": "tal", "start": 0.8, "end": 1.9}, {"word": "muy", "start": 2.1, "end": 2.5},
                             {"word": "bien", "start": 2.6, "end": 3.0}], offset=10)
    for seg in segs:
        seg["start"] += 10
        seg["end"] += 10
    attach_words(segs, words)
    assert [w["w"] for w in segs[0]["words"]] == ["hola", "que", "tal"]
    assert [w["w"] for w in segs[1]["words"]] == ["muy", "bien"] and segs[1]["words"][0]["s"] == 12.1
    # Re-normalizar (p. ej. al leer de la caché) no los pierde
    assert normalize_segments(segs)[0]["words"] == segs[0]["words"]


def test_clip_segments_shifts_to_zero():
    segs = [{"start": 0, "end": 5, "text": "a"}, {"start": 5, "end": 10, "text": "b"}, {"start": 10, "end": 15, "text": "c"}]
    assert clip_segments(segs, 7, 12) == [{"start": 0, "end": 3, "text": "b"}, {"start": 3, "end": 5, "text": "c"}]


def test_groq_words_requested_with_fallback(monkeypatch, tmp_path):
    import media
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    calls = []

    class Res:
        text, segments = "hola", [{"start": 0, "end": 1, "text": "hola"}]
        words = [{"word": "hola", "start": 0.1, "end": 0.5}]

    class Transcriptions:
        @staticmethod
        def create(**kw):
            calls.append(kw)
            if "timestamp_granularities" in kw and len(calls) == 1:
                raise RuntimeError("unknown parameter: timestamp_granularities")
            return Res()

    class Audio:
        transcriptions = Transcriptions()

    class FakeClient:
        audio = Audio()

    monkeypatch.setattr(media, "_word_timestamps_ok", True)
    text, segs = media.transcribe_with_groq(FakeClient(), str(audio), "es", str(tmp_path))
    assert text == "hola" and segs[0]["words"][0]["w"] == "hola"
    assert "timestamp_granularities" not in calls[-1]  # plan B sin el parámetro


# ─── Trabajos en segundo plano ──────────────────────────────────────────────

@pytest.fixture
def live():
    """Cliente con el loop de eventos abierto entre peticiones (como el servidor real)."""
    with TestClient(main.app) as c:
        yield c


def _wait_job(c, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("el trabajo no terminó")


def test_job_runs_in_background_and_saves_history(db, monkeypatch, live):
    async def fake_transcribe(url, lang, key, uid):
        await asyncio.sleep(0.05)
        return {"transcript": "Texto final.", "raw_transcript": "texto final", "srt": "", "method": "groq_whisper_v3_file",
                "segments": [{"start": 0, "end": 30, "text": "Texto final."}]}
    monkeypatch.setattr(main, "transcribe_url", fake_transcribe)
    r = live.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=abc", "title": "Conferencia",
                                     "groq_api_key": "gsk_secreto"})
    assert r.status_code == 200 and "api_key" not in r.json()
    job = _wait_job(live, r.json()["id"])
    assert job["status"] == "done" and job["result"]["transcript"] == "Texto final."
    assert "gsk_secreto" not in json.dumps(live.get("/api/jobs").json())
    saved = hist.get(db, job["history_id"])
    assert saved["title"] == "Conferencia" and saved["raw_transcript"] == "texto final" and saved["platform"] == "youtube"
    assert live.delete(f"/api/jobs/{job['id']}").status_code == 200


def test_job_error_is_friendly(db, monkeypatch, live):
    async def fail(url, lang, key, uid):
        raise main.TranscriptionError(friendly_error("Private video"), 500, "Private video")
    monkeypatch.setattr(main, "transcribe_url", fail)
    job = _wait_job(live, live.post("/api/jobs", json={"url": "https://youtu.be/x", "title": "t"}).json()["id"])
    assert job["status"] == "error" and "privado" in job["error"]


def test_job_rejects_non_http():
    assert client.post("/api/jobs", json={"url": "file:///etc/passwd"}).status_code == 400


def test_transcript_returns_raw_text(monkeypatch, db):
    monkeypatch.setattr(main, "detect_bunny_embed", lambda u: None)
    monkeypatch.setattr(main, "cache_get", lambda k: None)
    monkeypatch.setattr(main, "cache_set", lambda k, v: None)
    monkeypatch.setattr(main, "transcribe_from_subtitles", lambda *a: {"raw": "hola que tal como andan todos",
                                                                        "segments": [], "method": "subtitles"})
    r = client.post("/api/transcript", json={"url": "https://www.youtube.com/watch?v=abc"})
    assert r.status_code == 200 and r.json()["raw_transcript"].startswith("hola que tal")


# ─── Visualizador ───────────────────────────────────────────────────────────

def test_parse_range():
    assert main.parse_range("bytes=0-99", 1000) == (0, 99)
    assert main.parse_range("bytes=900-", 1000) == (900, 999)
    assert main.parse_range("bytes=-100", 1000) == (900, 999)
    assert main.parse_range("bytes=2000-", 1000) is None
    assert main.parse_range("algo", 1000) is None


def test_media_serving_supports_seeking(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "MEDIA_DIR", str(tmp_path))
    (tmp_path / "0123456789abcdef.mp4").write_bytes(bytes(range(256)) * 4)
    r = client.get("/api/media/0123456789abcdef", headers={"Range": "bytes=10-19"})
    assert r.status_code == 206 and r.content == bytes(range(10, 20))
    assert r.headers["content-range"] == "bytes 10-19/1024"
    assert client.get("/api/media/0123456789abcdef").status_code == 200
    assert client.get("/api/media/..%2F..%2Fmain").status_code == 404
    assert client.get("/api/media/zzzz").status_code == 404


def test_translate_segments(monkeypatch):
    import ai
    monkeypatch.setattr(ai, "translate_texts", lambda texts, target: [f"[{target}] {t}" for t in texts])
    r = client.post("/api/translate-segments", json={"texts": ["hello", "bye"], "target": "es"})
    assert r.json()["texts"] == ["[es] hello", "[es] bye"]
    assert client.post("/api/translate-segments", json={"texts": ["x"], "target": "zz"}).status_code == 400


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("FFmpeg no disponible")
    path = tmp_path_factory.mktemp("v") / "muestra.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=640x360:rate=25:duration=6", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    return path


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    return data["streams"][0]["width"], data["streams"][0]["height"], float(data["format"]["duration"])


def test_peaks(sample_video):
    peaks = main.compute_peaks(str(sample_video), buckets=100)
    assert 90 <= len(peaks) <= 110 and max(peaks) == 100


def test_postprocess_vertical_with_subtitles(sample_video, tmp_path):
    src = tmp_path / "clip.mp4"
    shutil.copy(sample_video, src)
    segs = [{"start": 1, "end": 3, "text": "Primera frase"}, {"start": 3, "end": 5, "text": "Segunda: «comillas» y ñ"}]
    out = main.postprocess_clip(str(src), segs, 0, 6, burn_subs=True, vertical=True)
    assert not src.exists() and _probe(out)[:2] == (1080, 1920)


def test_clip_file_endpoint(sample_video):
    with open(sample_video, "rb") as f:
        r = client.post("/api/clip-file", files={"file": ("entrevista.mp4", f, "video/mp4")},
                        data={"start": "1", "end": "4", "burn_subs": "true",
                              "segments": json.dumps([{"start": 1.5, "end": 3, "text": "Hola"}])})
    assert r.status_code == 200, r.text
    assert "entrevista_1s-4s" in r.headers["content-disposition"]
    out = os.path.join(os.path.dirname(sample_video), "out.mp4")
    with open(out, "wb") as f:
        f.write(r.content)
    assert 2.5 < _probe(out)[2] < 3.6


def test_clip_file_rejects_bad_range(sample_video):
    with open(sample_video, "rb") as f:
        r = client.post("/api/clip-file", files={"file": ("a.mp4", f)}, data={"start": "4", "end": "2"})
    assert r.status_code == 400
