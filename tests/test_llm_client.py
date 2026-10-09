from types import SimpleNamespace

from config import Settings
from extractor.llm_extractor import QwenClient


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
