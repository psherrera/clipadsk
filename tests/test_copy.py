"""Análisis del copy de una publicación."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import ai
import main
from fastapi.testclient import TestClient


def test_copy_source_includes_copy_and_context():
    out = ai.copy_source("Hoy anunciamos 500 viviendas #obra", "Diapositiva 1: viviendas")
    assert out.startswith("COPY DE LA PUBLICACIÓN:")
    assert "500 viviendas" in out and "CONTENIDO DE LA PUBLICACIÓN" in out
    assert "CONTENIDO" not in ai.copy_source("Solo el copy de la publicación")


def test_copy_source_trims_long_content():
    out = ai.copy_source("Un copy cualquiera", "x" * 50000, max_content=100)
    assert len(out) < 400 and out.endswith("[…]")


def test_analyze_copy_mode(monkeypatch):
    seen = {}
    monkeypatch.setattr(main, "require_groq", lambda key: object())
    def fake(client, text, mode):
        seen["text"], seen["mode"] = text, mode
        return {"result": "**Mensaje central**: ok", "model_used": "x", "parts": 1}
    monkeypatch.setattr(main.ai, "analyze_transcript", fake)
    c = TestClient(main.app)
    r = c.post("/api/analyze", json={"mode": "copy", "transcript": "", "copy": "Hoy inauguramos la obra del puerto"})
    assert r.status_code == 200, r.text
    assert seen["mode"] == "copy" and "inauguramos" in seen["text"]
    r = c.post("/api/analyze", json={"mode": "copy", "transcript": "", "copy": ""})
    assert r.status_code == 400 and "copy" in r.json()["detail"]


def test_copy_prompt_registered():
    assert "copy" in ai.JOURNALIST_PROMPTS
    assert "{transcript}" in ai.JOURNALIST_PROMPTS["copy"]
