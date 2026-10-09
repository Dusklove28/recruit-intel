"""Resolve explicit application evidence from pages inside one known campaign."""

from dataclasses import dataclass
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from collectors.generic import Announcement


APPLICATION_LABEL = re.compile(r"报名|网申|立即投递|在线投递|投递入口|立即申请|进入系统|申请职位", re.I)
APPLICATION_KEY = re.compile(r"^(?:apply_?url|application_?url|registration_?url|online_?apply|网申入口|报名入口)$", re.I)
GUIDE_PATH = re.compile(r"zhiyin|guide|apply|registration|signup", re.I)
WEB_URL = re.compile(r"https?://[A-Za-z0-9./?&=%_#~+:-]+", re.I)
SCRIPT_OPEN = re.compile(r"(?:window\.open|location\.href\s*=)\s*\(?\s*['\"](https?://[^'\"]+)['\"]", re.I)


@dataclass(frozen=True)
class ApplicationEvidence:
    url: str
    evidence_url: str
    priority: int


def _json_application_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    for script in soup.select('script[type="application/json"], script[type="application/ld+json"], script#__NEXT_DATA__')[:8]:
        try:
            root = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        stack = [root]
        checked = 0
        while stack and checked < 2000:
            checked += 1
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node[:200])
            elif isinstance(node, dict):
                for key, value in node.items():
                    if APPLICATION_KEY.fullmatch(key) and isinstance(value, str):
                        urls.append(urljoin(base_url, value))
                    elif isinstance(value, (dict, list)):
                        stack.append(value)
    return urls


def resolve_application_candidates(pages: list[Announcement]) -> list[ApplicationEvidence]:
    """A job list alone never counts as an application entry."""
    found: list[ApplicationEvidence] = []
    for page in pages:
        guide = bool(GUIDE_PATH.search(urlparse(page.final_url).path) or re.search(r"官方网申平台|报名入口|网申入口", page.text))
        soup = BeautifulSoup(page.html, "lxml")
        for url in _json_application_urls(soup, page.final_url):
            found.append(ApplicationEvidence(url, page.final_url, 0))
        for element in soup.select("[onclick], [data-apply-url], [data-application-url]")[:500]:
            label = element.get_text(" ", strip=True)
            for attr in ("data-apply-url", "data-application-url"):
                if element.get(attr):
                    found.append(ApplicationEvidence(urljoin(page.final_url, element[attr]), page.final_url, 1))
            if APPLICATION_LABEL.search(label) or guide:
                for url in SCRIPT_OPEN.findall(element.get("onclick", "")):
                    found.append(ApplicationEvidence(url, page.final_url, 1))
        if guide:
            for url in SCRIPT_OPEN.findall(page.html):
                found.append(ApplicationEvidence(url, page.final_url, 1))
        for match in WEB_URL.finditer(page.text):
            context = page.text[max(0, match.start() - 90):match.end() + 25]
            if re.search(r"报名|网申|投递|招聘平台|登录网址", context):
                found.append(ApplicationEvidence(match.group().rstrip(".)]）"), page.final_url, 2))
        for link in page.links:
            if APPLICATION_LABEL.search(link.text):
                found.append(ApplicationEvidence(urljoin(page.final_url, link.href), page.final_url, 1 if guide else 3))
    deduplicated: dict[str, ApplicationEvidence] = {}
    for item in sorted(found, key=lambda item: item.priority):
        parsed = urlparse(item.url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            deduplicated.setdefault(item.url, item)
    return list(deduplicated.values())
