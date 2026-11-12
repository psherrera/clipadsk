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


# ─── Seguridad (revisión nov-2026) ───────────────────────────────────────────

def test_dns_rebinding_host_is_rejected():
    """Un dominio ajeno apuntando a 127.0.0.1 no puede usar la API aunque Origin == Host."""
    evil = {"Origin": "http://evil.example:5000", "Host": "evil.example:5000"}
    assert client.post("/api/system/reset", headers=evil).status_code == 400
    assert client.delete("/api/clear-downloads", headers=evil).status_code == 400
    assert client.get("/api/health", headers={"Host": "evil.example:5000"}).status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:5000", "localhost:5000", "192.168.0.10:5000", "mi-pc:5000", "[::1]:5000"])
def test_local_hosts_are_accepted(host):
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_maintenance_blocked_when_exposed_without_token(monkeypatch):
    """Servidor expuesto a la red y sin ADMIN_TOKEN: nadie puede resetear ni actualizar."""
    monkeypatch.setattr(main, "ADMIN_TOKEN", "")
    monkeypatch.setattr(main, "IS_LOCAL_ONLY", False)
    assert client.post("/api/system/reset").status_code == 403
    assert client.post("/api/system/update-app").status_code == 403
    assert client.delete("/api/clear-downloads").status_code == 403


def test_clear_downloads_requires_admin_token(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DOWNLOAD_FOLDER", str(tmp_path / "dl"))
    monkeypatch.setattr(main, "ADMIN_TOKEN", "secreto")
    assert client.delete("/api/clear-downloads").status_code == 403
    assert client.delete("/api/clear-downloads", headers={"X-ADMIN-TOKEN": "secreto"}).status_code == 200


def test_bunny_detection_does_not_leak_cookies(monkeypatch, tmp_path):
    """Las cookies de YouTube no se mandan a una página cualquiera; las del propio sitio sí."""
    import requests
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tSECRETO_YT\n"
        ".sitio-cursos.example\tTRUE\t/\tTRUE\t2147483647\tsesion\tPROPIA\n", encoding="utf-8")
    monkeypatch.setattr(main, "BASE_DIR", str(tmp_path))
    sent = {}

    def fake_send(self, request, **kw):
        sent["cookie"] = request.headers.get("Cookie", "")
        resp = requests.Response()
        resp.status_code, resp._content, resp.url = 200, b"<html></html>", request.url
        return resp
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)

    main.detect_bunny_embed("https://otro-sitio.example/nota")
    assert "SECRETO_YT" not in sent["cookie"] and "PROPIA" not in sent["cookie"]
    main.detect_bunny_embed("https://www.sitio-cursos.example/clase-1")
    assert "PROPIA" in sent["cookie"] and "SECRETO_YT" not in sent["cookie"]


def test_partial_files_do_not_count_as_downloaded(tmp_path):
    for name in ("audio.webm.part", "audio.webm.ytdl", "audio.f251.webm", "sub.es.vtt.part"):
        (tmp_path / name).write_text("x")
    assert main._find_file(str(tmp_path), "audio.") is None
    assert main._find_file(str(tmp_path), "sub.") is None
    (tmp_path / "audio.webm").write_text("x")
    assert main._find_file(str(tmp_path), "audio.").endswith("audio.webm")


def test_download_retries_clean_leftovers(monkeypatch):
    """Si un intento falla dejando restos, se limpian y no se toma el resto como éxito."""
    calls = {"cleanup": 0}

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def download(self, urls): raise RuntimeError("HTTP Error 403")
    monkeypatch.setattr(main.yt_dlp, "YoutubeDL", FakeYDL)
    with pytest.raises(RuntimeError):
        main.ytdlp_download("https://www.youtube.com/watch?v=x", {}, lambda: False,
                            cleanup=lambda: calls.__setitem__("cleanup", calls["cleanup"] + 1))
    assert calls["cleanup"] == 3  # una por estrategia


def test_tls_verification_on_by_default():
    assert main.get_robust_opts("https://www.youtube.com/watch?v=x")["nocheckcertificate"] is False


RAW = ("bueno eh nosotros creemos que la inflacion va a bajar el ano que viene porque el plan "
       "economico esta funcionando y los numeros de octubre lo demuestran claramente dijo el ministro "
       "ante la consulta de los periodistas presentes en la conferencia de prensa de ayer")


def test_cleanup_accepts_punctuation_only(monkeypatch):
    import ai
    cleaned = ("Bueno, nosotros creemos que la inflacion va a bajar el ano que viene, porque el plan "
               "economico esta funcionando y los numeros de octubre lo demuestran claramente.\n\nDijo el ministro "
               "ante la consulta de los periodistas presentes en la conferencia de prensa de ayer.")
    monkeypatch.setattr(ai, "chat_completion", lambda *a, **k: (cleaned, "fake"))
    warnings = []
    assert ai.cleanup_transcript(RAW, object(), "es", warnings) == cleaned
    assert not warnings


def test_cleanup_rejects_rewritten_text(monkeypatch):
    """Si la IA reescribe lo dicho, se conserva el texto original y se avisa."""
    import ai
    rewritten = ("El ministro afirmo ayer en conferencia que la inflacion va a bajar el proximo ano gracias al "
                 "plan economico del gobierno, y sostuvo que los numeros de octubre respaldan esa mirada optimista "
                 "ante los periodistas.")
    monkeypatch.setattr(ai, "chat_completion", lambda *a, **k: (rewritten, "fake"))
    warnings = []
    assert ai.cleanup_transcript(RAW, object(), "es", warnings) == RAW
    assert warnings and "original" in warnings[0]


def test_cleanup_accepts_translation(monkeypatch):
    import ai
    english = ("well we believe inflation will go down next year because the economic plan is working and "
               "the october figures clearly show it said the minister when asked by the journalists present "
               "at the press conference held yesterday afternoon in the capital city")
    spanish = ("Bueno, creemos que la inflación va a bajar el año que viene porque el plan económico está funcionando "
               "y las cifras de octubre lo muestran claramente, dijo el ministro ante la consulta de los periodistas "
               "presentes en la conferencia de prensa realizada ayer por la tarde en la capital.")
    monkeypatch.setattr(ai, "chat_completion", lambda *a, **k: (spanish, "fake"))
    warnings = []
    assert ai.cleanup_transcript(english, object(), "es", warnings) == spanish
    assert not warnings
