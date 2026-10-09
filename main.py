"""Run one public recruitment announcement through the complete MVP pipeline."""

import argparse
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from urllib.parse import urljoin

import requests

from adapters.base import AccessRestricted, HEADERS
from collectors.campaign import explore_campaign
from collectors.ccb import collect_ccb_campaign, create_ccb_session, is_ccb_announcement
from collectors.discovery import Candidate
from collectors.generic import download_attachment
from collectors.public_jobs import collect_structured_jobs
from config import PRODUCT_OUTPUT_PATH, PROJECT_ROOT, Settings
from exporters.excel_exporter import export_excel
from extractor.llm_extractor import QwenClient, extract_record
from extractor.schema import RecruitmentRecord
from parsers.docx_parser import parse_docx
from parsers.excel_parser import parse_excel
from parsers.pdf_parser import parse_pdf
from processing.evidence import build_field_evidence
from processing.organization_registry import (
    OrganizationMatch, lookup_organization, save_verified_organization, verify_central_group,
)
from processing.product_scope import is_product_record
from storage.database import connect_database, list_records, save_record
from storage.candidates import save_candidates, update_candidate


CHINA_TIME = timezone(timedelta(hours=8))


def record_candidate_state(
    settings: Settings, candidate_url: str, official_url: str,
    record: RecruitmentRecord, state: str, reason: str | None = None,
) -> None:
    with closing(connect_database(settings.database_path)) as database:
        title = " ".join(part for part in (record.unit_name, record.batch) if part) or official_url
        save_candidates(database, [Candidate("直接输入", candidate_url, title, candidate_url)])
        update_candidate(
            database, candidate_url, state, reason=reason,
            official_url=official_url, unit_name=record.unit_name,
        )


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


def run(
    source_url: str, settings: Settings | None = None, *,
    verify_online: bool = True, require_verified_identity: bool = True,
    candidate_notice_url: str | None = None,
    verified_organization: tuple[str, OrganizationMatch] | None = None,
) -> RecruitmentRecord:
    ccb_acceptance = is_ccb_announcement(source_url)
    settings = settings or Settings.from_env()
    if ccb_acceptance and (
        settings.database_path == PROJECT_ROOT / "data" / "recruitment.sqlite3"
        or settings.output_path == PRODUCT_OUTPUT_PATH
    ):
        settings = replace(
            settings,
            database_path=PROJECT_ROOT / "data" / "cache" / "ccb_acceptance.sqlite3",
            attachments_dir=PROJECT_ROOT / "data" / "attachments" / "ccb_acceptance",
            output_path=PROJECT_ROOT / "data" / "cache" / "ccb_acceptance.xlsx",
        )
    checked_on = datetime.now(CHINA_TIME).date()
    session = create_ccb_session() if ccb_acceptance else requests.Session()
    print("开始解析……")
    campaign = collect_ccb_campaign(source_url, session) if ccb_acceptance else explore_campaign(source_url, session)
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
    if organization is None and verified_organization and record.unit_name == verified_organization[0]:
        organization = verified_organization[1]
    if organization is None and verify_online and not ccb_acceptance:
        try:
            organization = verify_central_group(record.unit_name)
        except (requests.RequestException, ValueError):
            print("官方央企名录读取失败，组织身份待核验")
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
    candidate_url = candidate_notice_url or source_url
    if require_verified_identity and not ccb_acceptance and organization is None:
        record_candidate_state(settings, candidate_url, official_url, record, "待核验", "缺少官方组织身份证据")
        print("组织身份待核验，保留候选，不进入正式招聘表")
        return record
    if require_verified_identity and not ccb_acceptance and (not is_product_record(record, checked_on) or not record.application_url):
        closed = record.status == "已截止" or (record.deadline is not None and record.deadline < checked_on)
        state = "已截止" if closed else "待核验"
        reason = "已过截止日期" if closed else "缺少当前可投递所需的招聘范围或报名入口证据"
        record_candidate_state(settings, candidate_url, official_url, record, state, reason)
        print("不符合当前可投递成品范围，未进入正式招聘表")
        return record
    if require_verified_identity and verify_online and not ccb_acceptance and record.application_url:
        try:
            with session.get(record.application_url, headers=HEADERS, timeout=(8, 20), stream=True) as response:
                code = response.status_code
                if code in {401, 403, 412, 429}:
                    record_candidate_state(settings, candidate_notice_url or source_url, official_url, record,
                                           "待核验", f"报名入口公开访问受限（HTTP {code}）")
                    raise AccessRestricted(record.application_url, code, "报名入口访问受限")
                if code >= 400:
                    record_candidate_state(settings, candidate_notice_url or source_url, official_url, record,
                                           "待核验", f"报名入口无法打开（HTTP {code}）")
                    return record
        except AccessRestricted:
            raise
        except requests.RequestException as error:
            record_candidate_state(settings, candidate_notice_url or source_url, official_url, record,
                                   "待核验", f"报名入口无法打开（{type(error).__name__}）")
            return record
    with closing(connect_database(settings.database_path)) as database:
        if require_verified_identity and not ccb_acceptance:
            previous = database.execute(
                "SELECT source_url FROM recruitment WHERE unit_name=? AND batch=? AND source_url<>?",
                (record.unit_name, record.batch, source_url),
            ).fetchone()
            if previous:
                save_candidates(database, [Candidate("直接输入", candidate_url, record.batch or official_url, candidate_url)])
                update_candidate(database, candidate_url, "待核验", reason="疑似同单位同批次重复活动，需复核",
                                 official_url=official_url, unit_name=record.unit_name)
                print("疑似重复活动，保留候选，未进入正式招聘表")
                return record
        if organization and record.unit_name:
            save_verified_organization(database, record.unit_name, organization)
        record = save_record(database, source_url, record, raw_text, evidence)
        if candidate_notice_url:
            save_candidates(database, [Candidate("直接输入", candidate_url, record.batch or official_url, candidate_url)])
            update_candidate(database, candidate_url, "正式收录", reason="已核验企业公告与组织身份",
                             official_url=official_url, unit_name=record.unit_name)
        print("SQLite保存成功")
        records = list_records(database)
    if settings.output_path == PRODUCT_OUTPUT_PATH:
        records = [record for record in records if is_product_record(record, checked_on)]
    output = export_excel(records, settings.output_path)
    print(f"Excel导出成功：{output}")
    print(
        f"摘要：{record.unit_name} | {record.batch or '批次未确认'} | "
        f"{record.education or '学历未确认'} | {record.status or '状态未确认'}"
    )
    return record


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
