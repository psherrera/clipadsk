"""Galería de carruseles de Instagram: lista, descarga de uno, de varios y de todos."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
URL = "https://www.instagram.com/p/ABC123/"

ITEMS = [
    {"url": "https://scontent.cdninstagram.com/a.jpg", "thumb": "https://scontent.cdninstagram.com/a.jpg", "is_video": False, "ext": "jpg"},
    {"url": "https://scontent.cdninstagram.com/b.mp4", "thumb": "https://scontent.cdninstagram.com/b.jpg", "is_video": True, "ext": "mp4"},
    {"url": "https://scontent.cdninstagram.com/c.jpg", "thumb": "https://scontent.cdninstagram.com/c.jpg", "is_video": False, "ext": "jpg"},
]


@pytest.fixture
def fake_carousel(monkeypatch, tmp_path):
    main._CAROUSEL_CACHE.clear()
    data = {"items": ITEMS, "username": "diario.x", "description": "Una nota", "shortcode": "ABC123"}
    monkeypatch.setattr(main, "get_carousel", lambda url, try_instaloader=True: data)
    monkeypatch.setattr(main, "_fetch_carousel_item", lambda item: f"contenido de {item['url']}".encode())
    monkeypatch.setattr(main, "DOWNLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(main, "resolve_url", _same_url)
    return data


async def _same_url(url):
    return url


def test_carousel_from_gallery_normalizes():
    files = [
        {"url": "https://x.cdninstagram.com/1.jpg", "metadata": {"extension": "jpg", "username": "u", "description": "d", "post_shortcode": "S"}},
        {"url": "https://x.cdninstagram.com/2.mp4", "metadata": {"extension": "mp4", "display_url": "https://x.cdninstagram.com/2.jpg"}},
        {"url": "https://x.cdninstagram.com/3", "metadata": {"extension": "../exe"}},
    ]
    data = main.carousel_from_gallery(files)
    assert data["username"] == "u" and data["shortcode"] == "S"
    a, b, c = data["items"]
    assert a == {"url": files[0]["url"], "thumb": files[0]["url"], "is_video": False, "ext": "jpg"}
    assert b["is_video"] and b["thumb"].endswith("2.jpg") and b["ext"] == "mp4"
    assert c["ext"] == "exe"  # sin puntos ni barras


def test_info_response_lists_every_item():
    res = main.carousel_info_response({"items": ITEMS, "username": "diario.x", "description": "", "shortcode": "ABC123"})
    assert [c["index"] for c in res["carousel"]] == [0, 1, 2]
    assert res["carousel"][1]["is_video"] and res["carousel"][0]["thumb"].startswith("/api/proxy-thumbnail?url=")
    assert res["formats"][0]["format_id"] == "carousel_images" and "3 archivos" in res["formats"][0]["label"]


def test_video_info_detects_sidecar(monkeypatch):
    main._CAROUSEL_CACHE.clear()
    monkeypatch.setattr(main, "resolve_url", _same_url)
    monkeypatch.setattr(main, "instaloader", object())
    monkeypatch.setattr(main, "get_instagram_info", lambda url: {
        "sidecar": ITEMS, "caption": "Texto", "shortcode": "ABC123", "uploader": "diario.x", "is_video": False, "title": "Texto"})
    r = client.post("/api/video-info", json={"url": URL})
    assert r.status_code == 200
    assert len(r.json()["carousel"]) == 3
    assert main._CAROUSEL_CACHE[URL][1]["items"] == ITEMS  # queda en caché para la descarga


def test_download_single_item_is_not_zipped(fake_carousel):
    r = client.post("/api/download", json={"url": URL, "format_id": "carousel_images", "items": [1]})
    assert r.status_code == 200
    assert r.content == b"contenido de https://scontent.cdninstagram.com/b.mp4"
    assert "carrusel_diario.x_02_video.mp4" in r.headers["content-disposition"]


def test_download_selected_items_zip(fake_carousel):
    r = client.post("/api/download", json={"url": URL, "format_id": "carousel_images", "items": [2, 0, 0, 99]})
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == ["01_imagen.jpg", "03_imagen.jpg"]


def test_download_all_without_items(fake_carousel):
    r = client.post("/api/download", json={"url": URL, "format_id": "carousel_images"})
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == ["01_imagen.jpg", "02_video.mp4", "03_imagen.jpg"]


def test_download_items_out_of_range(fake_carousel):
    r = client.post("/api/download", json={"url": URL, "format_id": "carousel_images", "items": [7]})
    assert r.status_code == 400


def test_download_reports_when_instagram_blocks(fake_carousel, monkeypatch):
    def boom(item):
        raise RuntimeError("403 Forbidden")
    monkeypatch.setattr(main, "_fetch_carousel_item", boom)
    r = client.post("/api/download", json={"url": URL, "format_id": "carousel_images", "items": [0, 2]})
    assert r.status_code == 502
