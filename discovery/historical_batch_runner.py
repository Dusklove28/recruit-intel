"""Reverify one bounded batch of historical employer source leads."""

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from adapters.base import AccessRestricted, public_get
from adapters.beisen import BeisenAdapter
from adapters.generic import GenericAdapter
from config import Settings
from discovery.historical_seed_import import HistoricalSeed, load_priority_batch
from discovery.platform_detector import detect_platform
from discovery.search_provider import (
    TavilySearchProvider,
    discovery_only_kind,
    queries_within_budget,
    rank_search_result,
)
from discovery.seed_registry import Seed
from discovery.source_registry import SourceRecord, export_source_registry, upsert_source
from extractor.llm_extractor import reset_usage, usage_snapshot
from processing.organization_registry import verify_central_group
from storage.database import connect_database


CHINA_TZ = timezone(timedelta(hours=8))
JOB_TERMS = re.compile(r"招聘|校招|校园招聘|应届生|毕业生|career|recruit", re.I)
OLD_CAMPAIGN = re.compile(r"202[0-6].{0,12}(?:校招|校园招聘)|(?:校招|校园招聘).{0,12}202[0-6]", re.I)
ATS_PLATFORMS = frozenset({"moka", "beisen", "feishu", "51job_campus", "hotjob", "chinahr", "zhilian", "iguopin"})


def _page_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return soup.get_text(" ", strip=True)[:150_000]


def _matches_organization(text: str, name: str) -> bool:
    compact = re.sub(r"\s+", "", text).casefold()
    target = re.sub(r"\s+", "", name).casefold()
    return len(target) >= 3 and target in compact


def _looks_current_source(text: str, name: str) -> bool:
    return _matches_organization(text, name) and bool(JOB_TERMS.search(text))


def _career_seed(item: HistoricalSeed, url: str, platform: str, official_domain: str) -> Seed:
    verified_group = None
    identity = None
    # The historical display name is not enough to infer organization type.
    # Only an exact match in the live official SASAC directory sets the type.
    try:
        identity = verify_central_group(item.canonical_name)
        if identity:
            verified_group = identity.parent_unit
    except (requests.RequestException, ValueError):
        pass
    return Seed(
        item.canonical_name,
        identity.unit_type if identity else None,
        verified_group,
        url,
        official_domain,
        platform if platform in {"moka", "beisen", "feishu", "51job_campus", "hotjob", "zhilian", "chinahr", "iguopin", "wechat", "custom", "unknown"} else "unknown",
        url,
        datetime.now(CHINA_TZ).date(),
        True,
    )


def _probe_url(session: requests.Session, item: HistoricalSeed, url: str):
    response = public_get(session, url)
    if "html" not in response.headers.get("Content-Type", "text/html").lower():
        return response, "", detect_platform(response.url, official_domain=item.suggested_domain or None), False
    text = _page_text(response.text)
    platform = detect_platform(response.url, response.text, item.suggested_domain or None)
    if not _looks_current_source(text, item.canonical_name):
        return response, text, platform, False
    return response, text, platform, True


def _discover_campaigns(seed: Seed) -> tuple[list, str]:
    if seed.platform not in {"custom", "unknown", "beisen"}:
        return [], ""
    adapter = BeisenAdapter() if seed.platform == "beisen" else GenericAdapter()
    outcome = adapter.discover(seed)
    return outcome.leads, outcome.reason


