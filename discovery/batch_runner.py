"""Run a small verified employer Seed batch through existing RecruitIntel services."""

from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlparse

import requests

from adapters.base import AccessRestricted, CampaignLead, public_get
from adapters.beisen import BeisenAdapter
from adapters.generic import GenericAdapter
from collectors.campaign import campaign_prefix
from collectors.discovery import Candidate
from config import PRODUCT_OUTPUT_PATH, Settings
from discovery.platform_detector import detect_platform
from discovery.seed_registry import Seed, load_seeds, save_seed_check, sync_seeds
from discovery.structured_records import beisen_draft, save_draft
from exporters.excel_exporter import export_excel
from extractor.schema import RecruitmentRecord
from main import run
from processing.product_scope import is_product_record
from processing.organization_registry import verify_child_seed
from storage.candidates import save_candidates, update_candidate
from storage.database import connect_database, list_records


CHINA_TIME = timezone(timedelta(hours=8))
SUPPORTED = frozenset({"custom", "unknown", "beisen"})


@dataclass
class SeedResult:
    organization_name: str
    career_url: str
    platform: str
    status: str
    reason: str = ""
    failed_url: str | None = None
    http_status: int | None = None
    discovered: int = 0
    parsed: int = 0
    formal: int = 0
    accessible: bool = False
    formal_urls: list[str] = field(default_factory=list)


@dataclass
class BatchReport:
    checked_at: str
    seed_total: int
    results: list[SeedResult] = field(default_factory=list)
    formal_records: list[RecruitmentRecord] = field(default_factory=list)

    def summary(self) -> dict:
        statuses = Counter(item.status for item in self.results)
        platforms = Counter(item.platform for item in self.results)
        parsed = sum(item.parsed for item in self.results)
        discovered = sum(item.discovered for item in self.results)
        records = self.formal_records
        n = len(records)
        return {
            "seed_total": self.seed_total,
            "accessible": sum(item.accessible for item in self.results),
            "platforms": dict(platforms),
            "seeds_with_2027_leads": sum(item.discovered > 0 for item in self.results),
            "discovered_2027_campaigns": discovered,
            "parsed_campaigns": parsed,
            "formal_campaigns": sum(item.formal for item in self.results),
            "pending_manual_review": statuses["pending_manual_review"],
            "status_counts": dict(statuses),
            "success": statuses["success"],
            "no_2027_recruitment": statuses["no_2027_recruitment"],
            "expired": statuses["expired"],
            "access_control": statuses["access_control"],
            "unsupported_platform": statuses["unsupported_platform"],
            "parse_failed": statuses["parse_failed"],
            "parse_rate": round(parsed / discovered, 3) if discovered else 0.0,
            "discovery_rate": round(sum(item.discovered > 0 for item in self.results) / self.seed_total, 3) if self.seed_total else 0.0,
            "formal_inclusion_rate": round(n / discovered, 3) if discovered else 0.0,
            "pending_rate": round(statuses["pending_manual_review"] / self.seed_total, 3) if self.seed_total else 0.0,
            "education_rate": round(sum(bool(r.education) for r in records) / n, 3) if n else 0.0,
            "requirements_rate": round(sum(bool(r.requirements) for r in records) / n, 3) if n else 0.0,
            "official_url_rate": round(sum(bool(r.official_url) for r in records) / n, 3) if n else 0.0,
            "application_url_rate": round(sum(bool(r.application_url) for r in records) / n, 3) if n else 0.0,
        }


def _save_lead_candidate(connection, seed: Seed, lead: CampaignLead) -> None:
    save_candidates(connection, [Candidate("企业招聘入口", seed.career_url, lead.title, lead.url)])


def _has_formal_record(connection, url: str) -> bool:
    return (
        connection.execute("SELECT state FROM candidates WHERE notice_url=?", (url,)).fetchone() or [None]
    )[0] == "正式收录" and connection.execute(
        "SELECT 1 FROM recruitment WHERE source_url=?", (url,)
    ).fetchone() is not None


def _allowed_lead(seed: Seed, lead: CampaignLead) -> bool:
    host = (urlparse(lead.url).hostname or "").lower()
    domain = seed.official_domain.lower().lstrip(".")
    entry_host = (urlparse(seed.career_url).hostname or "").lower()
    return host == domain or host.endswith("." + domain) or host == entry_host


