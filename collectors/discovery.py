"""Bounded discovery from the four approved official recruitment columns."""

from dataclasses import dataclass
import re
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests


SASAC_INDEX = "http://wap.sasac.gov.cn/n2588035/n2588325/n2588350/index.html"
BEIJING_INDEX = "https://gzw.beijing.gov.cn/yggq/gqzp/"
SHANGHAI_INDEX = "https://www.gzw.sh.gov.cn/shgzw_xxgk_cqzp/"
SHENZHEN_INDEX = "https://gzw.sz.gov.cn/xyzp/content/post_9397139.html"
SOURCE_PAGES = {
    "国务院国资委": [SASAC_INDEX],
    "北京市国资委": [BEIJING_INDEX],
    "上海市国资委": [SHANGHAI_INDEX],
    "深圳市国资委": [SHENZHEN_INDEX],
}
TITLE_PATTERN = re.compile(r"2027.*(?:校园招聘|校招|应届|秋招)|(?:校园招聘|校招|应届|秋招).*2027")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


@dataclass(frozen=True)
class Candidate:
    source: str
    discovery_url: str
    title: str
    notice_url: str


def parse_listing(html: str, page_url: str, source: str) -> list[Candidate]:
    """Read only explicit 2027 campus links; never traverse a whole site."""
    items: list[Candidate] = []
    seen: set[str] = set()
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        title = anchor.get_text(" ", strip=True).lstrip("• ").strip()
        if not TITLE_PATTERN.search(title):
            continue
        notice_url = urljoin(page_url, anchor["href"])
        if urlparse(notice_url).scheme not in {"http", "https"} or notice_url in seen:
            continue
        seen.add(notice_url)
        items.append(Candidate(source, page_url, title, notice_url))
    return items


def recent_sasac_pages(html: str, page_url: str) -> list[str]:
    """The site's numbered archive runs oldest to newest; inspect six recent pages."""
    links = {
        int(match.group(1)): urljoin(page_url, anchor["href"])
        for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True)
        if (match := re.search(r"index_7325475_(\d+)\.html", anchor["href"]))
    }
    return [links[number] for number in sorted(links)[-6:]]


def discover_approved_sources(
    session: requests.Session | None = None, *, delay_seconds: float = 1.0
) -> tuple[list[Candidate], list[str], int]:
    client = session or requests.Session()
    if client.headers.get("User-Agent", "").startswith("python-requests"):
        client.headers["User-Agent"] = USER_AGENT
    candidates: list[Candidate] = []
    warnings: list[str] = []
    duplicate_links = 0
    seen: set[str] = set()
    for source, pages in SOURCE_PAGES.items():
        queue = list(pages)
        for page in queue:
            try:
                response = client.get(page, timeout=(10, 30))
                response.raise_for_status()
                response.encoding = "utf-8"
                if source == "国务院国资委" and page == SASAC_INDEX:
                    queue.extend(recent_sasac_pages(response.text, response.url))
                for candidate in parse_listing(response.text, response.url, source):
                    if candidate.notice_url in seen:
                        duplicate_links += 1
                    else:
                        seen.add(candidate.notice_url)
                        candidates.append(candidate)
            except requests.RequestException as error:
                warnings.append(f"{source}栏目读取失败：{page}（{type(error).__name__}）")
            if delay_seconds:
                time.sleep(delay_seconds)
    return candidates, warnings, duplicate_links