def _campaign_fallback(
    item: HistoricalSeed, source_seed: Seed, provider: TavilySearchProvider,
    remaining_budget: int, sleep_seconds: float,
) -> tuple[Seed | None, int, str]:
    if remaining_budget <= 0:
        return None, 0, ""
    query_list = [f'"{item.canonical_name}" 2027 校园招聘']
    if source_seed.official_domain:
        query_list.append(f'site:{source_seed.official_domain} 2027 招聘')
    calls = 0
    for query in query_list[:remaining_budget]:
        try:
            candidates = provider.search(query)
        except requests.RequestException as error:
            return None, calls + 1, f"Tavily 招聘发现失败：{type(error).__name__}"
        calls += 1
        candidates = sorted(
            candidates,
            key=lambda candidate: rank_search_result(candidate.url, "", candidate.score),
            reverse=True,
        )[:5]
        for candidate in candidates:
            if rank_search_result(candidate.url, "", candidate.score) < 70_000:
                continue
            try:
                response = public_get(requests.Session(), candidate.url)
            except AccessRestricted:
                # Respect the block; do not try a different browser mode or
                # alternate host for this candidate.
                return None, calls, "搜索结果访问受限"
            except requests.RequestException:
                continue
            if discovery_only_kind(response.url):
                continue
            if "html" not in response.headers.get("Content-Type", "text/html").lower():
                continue
            text = _page_text(response.text)
            platform = detect_platform(response.url, response.text, source_seed.official_domain)
            source_host = (urlparse(source_seed.career_url).hostname or "").lower()
            candidate_host = (urlparse(response.url).hostname or "").lower()
            same_official_host = bool(
                source_seed.official_domain
                and (candidate_host == source_seed.official_domain
                     or candidate_host.endswith("." + source_seed.official_domain))
            )
            if not same_official_host and platform not in ATS_PLATFORMS:
                continue
            if not _matches_organization(text, item.canonical_name) or not JOB_TERMS.search(text):
                continue
            candidate_seed = _career_seed(item, response.url, platform, source_seed.official_domain)
            try:
                leads, _ = _discover_campaigns(candidate_seed)
            except AccessRestricted:
                return None, calls, "招聘专题访问受限"
            except (requests.RequestException, ValueError):
                leads = []
            if leads:
                return candidate_seed, calls, ""
        if sleep_seconds:
            time.sleep(sleep_seconds)
    return None, calls, ""


def _candidate_source_type(platform: str) -> str:
    return {
        "beisen": "北森招聘系统", "moka": "Moka招聘系统", "feishu": "飞书招聘系统",
        "51job_campus": "前程无忧校园招聘专题", "hotjob": "HotJob招聘系统",
        "chinahr": "中华英才网招聘专题", "zhilian": "智联招聘专题",
        "iguopin": "国聘招聘系统", "wechat": "微信公众号线索",
    }.get(platform, "企业招聘官网")


