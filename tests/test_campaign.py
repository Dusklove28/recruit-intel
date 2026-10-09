from collectors.campaign import campaign_prefix, explore_campaign, within_campaign
from collectors.generic import Announcement
from parsers.html_parser import HTMLLink


def test_campaign_scope_stays_in_one_topic(monkeypatch):
    import collectors.campaign as campaign

    visited = []

    def fake_fetch(url, session):
        visited.append(url)
        if url.endswith("brochure.html"):
            links = [
                HTMLLink("campus.html", "招聘岗位"),
                HTMLLink("zhiyin.html", "投递指引"),
                HTMLLink("about2.html", "2026届校园招聘"),
                HTMLLink("/other-company/brochure.html", "其他企业招聘简章"),
            ]
            html = "<p>2027届招聘简章</p>"
        elif url.endswith("zhiyin.html"):
            links = []
            html = '<script>window.open("https://xyz.51job.com/apply?CtmID=123")</script>'
        else:
            links = []
            html = "<p>岗位列表</p>"
        text = "2027届招聘简章" if url.endswith("brochure.html") else (
            "投递指引" if url.endswith("zhiyin.html") else "招聘岗位"
        )
        return Announcement(url, url, text, links, [], html)

    monkeypatch.setattr(campaign, "fetch_announcement", fake_fetch)
    bundle = explore_campaign("https://campus.51job.com/cofco/brochure.html", object())

    assert len(bundle.pages) == 3
    assert not any("other-company" in url for url in visited)
    assert not any("about2.html" in url for url in visited)
    assert bundle.application_candidates[0].url == "https://xyz.51job.com/apply?CtmID=123"
    host, prefix = campaign_prefix("https://campus.51job.com/cofco/brochure.html")
    assert within_campaign("https://campus.51job.com/cofco/campus.html", host, prefix)
    assert not within_campaign("https://campus.51job.com/other/campus.html", host, prefix)
