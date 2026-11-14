"""3.4: glosario, probar API Key, aviso de versión, Word con minutos/citas/diálogo y acceso por PIN."""
import io

import pytest
from fastapi.testclient import TestClient

import ai
import glossary
import history as hist
import extras
import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def reset_glossary():
    glossary.set_text("")
    yield
    glossary.set_text("")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "x.db")
    hist.init(path)
    extras.init(path)
    monkeypatch.setattr(main, "DB_FILE", path)
    return path


# ─── Glosario ───────────────────────────────────────────────────────────────

def test_glossary_parse():
    terms, pairs = glossary.parse("Anthropic\n# comentario\nYemini = Gemini\nCloud | Clod → Claude\n\n")
    assert terms == ["Anthropic", "Gemini", "Claude"]
    assert pairs == [("Yemini", "Gemini"), ("Cloud", "Claude"), ("Clod", "Claude")]


def test_glossary_apply_whole_word_and_case():
    glossary.set_text("Yemini = Gemini\nAntropic = Anthropic")
    assert glossary.apply("Usé yemini y Yemini; no Yeminis") == "Usé Gemini y Gemini; no Yeminis"
    assert glossary.apply("de Antropic.") == "de Anthropic."
    assert glossary.apply("Open AI") == "Open AI"


def test_glossary_longest_variant_first():
    glossary.set_text("Open = Abierto\nOpen AI = OpenAI")
    assert glossary.apply("Open AI y Open") == "OpenAI y Abierto"


def test_glossary_segments_and_words():
    glossary.set_text("Cloud = Claude")
    segs = [{"start": 0, "end": 1, "text": "Hola Cloud", "words": [{"w": "Cloud", "s": 0.5, "e": 1}]}]
    glossary.apply_to_segments(segs)
    assert segs[0]["text"] == "Hola Claude" and segs[0]["words"][0]["w"] == "Claude"


def test_whisper_prompt_and_limit():
    assert glossary.whisper_prompt() == ""
    glossary.set_text("Anthropic\nYemini = Gemini")
    assert glossary.whisper_prompt() == "Nombres propios: Anthropic, Gemini."
    glossary.set_text("\n".join(f"Nombre{i}" for i in range(500)))
    assert len(glossary.whisper_prompt()) <= glossary.MAX_PROMPT_CHARS + 2


def test_glossary_saved_with_settings(db):
    r = client.put("/api/settings", json={"glossary": "Yemini = Gemini"})
    assert r.status_code == 200 and r.json()["glossary"] == "Yemini = Gemini"
    assert glossary.apply("yemini") == "Gemini"
    assert client.put("/api/settings", json={"glossary": "x" * 7000}).status_code == 400


class _FakeCompletions:
    def __init__(self):
        self.prompts = []


def test_cleanup_gets_glossary_rule(monkeypatch):
    glossary.set_text("Yemini = Gemini")
    seen = {}

    def fake_chat(client, prompt, **kw):
        seen["prompt"] = prompt
        return ("Hablamos de Gemini en la nota de hoy con detalle suficiente para pasar el control.", "m")

    monkeypatch.setattr(ai, "chat_completion", fake_chat)
    out = ai.cleanup_transcript("Hablamos de Yemini en la nota de hoy con detalle suficiente para pasar el control.", object())
    assert "Gemini" in seen["prompt"] and "Yemini" in seen["prompt"]
    assert "Yemini" not in out


# ─── Probar API Key ─────────────────────────────────────────────────────────

class _Model:
    def __init__(self, id):
        self.id = id


class _Models:
    def __init__(self, ids):
        self.data = [_Model(i) for i in ids]


class _FakeClient:
    def __init__(self, ids=None, error=None):
        self._ids, self._error = ids, error
        self.models = self

    def list(self):
        if self._error:
            raise self._error
        return _Models(self._ids)


def test_key_ok(monkeypatch):
    monkeypatch.setattr(ai, "get_groq_client", lambda key=None: _FakeClient(["whisper-large-v3", "openai/gpt-oss-120b"]))
    d = client.post("/api/groq/test", json={"groq_api_key": "gsk_x"}).json()
    assert d["ok"] is True and d["whisper"] is True


def test_key_invalid(monkeypatch):
    monkeypatch.setattr(ai, "get_groq_client", lambda key=None: _FakeClient(error=RuntimeError("401 invalid_api_key")))
    d = client.post("/api/groq/test", json={"groq_api_key": "mala"}).json()
    assert d["ok"] is False and "API Key" in d["error"]


