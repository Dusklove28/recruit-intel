"""Small wrapper around the already configured Bailian compatible API."""

from datetime import date
import json
import threading
from collections import defaultdict
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from config import Settings
from extractor.prompts import SYSTEM_PROMPT, build_user_prompt
from extractor.schema import RecruitmentRecord
from processing.validate import finalize_record


USAGE: dict[str, Any] = {
    "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
    "fallback_switches": 0, "models": {},
}
_USAGE_LOCK = threading.Lock()
_ACTIVE_MODELS: dict[tuple[str, str, tuple[str, ...]], int] = {}
_ACTIVE_LOCK = threading.Lock()


def reset_usage() -> None:
    with _USAGE_LOCK:
        USAGE.update({"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                      "fallback_switches": 0, "models": {}})


def usage_snapshot() -> dict[str, Any]:
    with _USAGE_LOCK:
        return {**USAGE, "models": {name: dict(values) for name, values in USAGE["models"].items()}}


def _error_code(value: Any, depth: int = 0) -> set[str]:
    """Collect structured error codes without relying on incidental prose."""
    if depth > 4 or value is None:
        return set()
    codes: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() == "code" and isinstance(child, str):
                codes.add(child)
            elif isinstance(child, (dict, list)):
                codes.update(_error_code(child, depth + 1))
    elif isinstance(value, list):
        for child in value:
            codes.update(_error_code(child, depth + 1))
    return codes


def is_free_tier_quota_error(error: Exception) -> bool:
    """True only for the exact documented Bailian free-tier exhaustion code."""
    if getattr(error, "status_code", None) != 403:
        return False
    body = getattr(error, "body", None)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return False
    return "AllocationQuota.FreeTierOnly" in _error_code(body)


class QwenClient:
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        self.models = tuple(dict.fromkeys((settings.model, *settings.fallback_models)))
        self._model_key = (settings.base_url.rstrip("/"), settings.model, settings.fallback_models)
        self.client = client or OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=60,
            max_retries=1,
        )

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        while True:
            with _ACTIVE_LOCK:
                index = _ACTIVE_MODELS.get(self._model_key, 0)
            model = self.models[index]
            try:
                with _USAGE_LOCK:
                    USAGE["calls"] += 1
                    model_stats = USAGE["models"].setdefault(model, {"calls": 0, "quota_exhausted": 0})
                    model_stats["calls"] += 1
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                usage = getattr(response, "usage", None)
                if usage:
                    with _USAGE_LOCK:
                        USAGE["prompt_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
                        USAGE["completion_tokens"] += int(getattr(usage, "completion_tokens", 0) or 0)
                content = response.choices[0].message.content
                if not content:
                    raise ValueError("LLM 未返回 JSON 内容")
                return content
            except Exception as error:
                if not is_free_tier_quota_error(error):
                    raise
                with _USAGE_LOCK:
                    USAGE["models"].setdefault(model, {"calls": 0, "quota_exhausted": 0})["quota_exhausted"] += 1
                with _ACTIVE_LOCK:
                    current = _ACTIVE_MODELS.get(self._model_key, 0)
                    if current == index and index + 1 < len(self.models):
                        _ACTIVE_MODELS[self._model_key] = index + 1
                        with _USAGE_LOCK:
                            USAGE["fallback_switches"] += 1
                        continue
                    if current > index:
                        continue
                raise


def extract_record(
    client: QwenClient,
    material: str,
    official_url: str,
    page_links: list[tuple[str, str]],
    checked_on: date,
    warnings: list[str] | None = None,
    preferred_application_url: str | None = None,
    trusted_fields: dict[str, str | None] | None = None,
) -> RecruitmentRecord:
    prompt = build_user_prompt(material, official_url, page_links, checked_on.isoformat())
    last_error: Exception | None = None
    for attempt in range(2):
        system = SYSTEM_PROMPT
        if attempt:
            system += (
                "\n上一次输出未通过严格校验。请重新输出全部17字段；"
                "尤其把‘专业/硬性要求’压缩为180字以内的概括，不要逐岗位罗列；"
                "不要写入职后的培养或跟岗安排，保留特定专业的附加条件。"
            )
        response = client.complete_json(system, prompt)
        try:
            payload = json.loads(response)
            if not isinstance(payload, dict):
                raise ValueError("LLM 必须返回单个 JSON 对象")
            return finalize_record(
                payload, official_url, material, page_links, checked_on, warnings,
                preferred_application_url, trusted_fields,
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            last_error = error
    raise ValueError("LLM 连续两次未通过 JSON/字段校验") from last_error
