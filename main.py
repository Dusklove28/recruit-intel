"""Run one public recruitment announcement through the complete MVP pipeline."""

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from urllib.parse import urljoin

import requests

from collectors.campaign import explore_campaign
from collectors.generic import download_attachment
from collectors.public_jobs import collect_structured_jobs
from config import Settings
from exporters.excel_exporter import export_excel
from extractor.llm_extractor import QwenClient, extract_record
from extractor.schema import RecruitmentRecord
from parsers.docx_parser import parse_docx
from parsers.excel_parser import parse_excel
from parsers.pdf_parser import parse_pdf
from processing.evidence import build_field_evidence
from processing.organization_registry import lookup_organization
from storage.database import connect_database, list_records, save_record


CHINA_TIME = timezone(timedelta(hours=8))


def parse_attachment(path: Path) -> tuple[str, bool]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        result = parse_pdf(path)
        return result.text, result.needs_ocr
    if suffix in {".xls", ".xlsx"}:
        return parse_excel(path), False
    if suffix == ".docx":
        return parse_docx(path), False
    raise ValueError(f"不支持的附件格式：{suffix}")


def run(source_url: str, settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    checked_on = datetime.now(CHINA_TIME).date()
    session = requests.Session()
    print("开始解析……")
    campaign = explore_campaign(source_url, session)
    official_url = campaign.pages[0].final_url
    print(f"已读取招聘专题页面 {len(campaign.pages)} 个")
    print(f"发现附件 {len(campaign.attachments)} 个")
    material_parts = [f"网页正文（{page.final_url}）：\n{page.text}" for page in campaign.pages]
    warnings: list[str] = list(campaign.warnings)
    for number, link in enumerate(campaign.attachments, start=1):
        try:
            path = download_attachment(link, settings.attachments_dir, session)
            text, needs_ocr = parse_attachment(path)
            if needs_ocr:
                warning = f"附件 {link.filename} 需要OCR"
                warnings.append(warning)
                print(f"{path.suffix.upper().lstrip('.')} 需要OCR")
            else:
                print(f"{path.suffix.upper().lstrip('.')}解析成功")
            material_parts.append(
                f"附件{number}：{link.filename}\n原始链接：{link.original_url}\n下载链接：{link.url}\n{text}"
            )
        except Exception as error:
            warnings.append(f"附件 {link.filename} 处理失败（{type(error).__name__}）")
            print(f"附件 {number} 处理失败，继续处理其他材料")

    print("检查专题公开岗位数据……")
    structured_jobs = collect_structured_jobs(campaign, session)
    if structured_jobs:
        print(
            f"岗位列表 {structured_jobs.total_jobs} 个，"
            f"岗位详情成功读取 {len(structured_jobs.details)} 个"
        )
        material_parts.append(
            f"公开岗位数据（{structured_jobs.campaign_page_url}；列表接口："
            f"{structured_jobs.listing_url}；详情接口：{structured_jobs.detail_api_url}）：\n"
            + structured_jobs.prompt_summary()
        )
        warnings.extend(structured_jobs.warnings)
    material = "\n\n".join(material_parts)
    raw_text = material + ("\n\n全部岗位详情：\n" + structured_jobs.raw_job_text() if structured_jobs else "")
    links = [
        (link.text, urljoin(page.final_url, link.href))
        for page in campaign.pages for link in page.links
    ]
    links.extend(("官方网申入口", item.url) for item in campaign.application_candidates)
    preferred_application = (
        campaign.application_candidates[0].url if campaign.application_candidates else None
    )
    trusted_fields = (
        {"学历要求": structured_jobs.education_summary, "工作地点": structured_jobs.location_summary}
        if structured_jobs else None
    )
    record = extract_record(
        QwenClient(settings), material, official_url, links, checked_on, warnings,
        preferred_application, trusted_fields,
    )
    print("LLM抽取成功")

    organization = lookup_organization(record.unit_name)
    if organization:
        record = RecruitmentRecord.model_validate({
            **record.model_dump(),
            "unit_type": organization.unit_type,
            "parent_unit": organization.parent_unit,
        })
        print("官方组织名录核验通过")
    else:
        print("官方组织名录无精确匹配，组织字段留空")
    print("Pydantic校验通过")
    evidence = build_field_evidence(record, campaign, structured_jobs, organization)
    with closing(connect_database(settings.database_path)) as database:
        record = save_record(database, source_url, record, raw_text, evidence)
        print("SQLite保存成功")
        records = list_records(database)
    output = export_excel(records, settings.output_path)
    print(f"Excel导出成功：{output}")
    print(
        f"摘要：{record.unit_name} | {record.batch or '批次未确认'} | "
        f"{record.education or '学历未确认'} | {record.status or '状态未确认'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="将一个招聘公告 URL 提取为17字段并导出 Excel")
    parser.add_argument("url", help="公开招聘公告的 HTTP/HTTPS URL")
    args = parser.parse_args()
    try:
        run(args.url)
    except Exception as error:
        secret = ""
        try:
            secret = Settings.from_env().api_key
        except ValueError:
            pass
        message = str(error).replace(secret, "[REDACTED]") if secret else str(error)
        print(f"处理失败（{type(error).__name__}）：{message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
