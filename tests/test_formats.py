import pytest
import yt_dlp

from formats import (
    QUALITY_COMPATIBLE, QUALITY_MAX, TRIM_FFMPEG_ARGS, build_format_list, download_format_opts, normalize_quality,
)


def F(fid, h, vcodec, acodec="none", ext="mp4", fps=30, tbr=1000, size=None, hdr=None):
    d = {"format_id": fid, "url": f"https://x/{fid}", "ext": ext, "protocol": "https", "height": h,
         "width": int(h * 16 / 9) if h else None, "vcodec": vcodec, "acodec": acodec,
         "fps": fps if h else None, "tbr": tbr, "filesize": size}
    if h is None:
        d.update(vcodec="none", abr=tbr)
    if hdr:
        d["dynamic_range"] = hdr
    return d


# Como los entrega yt-dlp para YouTube: de PEOR a MEJOR
YT_FORMATS = [
    F("140", None, "none", "mp4a.40.2", "m4a", tbr=129), F("251", None, "none", "opus", "webm", tbr=140),
    F("18", 360, "avc1.42001E", "mp4a.40.2", tbr=500, size=10),
    F("136", 720, "avc1.4d401f", tbr=1500, size=30), F("247", 720, "vp9", ext="webm", tbr=1400, size=28),
    F("398", 720, "av01.0.05M.08", tbr=1200, size=24),
    F("137", 1080, "avc1.640028", tbr=2500, size=50), F("248", 1080, "vp9", ext="webm", tbr=2600, size=52),
    F("399", 1080, "av01.0.08M.08", tbr=2200, size=44),
    F("299", 1080, "avc1.64002a", fps=60, tbr=4300, size=86), F("303", 1080, "vp9", ext="webm", fps=60, tbr=4100, size=82),
    F("699", 1080, "av01.0.09M.10", fps=60, tbr=4000, size=80, hdr="HDR10"),
    F("271", 1440, "vp9", ext="webm", tbr=8000, size=160), F("400", 1440, "av01.0.12M.08", tbr=7000, size=140),
]


def test_menu_has_one_option_per_resolution_pointing_to_height():
    opts = build_format_list(YT_FORMATS)
    assert [o["format_id"] for o in opts] == ["h1440", "h1080", "h720", "h360"]
    assert all(o["ext"] == "mp4" for o in opts)


def test_menu_sizes_come_from_best_variant_not_worst():
    by_id = {o["format_id"]: o for o in build_format_list(YT_FORMATS)}
    # La mejor variante 1080p es la última de la lista (AV1 60 fps); la mejor H.264 es la de 60 fps
    assert by_id["h1080"]["filesize"] == 80
    assert by_id["h1080"]["filesize_compatible"] == 86
    assert by_id["h1440"]["compatible"] is False  # YouTube no tiene H.264 por encima de 1080p
    assert by_id["h720"]["compatible"] is True


def test_vertical_video_labelled_by_short_side():
    vertical = [{"format_id": "v", "width": 1080, "height": 1920, "vcodec": "h264", "acodec": "aac", "ext": "mp4"}]
    opt = build_format_list(vertical)[0]
    assert opt["resolution"].startswith("1080p")
    assert opt["format_id"] == "h1920"  # el filtro usa la altura real


def test_without_ffmpeg_only_formats_with_audio():
    opts = build_format_list(YT_FORMATS, has_ffmpeg=False)
    assert [o["format_id"] for o in opts] == ["h360"]


def _pick(format_id, quality):
    opts = download_format_opts(format_id, quality, has_ffmpeg=True)
    ydl = yt_dlp.YoutubeDL({"quiet": True, "simulate": True, **opts})
    info = {"id": "x", "title": "t", "extractor": "youtube", "extractor_key": "Youtube",
            "webpage_url": "https://www.youtube.com/watch?v=x", "formats": [dict(f) for f in YT_FORMATS]}
    return ydl.process_ie_result(info, download=False)["format_id"]


@pytest.mark.parametrize("format_id,quality,expected", [
    ("h1080", QUALITY_COMPATIBLE, "299+140"),  # H.264 60 fps (el menú viejo daba 137, 30 fps)
    ("h1080", QUALITY_MAX, "303+140"),         # VP9 60 fps; evita la variante HDR
    ("h720", QUALITY_COMPATIBLE, "136+140"),
    ("h1440", QUALITY_COMPATIBLE, "271+140"),  # sin H.264 en 1440p: usa lo que hay
    ("best", QUALITY_MAX, "400+140"),
    ("best", QUALITY_COMPATIBLE, "271+140"),   # "Mejor calidad" prioriza resolución
])
def test_ytdlp_picks_expected_variant(format_id, quality, expected):
    assert _pick(format_id, quality) == expected


def test_legacy_numeric_format_id_still_works():
    assert _pick("137", QUALITY_MAX) == "137+140"


def test_unknown_quality_falls_back_to_compatible():
    assert normalize_quality("ultra") == QUALITY_COMPATIBLE
    assert normalize_quality(None) == QUALITY_COMPATIBLE


def test_trim_args_use_high_quality():
    args = " ".join(TRIM_FFMPEG_ARGS)
    assert "-crf 18" in args and "libx264" in args and "yuv420p" in args
