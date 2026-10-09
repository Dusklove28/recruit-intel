"""Validate source URLs and make deterministic fields authoritative."""

from datetime import date, timedelta
import re
from urllib.parse import urljoin

from extractor.schema import FIELD_NAMES, RecruitmentRecord
from processing.normalize import normalize_payload


def finalize_record(
    payload: dict,
    official_url: str,
    source_text: str,
    page_links: list[tuple[str, str]],
    checked_on: date,
    warnings: list[str] | None = None,
    preferred_application_url: str | None = None,
    trusted_fields: dict[str, str | None] | None = None,
) -> RecruitmentRecord:
    expected = set(FIELD_NAMES)
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"LLM 字段不符合17列定义：缺少 {missing}；多出 {extra}")
    data = normalize_payload(payload)
    data["序号"] = 1
    data["官方公告"] = official_url
    data["最后核验日期"] = checked_on.isoformat()
    data["单位类型"] = None
    data["所属集团/主管单位"] = None
    data["更新时间"] = None
    for field, value in (trusted_fields or {}).items():
        if field not in {"学历要求", "工作地点"}:
            raise ValueError(f"不允许覆盖字段：{field}")
        if value:
            data[field] = value
    notes = [data.get("备注")] if data.get("备注") else []
    notes.extend(warnings or [])

    application_url = preferred_application_url or data.get("报名入口")
    known_urls = {
        urljoin(official_url, url)
        for label, url in page_links
        if re.search(r"报名|网申|立即投递|在线投递|投递入口|立即申请|进入系统|申请职位", label)
    }
    if preferred_application_url:
        known_urls.add(preferred_application_url)
    if application_url and application_url not in known_urls:
        data["报名入口"] = None
        notes.append("模型给出的链接不是明确报名入口，已留空")
    else:
        data["报名入口"] = application_url

    data["备注"] = "；".join(notes) if notes else None
    record = RecruitmentRecord.model_validate(data)
    if not record.unit_name:
        raise ValueError("未能从公告确认单位名称，拒绝保存")
    if record.deadline:
        if record.deadline < checked_on:
            status = "已截止"
        elif record.deadline <= checked_on + timedelta(days=7):
            status = "即将截止"
        else:
            status = "招聘中"
        record = record.model_copy(update={"status": status})
    return record
