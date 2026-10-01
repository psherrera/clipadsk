from text_utils import (
    parse_subtitles_to_segments, format_srt_timestamp, generate_srt_from_segments, remove_repetitions,
    split_text_chunks, pick_relevant_chunks, find_segment_times_for_quote, sanitize_url,
    is_allowed_thumbnail_url, safe_filename, parse_json_from_llm, normalize_segments, host_matches,
)

VTT = """WEBVTT
Kind: captions
Language: es

00:00:01.000 --> 00:00:03.500
<c.colorE5E5E5>Hola</c><00:00:02.000><c> a todos</c>

00:00:03.500 --> 00:00:06.000
La reunión es a las 10:30 en la sede
"""


def test_parse_vtt_strips_tags_but_keeps_spoken_times():
    segs = parse_subtitles_to_segments(VTT)
    assert segs[0] == {"start": 1.0, "end": 3.5, "text": "Hola a todos"}
    # Un horario dicho por alguien NO se borra
    assert segs[1]["text"] == "La reunión es a las 10:30 en la sede"


def test_parse_srt():
    srt = "1\n00:00:00,000 --> 00:00:02,000\nPrimera\n\n2\n00:00:02,000 --> 00:00:04,500\nSegunda línea\ny más\n"
    segs = parse_subtitles_to_segments(srt)
    assert [s["text"] for s in segs] == ["Primera", "Segunda línea y más"]
    assert segs[1]["end"] == 4.5


def test_srt_roundtrip():
    segs = [{"start": 0, "end": 1.9996, "text": "a"}, {"start": 3661.5, "end": 3662, "text": "b"}]
    srt = generate_srt_from_segments(segs)
    assert "00:00:02,000" in srt
    assert format_srt_timestamp(3661.5) == "01:01:01,500"
    assert [s["text"] for s in parse_subtitles_to_segments(srt)] == ["a", "b"]


def test_normalize_segments_objects_and_offset():
    class S:
        start, end, text = 1, 2, " hola "
    assert normalize_segments([S(), {"start": 0, "end": 1, "text": "x"}], offset=10) == [
        {"start": 11.0, "end": 12.0, "text": "hola"}, {"start": 10.0, "end": 11.0, "text": "x"}]


def test_remove_repetitions():
    text = "Cómo andan tanto tiempo Cómo andan tanto tiempo los extrañé mucho"
    assert remove_repetitions(text) == "Cómo andan tanto tiempo los extrañé mucho"
    # Énfasis corto se respeta
    assert remove_repetitions("no no no quiero eso para nada en mi vida") == "no no no quiero eso para nada en mi vida"


def test_split_text_chunks_never_cuts_words():
    text = " ".join(f"Oración número {i} con algunas palabras." for i in range(500))
    chunks = split_text_chunks(text, 1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_split_text_chunks_short_and_empty():
    assert split_text_chunks("hola", 100) == ["hola"]
    assert split_text_chunks("", 100) == []


def test_pick_relevant_chunks_keeps_order_and_first():
    chunks = ["intro con nombres", "habla del presupuesto", "clima", "más sobre presupuesto educativo"]
    picked = pick_relevant_chunks(chunks, "¿Qué dijo del presupuesto?", budget_chars=60)
    idx = [i for i, _ in picked]
    assert idx[0] == 0 and idx == sorted(idx) and 1 in idx


def test_find_quote_times_exact_and_across_segments():
    segs = [{"start": 0, "end": 5, "text": "Buenas tardes a todos."},
            {"start": 5, "end": 9, "text": "Vamos a bajar la inflación"},
            {"start": 9, "end": 12, "text": "antes de fin de año, lo prometo."}]
    assert find_segment_times_for_quote("bajar la inflación", segs)["start"] == 5
    t = find_segment_times_for_quote("la inflación antes de fin", segs)
    assert (t["start"], t["end"]) == (5, 12)
    assert find_segment_times_for_quote("algo que nadie dijo jamás", segs) == {}


def test_sanitize_url():
    assert sanitize_url("https://youtu.be/abc123?si=xyz&t=42") == "https://www.youtube.com/watch?v=abc123&t=42"
    assert sanitize_url("https://www.youtube.com/watch?v=abc&feature=share&pp=1") == "https://www.youtube.com/watch?v=abc"
    bunny = "https://vz-1.b-cdn.net/uuid/playlist.m3u8?token=1"
    assert sanitize_url(bunny) == bunny


def test_host_matches_is_not_fooled_by_substrings():
    assert host_matches("https://m.youtube.com/watch?v=1", ("youtube.com",))
    assert not host_matches("https://notyoutube.com.evil.net/x", ("youtube.com",))
    assert not host_matches("https://evil.com/?u=youtube.com", ("youtube.com",))


def test_thumbnail_proxy_whitelist():
    assert is_allowed_thumbnail_url("https://scontent.cdninstagram.com/v/t51/abc.jpg")
    assert not is_allowed_thumbnail_url("http://scontent.cdninstagram.com/a.jpg")
    assert not is_allowed_thumbnail_url("https://169.254.169.254/latest/meta-data")
    assert not is_allowed_thumbnail_url("https://localhost:5000/api/system/reset")


def test_safe_filename():
    assert safe_filename('Hola: "mundo"/\nnuevo?') == "Hola mundo nuevo"
    assert safe_filename("") == "archivo"


def test_parse_json_from_llm():
    assert parse_json_from_llm('```json\n{"quotes": []}\n```') == {"quotes": []}
    assert parse_json_from_llm('Aquí tienes: {"a": 1} listo') == {"a": 1}


def test_ensure_paragraphs_splits_long_block_without_changing_words():
    from text_utils import ensure_paragraphs
    block = " ".join(f"Esta es la oración número {i}, con algo de texto." for i in range(60))
    out = ensure_paragraphs(block)
    paras = out.split("\n\n")
    assert len(paras) > 3
    assert all(len(p) <= 700 for p in paras)
    assert out.split() == block.split()          # ni una palabra cambiada


def test_ensure_paragraphs_keeps_existing_paragraphs_and_short_text():
    from text_utils import ensure_paragraphs
    assert ensure_paragraphs("Uno.\n\nDos.") == "Uno.\n\nDos."
    assert ensure_paragraphs("Hola.\nChau.") == "Hola.\n\nChau."
    assert ensure_paragraphs("Corto.") == "Corto."
    assert ensure_paragraphs("") == ""