def _records_from_history(
    items: list[HistoricalSeed], provider: TavilySearchProvider,
    *, sleep_seconds: float, search_enabled: bool = True,
) -> tuple[list[SourceRecord], list[Seed], dict[str, dict]]:
    records: list[SourceRecord] = []
    usable_seeds: list[Seed] = []
    metrics: dict[str, dict] = {}
    started = time.monotonic()
    for index, item in enumerate(items, 1):
        before_calls, before_credits = provider.search_calls, provider.credits_used
        preflight_calls = 0
        urls = list(dict.fromkeys(url for url in (item.candidate_root_url, item.historical_url) if url))
        source_record: SourceRecord | None = None
        resolved_seed: Seed | None = None
        status = "not_found"
        evidence_url = ""
        failure_reason = "没有可用的公开入口"
        search_queries_used = 0
        tried: set[str] = set()
        session = requests.Session()

        def accept_url(url: str, discovered_by: str) -> bool:
            nonlocal source_record, resolved_seed, status, evidence_url, failure_reason
            if not url or url in tried:
                return False
            tried.add(url)
            try:
                response, text, platform, relevant = _probe_url(session, item, url)
            except AccessRestricted as error:
                status = "access_control"
                failure_reason = f"公开访问受限 HTTP {error.status_code or 'unknown'}"
                evidence_url = error.url
                return False
            except requests.RequestException as error:
                failure_reason = f"公开页面读取失败：{type(error).__name__}"
                evidence_url = url
                return False
            except (ValueError, OSError) as error:
                failure_reason = f"页面无法解析：{type(error).__name__}"
                evidence_url = url
                return False

            final_url = response.url
            host = (urlparse(final_url).hostname or "").lower()
            suggested = item.suggested_domain.lower().lstrip(".")
            lead_only_reason = discovery_only_kind(final_url)
            if lead_only_reason:
                status = "pending_manual_review"
                failure_reason = lead_only_reason
                evidence_url = final_url
                return False
            is_suggested_host = bool(
                suggested
                and (host == suggested or host.endswith("." + suggested))
            )
            if not is_suggested_host:
                status = "pending_manual_review"
                failure_reason = "访问页面域名与历史核验域名不一致，缺少企业官网关联证据"
                evidence_url = final_url
                return False
            page_is_recruitment = bool(JOB_TERMS.search(text))
            if not relevant:
                if OLD_CAMPAIGN.search(text) or OLD_CAMPAIGN.search(url):
                    status = "expired_source"
                    failure_reason = "入口内容指向2025/2026历史招聘活动"
                    evidence_url = final_url
                return False

            # A directly readable, company-branded recruitment page is enough
            # to verify the source mapping. Organization type and ownership
            # remain blank unless the official organization registry proves it.
            if not page_is_recruitment or (platform in ATS_PLATFORMS and not _matches_organization(text, item.canonical_name)):
                status = "pending_manual_review"
                failure_reason = "页面可访问，但企业招聘源归属证据不足"
                evidence_url = final_url
                return False
            status = "redirected" if final_url.rstrip("/") != url.rstrip("/") else "verified"
            failure_reason = ""
            evidence_url = final_url
            official_domain = "" if platform in ATS_PLATFORMS else suggested
            resolved_seed = _career_seed(item, final_url, platform, official_domain)
            source_record = SourceRecord(
                canonical_name=item.canonical_name,
                display_name=item.canonical_name,
                organization_type=resolved_seed.organization_type,
                parent_group=resolved_seed.parent_group,
                official_domain=official_domain,
                source_type=_candidate_source_type(platform),
                current_source_url=final_url,
                platform=platform,
                historical_url=item.historical_url,
                historical_platform=item.historical_platform,
                discovered_by=discovered_by,
                evidence_url=evidence_url,
                verified_at=datetime.now(CHINA_TZ).date().isoformat(),
                status=status,
            )
            return True

        # Candidate root precedes the old campaign link. A historical event
        # URL is never promoted merely because it responds successfully.
        for url in urls:
            if accept_url(url, "historical_candidate_root" if url == item.candidate_root_url else "historical_url"):
                break
            if status == "access_control":
                break

        # Search only when the historical entry did not produce a verified
        # current recruiting source. Search results are direct-checked before
        # any registry field is populated.
        if search_enabled and source_record is None and status != "access_control":
            query_budget = max(0, 2 - preflight_calls)
            query_list = queries_within_budget(item.canonical_name, item.suggested_domain, max_queries=query_budget)
            for query in query_list:
                search_queries_used += 1
                try:
                    candidates = provider.search(query)
                except requests.RequestException as error:
                    status = "pending_manual_review"
                    failure_reason = f"Tavily 搜索失败：{type(error).__name__}"
                    break
                candidates = sorted(
                    candidates,
                    key=lambda candidate: rank_search_result(candidate.url, "", candidate.score),
                    reverse=True,
                )[:5]
                for candidate in candidates:
                    # Search results from aggregators and social media are
                    # useful only as leads; they cannot verify a formal source.
                    rank = rank_search_result(candidate.url, "", candidate.score)
                    if rank < 70_000:
                        status = "pending_manual_review"
                        failure_reason = discovery_only_kind(candidate.url) or "搜索结果级别不足以确认正式招聘源"
                        evidence_url = candidate.url
                        continue
                    if accept_url(candidate.url, "tavily"):
                        break
                    if status == "access_control":
                        break
                if source_record or status == "access_control":
                    break
                if sleep_seconds:
                    time.sleep(sleep_seconds)

        if source_record is None:
            source_record = SourceRecord(
                canonical_name=item.canonical_name,
                display_name=item.canonical_name,
                official_domain="",
                source_type="发现线索（待核验）" if evidence_url else "",
                current_source_url="",
                platform="unknown",
                historical_url=item.historical_url,
                historical_platform=item.historical_platform,
                discovered_by="historical_seed" if not search_queries_used else "tavily",
                evidence_url=evidence_url,
                verified_at=datetime.now(CHINA_TZ).date().isoformat(),
                status=status,
            )
        campaign_search_calls = 0
        campaign_reason = ""
        if resolved_seed and search_enabled:
            try:
                current_leads, discovery_reason = _discover_campaigns(resolved_seed)
            except AccessRestricted as error:
                current_leads, discovery_reason = [], f"公开招聘接口访问受限 HTTP {error.status_code or 'unknown'}"
            except (requests.RequestException, ValueError) as error:
                current_leads, discovery_reason = [], f"招聘入口读取失败：{type(error).__name__}"
            if not current_leads:
                remaining = max(0, 2 - preflight_calls - (provider.search_calls - before_calls))
                campaign_seed, campaign_search_calls, campaign_reason = _campaign_fallback(
                    item, resolved_seed, provider, remaining, sleep_seconds,
                )
                if campaign_seed:
                    resolved_seed = campaign_seed
                    source_record = SourceRecord(
                        **{
                            **asdict(source_record),
                            "current_source_url": campaign_seed.career_url,
                            "platform": campaign_seed.platform,
                            "discovered_by": "tavily_campaign_fallback",
                            "evidence_url": campaign_seed.career_url,
                        }
                    )
                    # Refresh the database and workbook row with the newly
                    # direct-checked official campaign page.
                elif discovery_reason:
                    failure_reason = discovery_reason
        records.append(source_record)
        if resolved_seed:
            usable_seeds.append(resolved_seed)
        metrics[item.canonical_name] = {
            "source_status": source_record.status,
            "source_url": source_record.current_source_url,
            "evidence_url": source_record.evidence_url,
            "reason": failure_reason,
            "tavily_queries": search_queries_used,
            "tavily_calls": provider.search_calls - before_calls + preflight_calls,
            "tavily_credits": provider.credits_used - before_credits + preflight_calls,
            "preflight_tavily_calls": preflight_calls,
            "campaign_search_calls": campaign_search_calls,
            "campaign_reason": campaign_reason,
        }
        print(f"[{index}/{len(items)}] {item.canonical_name}: {source_record.status} ({source_record.platform})")
        if sleep_seconds:
            time.sleep(sleep_seconds)

    metrics["_batch"] = {"elapsed_seconds": round(time.monotonic() - started, 2)}
    return records, usable_seeds, metrics