def test_key_missing(monkeypatch):
    monkeypatch.setattr(ai, "get_groq_client", lambda key=None: None)
    assert client.post("/api/groq/test", json={}).json()["ok"] is False


def test_key_without_whisper(monkeypatch):
    monkeypatch.setattr(ai, "get_groq_client", lambda key=None: _FakeClient(["openai/gpt-oss-120b"]))
    assert client.post("/api/groq/test", json={"groq_api_key": "k"}).json()["ok"] is False


# ─── Versión nueva ──────────────────────────────────────────────────────────

def test_version_newer(monkeypatch):
    monkeypatch.setattr(main, "_latest_cache", {"at": 0.0, "data": None})
    monkeypatch.setattr(main, "_fetch_latest_version", lambda: "99.0.0")
    d = client.get("/api/version/latest").json()
    assert d["newer"] is True and d["latest"] == "99.0.0"


def test_version_same_or_offline(monkeypatch):
    monkeypatch.setattr(main, "_latest_cache", {"at": 0.0, "data": None})
    monkeypatch.setattr(main, "_fetch_latest_version", lambda: main.APP_VERSION)
    assert client.get("/api/version/latest").json()["newer"] is False

    def boom():
        raise OSError("sin internet")
    monkeypatch.setattr(main, "_latest_cache", {"at": 0.0, "data": None})
    monkeypatch.setattr(main, "_fetch_latest_version", boom)
    d = client.get("/api/version/latest").json()
    assert d["newer"] is False and d["latest"] is None


def test_version_tuple_compare():
    assert main._version_tuple("3.10.0") > main._version_tuple("3.9.9")


# ─── Word ───────────────────────────────────────────────────────────────────

def _docx_text(resp):
    import docx
    d = docx.Document(io.BytesIO(resp.content))
    return "\n".join(p.text for p in d.paragraphs)


def test_docx_minutes_quotes_dialogue():
    body = {"title": "Nota", "transcript": "Primer párrafo.\n\nSegundo párrafo.", "starts": [0, 75.4],
            "quotes": [{"quote": "Esto dijo", "note": "x", "start": 62}],
            "dialogue": "**Ana**: Hola.\n\n**Luis**: Chau."}
    r = client.post("/api/export-docx", json=body)
    assert r.status_code == 200
    text = _docx_text(r)
    assert "[00:00] Primer párrafo." in text and "[01:15] Segundo párrafo." in text
    assert "Citas destacadas" in text and "Esto dijo" in text and "[01:02]" in text
    assert "Ana" in text and "Diálogo por hablantes" in text


def test_docx_still_works_without_extras():
    r = client.post("/api/export-docx", json={"title": "Nota", "transcript": "Solo texto."})
    assert r.status_code == 200
    text = _docx_text(r)
    assert "Solo texto." in text and "Citas destacadas" not in text and "[" not in text


def test_docx_ignores_misaligned_starts():
    r = client.post("/api/export-docx", json={"title": "N", "transcript": "Uno.\n\nDos.", "starts": [1]})
    assert r.status_code == 200 and "[00:01]" not in _docx_text(r)


def test_history_update_segments(db):
    item_id = hist.upsert(db, {"url": "https://x.test/a", "title": "t", "transcript": "hola", "segments": [{"start": 0, "end": 1, "text": "hola"}]})
    assert hist.update(db, item_id, transcript="chau", segments=[{"start": 0, "end": 1, "text": "chau"}])
    item = hist.get(db, item_id)
    assert item["transcript"] == "chau" and item["segments"][0]["text"] == "chau"


# ─── Acceso con PIN (celular) ───────────────────────────────────────────────

