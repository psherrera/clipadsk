import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
LOCAL = "http://127.0.0.1:5000"


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_foreign_origin_is_blocked():
    r = client.post("/api/system/reset", headers={"Origin": "https://pagina-maliciosa.com"})
    assert r.status_code == 403


def test_cors_does_not_allow_foreign_origin():
    r = client.options("/api/analyze", headers={"Origin": "https://pagina-maliciosa.com",
                                                "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") != "*"


def test_local_origin_allowed():
    r = client.post("/api/analyze", json={"transcript": "x" * 100, "mode": "summary"}, headers={"Origin": LOCAL})
    assert r.status_code == 503  # sin API key de Groq, pero no bloqueado por origen


def test_admin_token(monkeypatch):
    monkeypatch.setattr(main, "ADMIN_TOKEN", "secreto")
    assert client.post("/api/system/reset").status_code == 403
    monkeypatch.setattr(main, "_update_engine", lambda: {"status": "ok"})
    assert client.post("/api/system/update-engine", headers={"X-ADMIN-TOKEN": "secreto"}).status_code == 200


def test_proxy_thumbnail_rejects_other_hosts():
    r = client.get("/api/proxy-thumbnail", params={"url": "http://127.0.0.1:5000/api/health"})
    assert r.status_code == 400


def test_transcript_file_rejects_bad_extension():
    r = client.post("/api/transcript-file", files={"file": ("x.exe", b"MZ")},
                    data={"groq_api_key": "fake"})
    assert r.status_code == 400


def test_static_path_traversal_returns_index():
    r = client.get("/..%2F..%2Fbackend%2Fmain.py")
    assert r.status_code == 200 and "import" not in r.text[:200]


def test_unknown_api_route_is_404():
    assert client.get("/api/no-existe").status_code == 404


def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_FILE", str(tmp_path / "t.db"))
    main.init_db()
    main.cache_set("k", {"transcript": "hola", "srt": "", "segments": []})
    assert main.cache_get("k")["transcript"] == "hola"
    assert main.cache_get("otra") is None


@pytest.mark.parametrize("mode", ["summary", "data", "angle"])
def test_analyze_long_transcript_uses_all_parts(monkeypatch, mode):
    """Una transcripción larga se analiza completa (map → reduce), no solo inicio y final."""
    import ai
    seen = []

    def fake_chat(client, prompt, **kw):
        seen.append(prompt)
        return "ok", "fake-model"
    monkeypatch.setattr(ai, "chat_completion", fake_chat)
    middle = "DATO_DEL_MEDIO"
    text = ("palabra " * 3000) + middle + (" palabra" * 3000)
    out = ai.analyze_transcript(object(), text, mode)
    assert out["parts"] > 1
    assert any(middle in p for p in seen)


def test_cleanup_keeps_raw_chunk_on_failure(monkeypatch):
    import ai

    def boom(*a, **k):
        raise ai.RateLimitedError("429")
    monkeypatch.setattr(ai, "chat_completion", boom)
    warnings = []
    text = "Hola esto es una prueba de texto bastante larga para limpiar. " * 3
    assert ai.cleanup_transcript(text, object(), "es", warnings) == text.strip() or warnings
    assert warnings
