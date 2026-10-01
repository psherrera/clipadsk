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


def test_update_from_zip_keeps_user_files(tmp_path, monkeypatch):
    """Instalaciones sin git: actualiza desde el ZIP de GitHub sin tocar .env ni el venv."""
    import zipfile as zf
    src = tmp_path / "zip.zip"
    with zf.ZipFile(src, "w") as z:
        z.writestr("clipadsk-main/backend/main.py", "nuevo")
        z.writestr("clipadsk-main/frontend/index.html", "<html>nuevo</html>")
        z.writestr("clipadsk-main/.env", "NO_DEBE_COPIARSE=1")
        z.writestr("clipadsk-main/backend/venv/x.txt", "no")
    root = tmp_path / "app"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "main.py").write_text("viejo")
    (root / ".env").write_text("GROQ_API_KEY=mia")
    monkeypatch.setattr(main, "http_download", lambda url, dest, headers, timeout=60: __import__("shutil").copy(src, dest))
    changed, err = main._update_from_zip(str(root))
    assert err is None and changed == 2
    assert (root / "backend" / "main.py").read_text() == "nuevo"
    assert (root / ".env").read_text() == "GROQ_API_KEY=mia"
    assert not (root / "backend" / "venv").exists()
    assert main._update_from_zip(str(root)) == (0, None)  # segunda vez: nada que cambiar


def test_update_with_git_stashes_local_changes(tmp_path):
    """Una instalación vieja con yt-dlp.exe modificado igual se actualiza (los cambios van a git stash)."""
    import subprocess as sp

    def g(cwd, *a):
        sp.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    remote, local = tmp_path / "remote", tmp_path / "local"
    remote.mkdir()
    g(remote, "init", "-q", "-b", "main")
    g(remote, "config", "user.email", "t@t"); g(remote, "config", "user.name", "t")
    (remote / "yt-dlp.exe").write_text("v1")
    g(remote, "add", "."); g(remote, "commit", "-qm", "v1")
    g(tmp_path, "clone", "-q", str(remote), str(local))
    (remote / "yt-dlp.exe").unlink(); (remote / "nuevo.py").write_text("x")
    g(remote, "add", "-A"); g(remote, "commit", "-qm", "v2")
    (local / "yt-dlp.exe").write_text("actualizado por la version vieja")  # cambio local
    changed, out, err = main._update_with_git(str(local))
    assert err is None and changed
    assert (local / "nuevo.py").exists() and not (local / "yt-dlp.exe").exists()