@pytest.fixture
def pin_mode(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_PIN", "246810")
    monkeypatch.setattr(main, "_PIN_FAILS", {})
    monkeypatch.setattr(main, "_is_loopback", lambda request: False)   # el TestClient se hace pasar por el celular


def test_pin_blocks_api_and_page(pin_mode):
    c = TestClient(main.app)
    r = c.get("/api/history")
    assert r.status_code == 401 and r.json()["pin_required"] is True
    page = c.get("/")
    assert page.status_code == 401 and "PIN" in page.text


def test_pin_login_flow(pin_mode):
    c = TestClient(main.app)
    assert c.post("/api/login", json={"pin": "000000"}).status_code == 403
    ok = c.post("/api/login", json={"pin": "246810"})
    assert ok.status_code == 200 and "clipa_auth" in ok.headers.get("set-cookie", "")
    assert c.get("/api/health").status_code == 200       # la cookie queda en el cliente


def test_pin_rate_limit(pin_mode):
    c = TestClient(main.app)
    for _ in range(5):
        assert c.post("/api/login", json={"pin": "1"}).status_code == 403
    assert c.post("/api/login", json={"pin": "246810"}).status_code == 429


def test_pin_not_needed_from_the_pc(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_PIN", "246810")
    monkeypatch.setattr(main, "_is_loopback", lambda request: True)
    assert TestClient(main.app).get("/api/health").status_code == 200


def test_no_pin_configured_changes_nothing():
    assert main.ACCESS_PIN == ""
    assert TestClient(main.app).get("/api/health").status_code == 200


def test_wrong_cookie_rejected(pin_mode):
    c = TestClient(main.app, cookies={"clipa_auth": "falsa"})
    assert c.get("/api/health").status_code == 401


def test_mobile_info_shows_pin_only_on_the_pc(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_PIN", "246810")
    monkeypatch.setattr(main, "IS_LOCAL_ONLY", False)
    monkeypatch.setattr(main, "_is_loopback", lambda request: True)
    d = TestClient(main.app).get("/api/mobile/info").json()
    assert d["enabled"] is True and d["pin"] == "246810" and d["from_pc"] is True
    monkeypatch.setattr(main, "_is_loopback", lambda request: False)
    c = TestClient(main.app, cookies={"clipa_auth": main._pin_token()})
    assert c.get("/api/mobile/info").json()["pin"] is None


def test_mobile_info_disabled_by_default():
    d = client.get("/api/mobile/info").json()
    assert d["enabled"] is False and d["exposed"] is False and d["urls"] == []


def test_admin_allowed_from_pc_in_pin_mode(monkeypatch):
    monkeypatch.setattr(main, "ACCESS_PIN", "246810")
    monkeypatch.setattr(main, "IS_LOCAL_ONLY", False)
    monkeypatch.setattr(main, "ADMIN_TOKEN", "")

    class R:
        client = type("C", (), {"host": "127.0.0.1"})()
        headers = {}
    main.require_admin(R())            # desde la PC: permitido
    R.client = type("C", (), {"host": "192.168.1.50"})()
    with pytest.raises(Exception):
        main.require_admin(R())        # desde la red: bloqueado


def test_lan_urls_shape():
    for u in main.lan_urls():
        assert u.startswith("http://") and u.endswith(f":{main.PORT}")


# ─── Activar el celular desde la app ────────────────────────────────────────

def test_toggle_only_from_the_pc(monkeypatch):
    monkeypatch.setattr(main, "_is_loopback", lambda request: False)
    assert client.post("/api/mobile/toggle", json={"enable": True}).status_code == 403


def test_toggle_needs_windows(monkeypatch):
    monkeypatch.setattr(main, "_is_loopback", lambda request: True)
    monkeypatch.setattr(main.sys, "platform", "linux")
    assert client.post("/api/mobile/toggle", json={"enable": True}).status_code == 400


def test_toggle_launches_script(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_is_loopback", lambda request: True)
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(main.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    assert client.post("/api/mobile/toggle", json={"enable": True}).json()["restarting"] is True
    assert client.post("/api/mobile/toggle", json={"enable": False}).status_code == 200
    assert "-Desactivar" not in calls[0] and "-Desactivar" in calls[1]
    assert calls[0][0] == "powershell" and calls[0][-1].endswith("celular.ps1")


def test_toggle_script_missing(monkeypatch):
    monkeypatch.setattr(main, "_is_loopback", lambda request: True)
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.os.path, "isfile", lambda p: False)
    assert client.post("/api/mobile/toggle", json={"enable": True}).status_code == 404


def test_manifest_and_icons_free_of_pin(pin_mode):
    c = TestClient(main.app)
    assert c.get("/manifest.json").status_code == 200
    assert c.get("/icon-192.png").status_code == 200
    assert c.get("/index.html").status_code == 401


def test_manifest_has_png_icons():
    import json
    import os
    m = json.load(open(os.path.join(main.FRONTEND_DIR, "manifest.json"), encoding="utf-8"))
    sizes = {(i["sizes"], i["type"], i["purpose"]) for i in m["icons"]}
    assert ("192x192", "image/png", "any") in sizes and ("512x512", "image/png", "maskable") in sizes
    for i in m["icons"]:
        assert os.path.isfile(os.path.join(main.FRONTEND_DIR, i["src"]))
