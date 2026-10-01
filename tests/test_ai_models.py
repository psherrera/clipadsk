"""Elección de modelos de Groq: si un modelo fue retirado, se usa el siguiente."""
import pytest

import ai


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Res:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Model:
    def __init__(self, mid):
        self.id = mid


class FakeGroq:
    """Imita a Groq: algunos modelos dan 404 'model_not_found'."""

    def __init__(self, available, retired=(), list_fails=False, reject_extras=False):
        self.available, self.retired = set(available), set(retired)
        self.list_fails, self.reject_extras = list_fails, reject_extras
        self.calls = []
        outer = self

        class Completions:
            @staticmethod
            def create(**kw):
                outer.calls.append(kw)
                if kw["model"] in outer.retired or kw["model"] not in outer.available:
                    raise Exception(f"Error code: 404 - {{'error': {{'message': 'The model `{kw['model']}` does not exist or you do not have access to it.', 'code': 'model_not_found'}}}}")
                if outer.reject_extras and ("reasoning_effort" in kw or "response_format" in kw):
                    raise Exception("Error code: 400 - unsupported parameter")
                return _Res(f"<think>pensando</think>respuesta de {kw['model']}")

        class Chat:
            completions = Completions

        class Models:
            @staticmethod
            def list():
                if outer.list_fails:
                    raise Exception("sin permiso")

                class R:
                    data = [_Model(m) for m in outer.available]
                return R()

        self.chat = Chat
        self.models = Models


@pytest.fixture(autouse=True)
def _reset():
    ai._available_cache.clear()
    ai._dead_models.clear()


def test_uses_first_available_model_from_list():
    g = FakeGroq(available=["openai/gpt-oss-20b", "whisper-large-v3"])
    text, model = ai.chat_completion(g, "hola", models=["llama-3.3-70b-versatile", "openai/gpt-oss-20b"])
    assert model == "openai/gpt-oss-20b"
    assert text == "respuesta de openai/gpt-oss-20b"   # sin el bloque <think>
    assert [c["model"] for c in g.calls] == ["openai/gpt-oss-20b"]  # ni siquiera prueba el retirado


def test_retired_model_falls_back_when_listing_fails():
    g = FakeGroq(available=["openai/gpt-oss-120b"], retired=["llama-3.3-70b-versatile"], list_fails=True)
    _, model = ai.chat_completion(g, "hola", models=["llama-3.3-70b-versatile", "openai/gpt-oss-120b"])
    assert model == "openai/gpt-oss-120b"
    # El retirado queda descartado para las próximas llamadas
    g.calls.clear()
    ai.chat_completion(g, "hola", models=["llama-3.3-70b-versatile", "openai/gpt-oss-120b"])
    assert [c["model"] for c in g.calls] == ["openai/gpt-oss-120b"]


def test_retries_without_unsupported_params():
    g = FakeGroq(available=["openai/gpt-oss-120b"], reject_extras=True)
    text, _ = ai.chat_completion(g, "x", models=["openai/gpt-oss-120b"], json_mode=True)
    assert text.startswith("respuesta")
    assert "reasoning_effort" not in g.calls[-1] and "response_format" not in g.calls[-1]


def test_clear_error_when_no_model_exists():
    g = FakeGroq(available=[], list_fails=True)
    with pytest.raises(ai.NoModelAvailableError):
        ai.chat_completion(g, "x", models=["llama-3.3-70b-versatile"])


def test_default_lists_do_not_depend_only_on_retired_models():
    from config import GROQ_TEXT_MODELS, GROQ_CHAT_MODELS, GROQ_VISION_MODELS
    retired = {"llama-3.3-70b-versatile", "llama-3.1-8b-instant", "meta-llama/llama-4-scout-17b-16e-instruct"}
    for lst in (GROQ_TEXT_MODELS, GROQ_CHAT_MODELS, GROQ_VISION_MODELS):
        assert set(lst) - retired