def _process_seed(seed: Seed, settings: Settings, connection, *, sleep_seconds: float) -> SeedResult:
    platform = detect_platform(seed.career_url, official_domain=seed.official_domain)
    result = SeedResult(seed.organization_name, seed.career_url, platform, "pending_manual_review")
    if platform not in SUPPORTED:
        try:
            public_get(requests.Session(), seed.career_url)
            result.accessible = True
        except AccessRestricted as error:
            result.status = "access_control"
            result.reason = str(error)
            result.failed_url = error.url
            result.http_status = error.status_code
            return result
        except requests.RequestException as error:
            result.status = "parse_failed"
            result.reason = f"{type(error).__name__}：入口读取失败"
            result.failed_url = seed.career_url
            return result
        result.status = "unsupported_platform"
        result.reason = f"{platform} 平台尚无首批 Adapter"
        return result
    try:
        adapter = BeisenAdapter() if platform == "beisen" else GenericAdapter()
        outcome = adapter.discover(seed)
        result.platform = outcome.platform
        result.accessible = outcome.accessible
        result.discovered = len(outcome.leads)
        if not outcome.leads:
            result.status = (
                "expired" if "均已截止" in outcome.reason else
                "no_2027_recruitment" if "校招栏目无公开岗位" in outcome.reason
                or "未发现2027届岗位" in outcome.reason
                or "未发现明确2027届校招活动" in outcome.reason
                else "pending_manual_review"
            )
            result.reason = outcome.reason
            return result
        statuses: list[str] = []
        organization_hint = None
        if seed.organization_type == "央企子公司":
            try:
                match = verify_child_seed(seed)
                if match:
                    organization_hint = (seed.organization_name, match)
            except (requests.RequestException, ValueError):
                pass
        for lead in outcome.leads:
            _save_lead_candidate(connection, seed, lead)
            if not _allowed_lead(seed, lead):
                update_candidate(connection, lead.url, "待核验", reason="招聘链接不在已核验企业域名内")
                statuses.append("pending_manual_review")
                continue
            lead_platform = detect_platform(lead.url, official_domain=seed.official_domain)
            if lead_platform not in SUPPORTED:
                update_candidate(connection, lead.url, "待核验", reason=f"{lead_platform} 平台尚未接入")
                statuses.append("unsupported_platform")
                continue
            if lead.structured_jobs:
                draft, evidence = beisen_draft(seed, lead)
                save_draft(connection, lead, draft, evidence)
                update_candidate(connection, lead.url, "待核验", reason="已读取北森2027岗位，缺少活动公告或通用投递入口")
                statuses.append("pending_manual_review")
                result.parsed += 1
                continue
            try:
                campaign_prefix(lead.url)
            except ValueError:
                update_candidate(connection, lead.url, "待核验", reason="公告位于根路径，当前专题解析器不支持")
                statuses.append("unsupported_platform")
                continue
            try:
                public_get(requests.Session(), lead.url)
                record = run(
                    lead.url, settings, candidate_notice_url=lead.url,
                    verified_organization=organization_hint,
                )
                result.parsed += 1
                if _has_formal_record(connection, lead.url):
                    result.formal += 1
                    result.formal_urls.append(lead.url)
                    statuses.append("success")
                elif record.status == "已截止":
                    statuses.append("expired")
                else:
                    statuses.append("pending_manual_review")
            except AccessRestricted as error:
                result.failed_url = error.url
                result.http_status = error.status_code
                result.reason = str(error)
                statuses.append("access_control")
            except Exception as error:
                code = error.response.status_code if isinstance(error, requests.HTTPError) and error.response is not None else None
                if code in {401, 403, 412, 429}:
                    result.http_status = code
                    result.failed_url = error.response.url
                    statuses.append("access_control")
                else:
                    statuses.append("parse_failed")
                result.reason = f"{type(error).__name__}；处理当前公告失败"
            if sleep_seconds:
                time.sleep(sleep_seconds)
        for priority in ("success", "access_control", "parse_failed", "expired", "pending_manual_review", "unsupported_platform"):
            if priority in statuses:
                result.status = priority
                break
        if not result.reason:
            result.reason = "；".join(dict.fromkeys(statuses))
        return result
    except AccessRestricted as error:
        result.status = "access_control"
        result.reason = str(error)
        result.failed_url = error.url
        result.http_status = error.status_code
        return result
    except Exception as error:
        code = error.response.status_code if isinstance(error, requests.HTTPError) and error.response is not None else None
        result.status = "access_control" if code in {401, 403, 412, 429} else "parse_failed"
        result.http_status = code
        result.reason = f"{type(error).__name__}：公开入口读取或解析失败"
        result.failed_url = seed.career_url
        return result


def run_batch(
    settings: Settings | None = None, seeds: list[Seed] | None = None, *,
    limit: int = 20, sleep_seconds: float = 1.0,
) -> tuple[BatchReport, Path]:
    settings = settings or Settings.from_env()
    selected = [seed for seed in (seeds if seeds is not None else load_seeds()) if seed.enabled][:limit]
    report = BatchReport(datetime.now(CHINA_TIME).isoformat(timespec="seconds"), len(selected))
    with closing(connect_database(settings.database_path)) as connection:
        sync_seeds(connection, selected)
        for index, seed in enumerate(selected, start=1):
            result = _process_seed(seed, settings, connection, sleep_seconds=sleep_seconds)
            report.results.append(result)
            save_seed_check(
                connection, seed, result.status, platform=result.platform,
                reason=result.reason, failed_url=result.failed_url, http_status=result.http_status,
                discovered=result.discovered, parsed=result.parsed,
                accessible=result.accessible,
            )
            print(f"[{index}/{len(selected)}] {seed.organization_name}: {result.status} ({result.platform})")
            if sleep_seconds:
                time.sleep(sleep_seconds)
        today = datetime.now(CHINA_TIME).date()
        source_by_official = {
            row["official_url"]: row["source_url"]
            for row in connection.execute("SELECT source_url,official_url FROM recruitment")
        }
        records = [
            record for record in list_records(connection)
            if is_product_record(record, today) and not connection.execute(
                "SELECT 1 FROM candidates WHERE notice_url=? AND state<>?",
                (source_by_official.get(record.official_url, record.official_url), "正式收录"),
            ).fetchone()
        ]
        formal_urls = {url for item in report.results for url in item.formal_urls}
        report.formal_records = [
            RecruitmentRecord.model_validate({name: row[name] for name in RecruitmentRecord.model_fields})
            for row in connection.execute("SELECT * FROM recruitment")
            if row["source_url"] in formal_urls
        ]
        # Existing product records are kept; this trial never deletes the old 69 candidates.
        path = export_excel(records, settings.output_path)
    output = settings.output_path.parent / "seed_batch_report.json"
    output.write_text(json.dumps({"summary": report.summary(), "results": [vars(r) for r in report.results]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, path
