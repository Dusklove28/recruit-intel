from types import SimpleNamespace
import pytest

from config import Settings
from extractor.llm_extractor import QwenClient


class FakeHTTPError(Exception):
    def __init__(self, status_code, body):
        super().__init__("request failed")
        self.status_code = status_code
        self.body = body


def _response(content='{"ok":true}'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_qwen_client_requests_low_temperature_json():
    called = {}

    class FakeCompletions:
        def create(self, **kwargs):
            called.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"单位名称":"测试单位"}'))]
            )

    fake = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    settings = Settings(api_key="test-value", base_url="https://example.com/v1", model="tested-model")
    result = QwenClient(settings, client=fake).complete_json("system", "user")

    assert result == '{"单位名称":"测试单位"}'
    assert called["model"] == "tested-model"
    assert called["temperature"] == 0
    assert called["response_format"] == {"type": "json_object"}


def test_free_tier_exhaustion_uses_configured_models_in_order():
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] != "fallback-2":
                raise FakeHTTPError(403, {"error": {"code": "AllocationQuota.FreeTierOnly"}})
            return _response()

    fake = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    settings = Settings("test", "https://fallback-order.test/v1", "primary", fallback_models=("fallback-1", "fallback-2"))
    assert QwenClient(settings, fake).complete_json("s", "u") == '{"ok":true}'
    assert calls == ["primary", "fallback-1", "fallback-2"]


@pytest.mark.parametrize("status,body", [
    (403, {"error": {"code": "Other.Forbidden"}}),
    (429, {"error": {"code": "AllocationQuota.FreeTierOnly"}}),
    (400, {"error": {"code": "AllocationQuota.FreeTierOnly"}}),
    (401, {"error": {"code": "AllocationQuota.FreeTierOnly"}}),
])
def test_other_http_errors_do_not_switch_models(status, body):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs["model"])
            raise FakeHTTPError(status, body)

    fake = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    settings = Settings("test", f"https://status-{status}-{id(body)}.test/v1", "primary", fallback_models=("fallback",))
    with pytest.raises(FakeHTTPError):
        QwenClient(settings, fake).complete_json("s", "u")
    assert calls == ["primary"]


def test_fallback_selection_persists_for_new_clients_after_quota_error():
    first_calls = []
    class FirstCompletions:
        def create(self, **kwargs):
            first_calls.append(kwargs["model"])
            if kwargs["model"] == "primary":
                raise FakeHTTPError(403, {"code": "AllocationQuota.FreeTierOnly"})
            return _response()
    settings = Settings("test", "https://persistent-fallback.test/v1", "primary", fallback_models=("fallback",))
    QwenClient(settings, SimpleNamespace(chat=SimpleNamespace(completions=FirstCompletions()))).complete_json("s", "u")

    second_calls = []
    class SecondCompletions:
        def create(self, **kwargs):
            second_calls.append(kwargs["model"])
            return _response()
    QwenClient(settings, SimpleNamespace(chat=SimpleNamespace(completions=SecondCompletions()))).complete_json("s", "u")
    assert first_calls == ["primary", "fallback"]
    assert second_calls == ["fallback"]


def test_settings_loads_primary_and_ordered_fallbacks(monkeypatch):
    from config import Settings

    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-secret")
    monkeypatch.setenv("LLM_BASE_URL", "https://config.test/v1")
    monkeypatch.setenv("LLM_MODEL", "legacy")
    monkeypatch.setenv("LLM_MODEL_PRIMARY", "primary")
    monkeypatch.setenv("LLM_MODEL_FALLBACK_1", "fallback-a")
    monkeypatch.setenv("LLM_MODEL_FALLBACK_2", "primary")
    monkeypatch.setenv("LLM_MODEL_FALLBACK_3", "fallback-b")
    for index in range(4, 11):
        monkeypatch.delenv(f"LLM_MODEL_FALLBACK_{index}", raising=False)

    settings = Settings.from_env()

    assert settings.model == "primary"
    assert settings.fallback_models == ("fallback-a", "fallback-b")


def test_all_free_tiers_exhausted_raises_last_403():
    attempted = []

    class FakeCompletions:
        def create(self, **kwargs):
            attempted.append(kwargs["model"])
            raise FakeHTTPError(403, {"error": {"code": "AllocationQuota.FreeTierOnly"}})

    settings = Settings("test", "https://all-exhausted.test/v1", "primary", fallback_models=("fallback",))
    with pytest.raises(FakeHTTPError):
        QwenClient(settings, SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))).complete_json("s", "u")
    assert attempted == ["primary", "fallback"]
