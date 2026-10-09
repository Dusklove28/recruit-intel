"""One-page, bounded discovery from an employer's public career entry."""

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

from adapters.base import CampaignLead, DiscoveryOutcome, public_get
from discovery.platform_detector import detect_platform
from discovery.seed_registry import Seed


COHORT = re.compile(
    r"(?:2027|(?<!\d)27(?!\d))\s*(?:届|年|年度)?[^\n。；]{0,8}?"
    r"(?:校园招聘|校招|高校毕业生(?:招聘|统招)?|应届生招聘|毕业生招聘)"
    r"|(?:校园招聘|校招|高校毕业生招聘|应届生招聘|毕业生招聘)"
    r"[^\n。；]{0,8}?(?:2027|(?<!\d)27(?!\d))\s*(?:届|年|年度)?",
    re.I,
)
NON_CAMPUS = re.compile(r"社会招聘|社招|实习招聘|日常实习|暑期实习", re.I)
MAX_JSON_NODES = 3000
MAX_LEADS_PER_SEED = 3


def _looks_like_notice(url: str) -> bool:
    path = urlparse(url).path.lower()
    last = path.rsplit("/", 1)[-1]
    return (last.endswith((".html", ".htm")) and last not in {"index.html", "index.htm"}) or bool(
        re.search(r"/\d{12,}/index\.html?$", path)
    )


def _cohort_evidence(text: str) -> str:
    match = COHORT.search(text)
    return text[max(0, match.start() - 30):match.end() + 45].strip() if match else ""


def _json_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for script in soup.select('script[type="application/json"], script[type="application/ld+json"], script#__NEXT_DATA__')[:8]:
        try:
            root = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        stack = [root]
        checked = 0
        while stack and checked < MAX_JSON_NODES:
            checked += 1
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node[:300])
            elif isinstance(node, dict):
                label = next((node[key] for key in ("title", "name", "text") if isinstance(node.get(key), str)), "")
                href = next((node[key] for key in ("url", "href", "link") if isinstance(node.get(key), str)), "")
                if label and href and _cohort_evidence(label):
                    found.append((label, urljoin(base_url, href)))
                stack.extend(value for value in node.values() if isinstance(value, (dict, list)))
    return found


class GenericAdapter:
    def discover(self, seed: Seed, session: requests.Session | None = None) -> DiscoveryOutcome:
        client = session or requests.Session()
        response = public_get(client, seed.career_url)
        if "html" not in response.headers.get("Content-Type", "text/html").lower():
            return DiscoveryOutcome(seed, "custom", True, [], "入口不是 HTML 页面")
        soup = BeautifulSoup(response.text, "lxml")
        page_text = soup.get_text(" ", strip=True)[:100_000]
        platform = detect_platform(response.url, response.text, seed.official_domain)
        links = [
            (a.get_text(" ", strip=True), urljoin(response.url, a["href"]))
            for a in soup.select("a[href]")[:2000] if a.get("href")
        ]
        links.extend(_json_links(soup, response.url))
        leads: list[CampaignLead] = []
        seen: set[str] = set()
        for label, url in links:
            if not _cohort_evidence(label) or NON_CAMPUS.search(label):
                continue
            if urlparse(url).scheme not in {"http", "https"} or url in seen:
                continue
            # Links must be explicitly present on the seed's verified career page.
            seen.add(url)
            leads.append(CampaignLead(url, label[:180], response.url, _cohort_evidence(label)))
            if len(leads) >= MAX_LEADS_PER_SEED:
                break
        if not leads and _looks_like_notice(response.url) and _cohort_evidence(page_text):
            title = soup.title.get_text(" ", strip=True) if soup.title else f"{seed.organization_name}2027届校园招聘"
            leads.append(CampaignLead(response.url, title[:180], response.url, _cohort_evidence(page_text)))
        return DiscoveryOutcome(seed, platform, True, leads, "" if leads else "未发现明确2027届校招活动")
