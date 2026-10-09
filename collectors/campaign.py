"""Explore only relevant pages within the input announcement's campaign directory."""

from collections import deque
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse

import requests

from collectors.generic import Announcement, AttachmentLink, fetch_announcement
from processing.evidence_resolver import ApplicationEvidence, resolve_application_candidates


MAX_CAMPAIGN_PAGES = 15
RELEVANT = re.compile(r"招聘|岗位|职位|投递|报名|网申|简章|指引|关于我们|申请", re.I)
RELEVANT_PATH = re.compile(r"(?:index|brochure|campus|position|job|post|detail|zhiyin|apply)", re.I)


ApplicationCandidate = ApplicationEvidence


@dataclass(frozen=True)
class CampaignBundle:
    source_url: str
    pages: list[Announcement]
    attachments: list[AttachmentLink]
    application_candidates: list[ApplicationCandidate]
    warnings: list[str]
    content_evidence_urls: list[str] = field(default_factory=list)
    attachment_evidence_fields: tuple[str, ...] | None = None


def campaign_prefix(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("仅支持 HTTP/HTTPS 招聘公告")
    directory = str(PurePosixPath(parsed.path).parent)
    prefix = directory.rstrip("/") + "/"
    single_query = any(key in parse_qs(parsed.query) for key in ("id", "aId", "annoId"))
    if prefix == "/" and not single_query:
        raise ValueError("公告 URL 缺少可限定的招聘专题路径")
    return parsed.hostname.lower(), prefix


def within_campaign(url: str, host: str, prefix: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname == host and parsed.path.startswith(prefix)


def _is_relevant_page(url: str, label: str) -> bool:
    path = urlparse(url).path
    if not (path.endswith("/") or path.lower().endswith(('.html', '.htm'))):
        return False
    return bool(RELEVANT.search(label) or RELEVANT_PATH.search(PurePosixPath(path).name))


def _application_candidates(pages: list[Announcement]) -> list[ApplicationCandidate]:
    return resolve_application_candidates(pages)


def explore_campaign(source_url: str, session: requests.Session | None = None) -> CampaignBundle:
    host, prefix = campaign_prefix(source_url)
    single_query = any(key in parse_qs(urlparse(source_url).query) for key in ("id", "aId", "annoId"))
    client = session or requests.Session()
    queue = deque([source_url])
    queued = {source_url}
    pages: list[Announcement] = []
    warnings: list[str] = []
    campaign_year: str | None = None
    while queue and len(pages) < MAX_CAMPAIGN_PAGES:
        url = queue.popleft()
        try:
            page = fetch_announcement(url, client)
        except Exception as error:
            if not pages:
                raise
            warnings.append(f"专题页面读取失败：{url}（{type(error).__name__}）")
            continue
        if not within_campaign(page.final_url, host, prefix):
            warnings.append(f"跳转离开招聘专题，已跳过：{url}")
            continue
        pages.append(page)
        if single_query:
            break
        if campaign_year is None:
            match = re.search(r"20\d{2}届", page.text)
            campaign_year = match.group(0) if match else None
        for link in page.links:
            link_year = re.search(r"20\d{2}届", link.text)
            if campaign_year and link_year and link_year.group(0) != campaign_year:
                continue
            absolute, _fragment = urldefrag(urljoin(page.final_url, link.href))
            if absolute in queued or not within_campaign(absolute, host, prefix):
                continue
            if _is_relevant_page(absolute, link.text):
                queue.append(absolute)
                queued.add(absolute)
    if queue:
        warnings.append(f"招聘专题页面超过 {MAX_CAMPAIGN_PAGES} 页，本次未继续探索")
    attachments: list[AttachmentLink] = []
    seen: set[str] = set()
    for page in pages:
        for link in page.attachments:
            attachment_in_scope = (
                (urlparse(link.url).hostname or "").lower() == host
                if single_query else within_campaign(link.url, host, prefix)
            )
            if attachment_in_scope and link.url not in seen:
                attachments.append(link)
                seen.add(link.url)
    return CampaignBundle(
        source_url=source_url,
        pages=pages,
        attachments=attachments,
        application_candidates=_application_candidates(pages),
        warnings=warnings,
    )
