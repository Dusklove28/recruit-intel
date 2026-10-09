import pytest

from discovery.search_provider import (
    TavilySearchProvider,
    queries_within_budget,
    rank_candidate,
    rank_search_result,
    discovery_only_kind,
)


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "results": [{"url": "https://job.a.cn/campus/2027", "title": "2027校园招聘", "score": 0.93}],
            "usage": {"credits": 1},
        }


class Session:
    def __init__(self):
        self.call = None

    def post(self, url, **kwargs):
        self.call = (url, kwargs)
        return Response()


def test_tavily_client_uses_bounded_basic_search_and_counts_usage():
    session = Session()
    provider = TavilySearchProvider(api_key="test-only", session=session)

    results = provider.search('"甲集团" 2027 校园招聘')

    assert provider.search_calls == 1
    assert provider.credits_used == 1
    assert len(results) == 1
    assert session.call[0] == "https://api.tavily.com/search"
    assert session.call[1]["json"]["max_results"] == 5
    assert session.call[1]["json"]["search_depth"] == "basic"
    assert rank_candidate(results[0].url, "a.cn") == 100
    assert rank_search_result("https://company.cn/jobs", "", 0) > rank_search_result(
        "https://tenant.zhiye.com/", "", 99
    )
    assert rank_search_result("https://tenant.zhiye.com/", "", 0) > rank_search_result(
        "https://www.nowcoder.com/feed/", "", 99
    )
    assert rank_candidate("https://www.wondercv.com/xiaozhao/a", "wondercv.com") == 10
    assert rank_candidate("https://career.university.edu.cn/jobs", "") == 10
    assert discovery_only_kind("https://career.university.edu.cn/jobs")
    assert "问卷平台" in discovery_only_kind("https://qywx.wjx.cn/vm/abc")


def test_query_budget_is_capped_at_three_and_domain_query_is_optional():
    assert len(queries_within_budget("甲集团", "a.cn")) == 2
    assert len(queries_within_budget("甲集团", "", max_queries=3)) == 3
    with pytest.raises(ValueError):
        queries_within_budget("甲集团", "a.cn", max_queries=4)


def test_tavily_client_requires_key_without_printing_it(monkeypatch):
    monkeypatch.setattr("discovery.search_provider.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        TavilySearchProvider(api_key="")