def run_historical_batch(
    *, settings: Settings | None = None,
    input_path: Path | None = None,
    limit: int = 100,
    sleep_seconds: float = 0.25,
    search_enabled: bool = True,
) -> dict:
    settings = settings or Settings.from_env()
    root = Path(__file__).resolve().parents[1]
    input_path = input_path or root / "央国企历史招聘SourceSeed库_2025-2026_复核版.xlsx"
    items = load_priority_batch(input_path, limit=limit)
    provider = TavilySearchProvider()
    reset_usage()
    started = time.monotonic()
    source_records, seeds, per_company = _records_from_history(
        items, provider, sleep_seconds=sleep_seconds, search_enabled=search_enabled,
    )

    with connect_database(settings.database_path) as connection:
        for record in source_records:
            upsert_source(connection, record)
    registry_path = root / "data" / "output" / "source_registry_verified.xlsx"
    export_source_registry(source_records, registry_path)

    # Reuse the existing one-URL discovery/extraction path for source entries
    # that passed direct evidence checks. A single-company error stays local.
    from discovery.batch_runner import run_batch

    campaign_summary = None
    if seeds:
        batch_report, product_path = run_batch(settings, seeds, limit=len(seeds), sleep_seconds=sleep_seconds)
        campaign_summary = batch_report.summary()
    else:
        product_path = settings.output_path
        campaign_summary = {"seed_total": 0, "discovered_2027_campaigns": 0, "parsed_campaigns": 0, "formal_campaigns": 0}

    final_usage = usage_snapshot()
    status_counts = Counter(record.status for record in source_records)
    platform_counts = Counter(record.platform for record in source_records)
    report = {
        "checked_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "seed_total": len(items),
        "source_registry": {
            "status_counts": dict(status_counts),
            "verified": status_counts["verified"] + status_counts["redirected"],
            "expired_source": status_counts["expired_source"],
            "rediscovered_source": sum(metric["source_status"] in {"verified", "redirected"} and metric["tavily_calls"] > 0 for name, metric in per_company.items() if name != "_batch"),
            "pending_manual_review": status_counts["pending_manual_review"],
            "access_control": status_counts["access_control"],
            "not_found": status_counts["not_found"],
            "unsupported": status_counts["unsupported"],
            "platforms": dict(platform_counts),
        },
        "current_2027_batch": campaign_summary,
        "tavily": {
            "calls": provider.search_calls,
            "credits": provider.credits_used,
            "batch_calls_after_preflight": provider.search_calls,
            "batch_credits_after_preflight": provider.credits_used,
            "company_query_budget_max": 2,
            "enabled": search_enabled,
            "prior_interrupted_run_usage": "unknown; previous run stopped before usage report was saved",
        },
        "qwen": final_usage,
        "average_seconds_per_company": round((time.monotonic() - started) / len(items), 2) if items else 0,
        "source_registry_xlsx": str(registry_path),
        "product_xlsx": str(product_path),
        "companies": [
            {**asdict(item), **per_company.get(item.canonical_name, {})}
            for item in items
        ],
        "sources": [asdict(item) for item in source_records],
    }
    report_path = root / "data" / "output" / "source_registry_batch_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
