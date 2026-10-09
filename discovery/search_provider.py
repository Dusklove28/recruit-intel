"""Optional search fallback contract; no search-engine HTML scraping."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


@dataclass(frozen=True)
class CandidateURL:
    url: str
    title: str
    source: str
    score: int
    content: str = ""


class SearchProvider(Protocol):
    def search(self, query: str) -> list[CandidateURL]: ...


class MockSearchProvider:
    def __init__(self, results: dict[str, list[CandidateURL]] | None = None) -> None:
        self.results = results or {}

    def search(self, query: str) -> list[CandidateURL]:
        return list(self.results.get(query, []))


class TavilySearchProvider:
    """Small synchronous client for Tavily's public Search API."""

    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None, session: requests.Session | None = None) -> None:
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        self.api_key = (api_key or os.getenv("TAVILY_API_KEY", "")).strip()
        if not self.api_key:
            raise ValueError("缺少 TAVILY_API_KEY；请通过环境变量或项目 .env 配置")
        self.session = session or requests.Session()
        self.credits_used = 0
        self.search_calls = 0

    def search(self, query: str) -> list[CandidateURL]:
        self.search_calls += 1
        response = self.session.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "query": query,
                "topic": "general",
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": False,
                "include_raw_content": False,
                "include_usage": True,
                "country": "china",
            },
            timeout=(8, 30),
        )
        response.raise_for_status()
        payload = response.json()
        self.credits_used += int((payload.get("usage") or {}).get("credits", 0))
        # The provider returns only public search leads. Every URL remains
        # unverified until a later direct request confirms its official source.
        return [
            CandidateURL(
                url=str(item.get("url", "")),
                title=str(item.get("title", "")),
                source="tavily",
                score=int(float(item.get("score", 0)) * 100),
                content=str(item.get("content", "")),
            )
            for item in payload.get("results", [])
            if item.get("url")
        ]


def search_queries(organization_name: str, official_domain: str) -> list[str]:
    queries = [
        f'"{organization_name}" 招聘官网',
        f'"{organization_name}" 2027 校园招聘',
        f'"{organization_name}" 2027届 校招 官网',
    ]
    if official_domain:
        queries.append(f'site:{official_domain} 2027 招聘')
    return queries


def queries_within_budget(
    organization_name: str, official_domain: str, *, max_queries: int = 2,
) -> list[str]:
    """Return targeted company queries, capped at the approved per-company budget."""
    if max_queries < 0 or max_queries > 3:
        raise ValueError("每家公司搜索预算必须在0到3次之间")
    return search_queries(organization_name, official_domain)[:max_queries]


def rank_candidate(url: str, official_domain: str) -> int:
    """Search results are only leads; this score never authorizes formal inclusion."""
    host = (urlparse(url).hostname or "").lower()
    domain = official_domain.lower().lstrip(".")
    discovery_only = _discovery_only_kind(url)
    if discovery_only:
        return 10
    if host == domain or host.endswith("." + domain):
        return 100
    if host.endswith((
        ".zhiye.com", ".mokahr.com", ".jobs.feishu.cn", ".hotjob.cn",
        ".iguopin.com", ".iguopin.cn",
    )) or host in {"campus.51job.com", "campus.chinahr.com", "campus.zhaopin.com"}:
        return 80
    if host.endswith((".iguopin.com", ".iguopin.cn")):
        return 70
    if host.endswith((".sasac.gov.cn", ".gov.cn")):
        return 50
    # Unknown commercial domains remain candidate official sites until the
    # direct page is checked for the named employer and recruitment context.
    return 90


def _discovery_only_kind(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if (
        host == "campus.51job.com" or host == "campus.chinahr.com" or host == "campus.zhaopin.com"
        or host.endswith((".zhiye.com", ".mokahr.com", ".jobs.feishu.cn", ".hotjob.cn", ".iguopin.com", ".iguopin.cn"))
    ):
        return ""
    if host.endswith((".edu.cn", ".edu")):
        return "高校就业网仅作为发现线索"
    if host.endswith((".gov.cn", ".sasac.gov.cn")):
        return "政府转载仅作为发现线索"
    if host == "mp.weixin.qq.com" or host.endswith(".weixin.qq.com"):
        return "微信公众号仅作为发现线索"
    aggregators = (
        "nowcoder.com", "yingjiesheng.com", "yjbys.com", "jobui.com", "lagou.com",
        "liepin.com", "zhaopin.com", "51job.com", "zhipin.com", "boss.com",
        "xiaohongshu.com", "sohu.com", "163.com", "qq.com", "baijiahao.baidu.com",
        "wondercv.com", "gaoxiaojob.com", "eoffcn.com", "gwy.com", "fenbi.com",
        "hahazhao.com", "yinhangzhaopin.com", "gaodun.com", "niuqizp.com",
        "yuantuedu.com", "wjx.top",
        "wjx.cn",
    )
    if any(host == domain or host.endswith("." + domain) for domain in aggregators):
        return "第三方聚合网站/问卷平台仅作为发现线索"
    return ""


def discovery_only_kind(url: str) -> str:
    """Public lead sources that cannot establish an official employer source."""
    return _discovery_only_kind(url)


def rank_search_result(url: str, official_domain: str, search_score: int = 0) -> int:
    """Apply source trust before relevance so aggregators never outrank official pages."""
    trust = rank_candidate(url, official_domain)
    return trust * 1000 + max(0, min(999, search_score))
