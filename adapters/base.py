"""Shared discovery result and safe public-page fetch."""

from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from discovery.seed_registry import Seed


class AccessRestricted(RuntimeError):
    """A site requires a decision before any stronger access method is attempted."""

    def __init__(self, url: str, status_code: int | None = None, reason: str = "访问受限") -> None:
        self.url = url
        self.status_code = status_code
        super().__init__(f"{reason}（HTTP {status_code}）：{url}" if status_code else f"{reason}：{url}")


@dataclass(frozen=True)
class CampaignLead:
    url: str
    title: str
    evidence_url: str
    cohort_evidence: str
    structured_jobs: list[dict] = field(default_factory=list)
    listing_url: str | None = None


@dataclass(frozen=True)
class DiscoveryOutcome:
    seed: Seed
    platform: str
    accessible: bool
    leads: list[CampaignLead]
    reason: str = ""


HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}


def public_get(session: requests.Session, url: str) -> requests.Response:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("仅支持公开 HTTP/HTTPS 招聘入口")
    response = session.get(url, headers=HEADERS, timeout=(8, 20))
    if response.status_code in {401, 403, 412, 429}:
        raise AccessRestricted(url, response.status_code)
    response.raise_for_status()
    if response.encoding is None or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    final_path = urlparse(response.url).path.lower()
    if any(part in final_path for part in ("/login", "/signin", "/captcha")):
        raise AccessRestricted(response.url, response.status_code, "入口跳转至登录或验证页面")
    head = response.text[:20000].lower()
    if any(marker in head for marker in ("js challenge", "checking your browser", "请开启javascript以继续访问")):
        raise AccessRestricted(url, response.status_code, "疑似访问控制页面")
    visible = BeautifulSoup(response.text[:30000], "lxml").get_text(" ", strip=True)
    if any(marker in visible for marker in ("请完成安全验证", "访问验证", "请先通过验证码")) and not any(
        term in visible for term in ("招聘公告", "校园招聘", "招聘岗位")
    ):
        raise AccessRestricted(url, response.status_code, "疑似访问控制页面")
    return response
