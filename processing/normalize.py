"""Small, explicit cleanup of LLM JSON values."""

import re


EMPTY_MARKERS = {"", "未知", "不详", "未提及", "无", "null", "none"}


def normalize_payload(payload: dict) -> dict:
    normalized = dict(payload)
    for key, value in normalized.items():
        if isinstance(value, str):
            value = value.strip()
            if value.lower() in EMPTY_MARKERS:
                value = None
            elif key in {"更新时间", "截止时间", "最后核验日期"}:
                match = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", value)
                if match:
                    year, month, day = map(int, match.groups())
                    value = f"{year:04d}-{month:02d}-{day:02d}"
            normalized[key] = value
    return normalized
