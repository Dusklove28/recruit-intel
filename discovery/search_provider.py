"""Optional search fallback contract; no search-engine HTML scraping."""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class CandidateURL:
    url: str
    title: str
    source: str
    score: int


class SearchProvider(Protocol):
    def search(self, query: str) -> list[CandidateURL]: ...


class MockSearchProvider:
    def __init__(self, results: dict[str, list[CandidateURL]] | None = None) -> None:
        self.results = results or {}

    def search(self, query: str) -> list[CandidateURL]:
        return list(self.results.get(query, []))


def search_queries(organization_name: str, official_domain: str) -> list[str]:
    return [
        f'"{organization_name}" 2027 校园招聘',
        f'"{organization_name}" 2027 校招 官网',
        f'"{organization_name}" 2027 应届生 招聘',
        f'site:{official_domain} 2027 招聘',
    ]


def rank_candidate(url: str, official_domain: str) -> int:
    """Search results are only leads; this score never authorizes formal inclusion."""
    host = (urlparse(url).hostname or "").lower()
    domain = official_domain.lower().lstrip(".")
    if host == domain or host.endswith("." + domain):
        return 100
    if host.endswith((".zhiye.com", ".mokahr.com", ".jobs.feishu.cn")) or host == "campus.51job.com":
        return 80
    if host.endswith((".iguopin.com", ".iguopin.cn")):
        return 70
    if host.endswith((".sasac.gov.cn", ".gov.cn")):
        return 50
    return 10
