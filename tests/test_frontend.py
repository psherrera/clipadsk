"""El frontend no depende de servicios externos y todos sus archivos locales existen."""
import os
import re

import pytest
from fastapi.testclient import TestClient

import main

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
client = TestClient(main.app)


def _read(name):
    with open(os.path.join(FRONTEND, name), encoding="utf-8") as f:
        return f.read()


def _assets(html):
    """Rutas de <script src> y <link href> (sin los enlaces de navegación <a>)."""
    return re.findall(r'<(?:script|link)\b[^>]*?\b(?:src|href)="([^"]+)"', html)


@pytest.mark.parametrize("page", ["index.html", "setup.html"])
def test_page_loads_only_local_assets(page):
    for url in _assets(_read(page)):
        assert not re.match(r"(https?:)?//", url), f"{page} carga un recurso externo: {url}"
        assert os.path.exists(os.path.join(FRONTEND, url.split("?")[0])), f"{page}: falta {url}"


@pytest.mark.parametrize("path", ["vendor/tailwind.css", "vendor/tailwind-setup.css", "vendor/fonts.css",
                                  "vendor/jszip.min.js", "vendor/fonts/material-symbols-outlined.woff2",
                                  "vendor/fonts/outfit-latin-wght-normal.woff2"])
def test_vendor_files_are_served(path):
    r = client.get("/" + path)
    assert r.status_code == 200
    if path.endswith((".css", ".js")):  # que no sea el index.html de relleno de la SPA
        assert not r.text.lstrip().startswith("<!DOCTYPE")


def test_compiled_tailwind_has_the_apps_custom_theme():
    css = _read("vendor/tailwind.css")
    assert "--c-primary" in css and "--s400" in css  # paleta personalizada (grises que se invierten en modo claro)
    assert ".text-slate-400" in css and ".bg-white\\/5" in css


def test_service_worker_precaches_existing_files_and_matching_versions():
    sw = _read("sw.js")
    index = _read("index.html")
    for url in re.findall(r"'\./([^']+)'", sw.split("const ASSETS")[1].split("];")[0]):
        assert os.path.exists(os.path.join(FRONTEND, url.split("?")[0])), f"sw.js precachea un archivo que no existe: {url}"
    version = re.search(r"clipadsk-v([\d.]+)", sw).group(1)
    assert f"main.js?v={version}" in index and f"style.css?v={version}" in index and f"tailwind.css?v={version}" in index
