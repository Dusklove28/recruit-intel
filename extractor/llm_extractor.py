"""Small wrapper around the already configured Bailian compatible API."""

from datetime import date
import json

from openai import OpenAI
from pydantic import ValidationError

from config import Settings
from extractor.prompts import SYSTEM_PROMPT, build_user_prompt
from extractor.schema import RecruitmentRecord
from processing.validate import finalize_record


class QwenClient:
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        self.model = settings.model
        self.client = client or OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=60,
            max_retries=1,
        )

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM 未返回 JSON 内容")
        return content


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
