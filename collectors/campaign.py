"""Explore only relevant pages within the input announcement's campaign directory."""

from collections import deque
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from urllib.parse import urldefrag, urljoin, urlparse

import requests

from collectors.generic import Announcement, AttachmentLink, fetch_announcement


MAX_CAMPAIGN_PAGES = 15
RELEVANT = re.compile(r"招聘|岗位|职位|投递|报名|网申|简章|指引|关于我们|申请", re.I)
RELEVANT_PATH = re.compile(r"(?:index|brochure|campus|position|job|post|detail|zhiyin|apply)", re.I)
APPLICATION = re.compile(r"报名|网申|立即投递|在线投递|投递入口|立即申请|进入系统|申请职位", re.I)
GUIDE_PATH = re.compile(r"zhiyin|guide|apply|registration|signup", re.I)
WEB_URL = re.compile(r"https?://[A-Za-z0-9./?&=%_#~+:-]+", re.I)
SCRIPT_OPEN = re.compile(r"window\.open\(\s*['\"](https?://[^'\"]+)['\"]", re.I)


@dataclass(frozen=True)
class ApplicationCandidate:
    url: str
    evidence_url: str
    priority: int


@dataclass(frozen=True)
class CampaignBundle:
    source_url: str
    pages: list[Announcement]
    attachments: list[AttachmentLink]
    application_candidates: list[ApplicationCandidate]
    warnings: list[str]


def campaign_prefix(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("仅支持 HTTP/HTTPS 招聘公告")
    directory = str(PurePosixPath(parsed.path).parent)
    prefix = directory.rstrip("/") + "/"
    if prefix == "/":
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
    candidates: list[ApplicationCandidate] = []
    for page in pages:
        guide = bool(
            GUIDE_PATH.search(urlparse(page.final_url).path)
            or re.search(r"官方网申平台|报名入口|网申入口", page.text)
        )
        if guide:
            for url in SCRIPT_OPEN.findall(page.html):
                candidates.append(ApplicationCandidate(url, page.final_url, 0))
            for url in WEB_URL.findall(page.text):
                candidates.append(ApplicationCandidate(url.rstrip(".)"), page.final_url, 2))
        for link in page.links:
            if APPLICATION.search(link.text):
                candidates.append(
                    ApplicationCandidate(urljoin(page.final_url, link.href), page.final_url, 1 if guide else 3)
                )
    deduplicated: dict[str, ApplicationCandidate] = {}
    for item in sorted(candidates, key=lambda item: item.priority):
        parsed = urlparse(item.url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            deduplicated.setdefault(item.url, item)
    return list(deduplicated.values())


def explore_campaign(source_url: str, session: requests.Session | None = None) -> CampaignBundle:
    host, prefix = campaign_prefix(source_url)
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
            if within_campaign(link.url, host, prefix) and link.url not in seen:
                attachments.append(link)
                seen.add(link.url)
    return CampaignBundle(
        source_url=source_url,
        pages=pages,
        attachments=attachments,
        application_candidates=_application_candidates(pages),
        warnings=warnings,
    )
