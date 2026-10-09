"""Small offline checks for the new bounded discovery layer."""

import sqlite3

from adapters.base import AccessRestricted, CampaignLead, DiscoveryOutcome, public_get
from adapters.beisen import BeisenAdapter
from adapters.generic import _cohort_evidence
from collectors.generic import Announcement
from config import Settings
from discovery.batch_runner import run_batch
from discovery.platform_detector import detect_platform
from discovery.seed_registry import Seed, STATUSES, load_seeds
from discovery.structured_records import beisen_draft, save_draft
from processing.organization_registry import verify_child_seed


def _seed(name: str, url: str) -> Seed:
    return Seed(name, "央企", "国务院国资委", url, "example.cn", "custom", url, None)


def test_20_independent_seeds_and_platform_detection():
    seeds = load_seeds()
    assert len(seeds) == 20
    assert len({seed.career_url for seed in seeds}) == 20
    assert detect_platform("https://a.zhiye.com/campus/jobs") == "beisen"
    assert detect_platform("https://campus.51job.com/cofco/") == "51job_campus"
    assert detect_platform("https://job.example.cn/", official_domain="example.cn") == "custom"
    assert _cohort_evidence("中国华电2027年度校园招聘公告")
    assert _cohort_evidence("2027年度高校毕业生统招公告")
    assert not _cohort_evidence("2026年社会招聘公告")
    assert "access_control" in STATUSES


def test_access_control_is_recorded_and_next_seed_continues(tmp_path, monkeypatch):
    first = _seed("国家电网有限公司", "https://a.example.cn/campus")
    second = _seed("测试集团", "https://b.example.cn/campus")

    def discover(self, seed):
        if seed == first:
            raise AccessRestricted(seed.career_url, 412)
        return DiscoveryOutcome(seed, "custom", True, [], "未发现明确2027届校招活动")

    monkeypatch.setattr("discovery.batch_runner.GenericAdapter.discover", discover)
    settings = Settings("unused", "https://unused.example", "unused", tmp_path / "local.sqlite3", tmp_path / "attachments", tmp_path / "output" / "trial.xlsx")
    report, output = run_batch(settings, [first, second], sleep_seconds=0)
    assert output.exists()
    assert [item.status for item in report.results] == ["access_control", "pending_manual_review"]
    assert report.results[0].http_status == 412
    assert report.results[0].failed_url == first.career_url
    with sqlite3.connect(settings.database_path) as connection:
        rows = connection.execute("SELECT career_url,http_status,checked_at FROM career_seed_checks ORDER BY career_url").fetchall()
        assert len(rows) == 2
        assert rows[0][1] == 412
        assert rows[0][2]


def test_beisen_public_jobs_become_evidence_backed_draft():
    seed = _seed("测试集团", "https://demo.zhiye.com/campus/jobs")
    lead = CampaignLead(
        seed.career_url, "2027校园招聘", seed.career_url, "2027应届毕业生",
        structured_jobs=[{
            "JobAdName": "电气工程师", "Require": "2027届本科及以上应届毕业生，电气工程专业",
            "LocNames": ["北京"],
        }],
        listing_url="https://demo.zhiye.com/api/Jobad/GetJobAdPageList",
    )
    record, evidence = beisen_draft(seed, lead)
    assert record.education == "本科及以上"
    assert record.positions == "电气工程师"
    assert record.location == "北京"
    assert record.unit_type is None
    assert record.application_url is None
    assert evidence["education"] == [lead.listing_url]
    with sqlite3.connect(":memory:") as connection:
        save_draft(connection, lead, record, evidence)
        assert connection.execute("SELECT job_count FROM candidate_structured_records").fetchone()[0] == 1


def test_child_identity_requires_exact_official_relation(monkeypatch):
    source = "https://child.example.cn/campus/2027.html"
    seed = Seed("子公司甲有限公司", "央企子公司", "母集团有限公司", source, "example.cn", "custom", source, None)
    monkeypatch.setattr("processing.organization_registry.central_enterprise_names", lambda: frozenset({"母集团有限公司"}))
    monkeypatch.setattr(
        "processing.organization_registry.fetch_announcement",
        lambda url: Announcement(url, url, "子公司甲有限公司是母集团有限公司旗下全资子公司。", [], []),
    )
    match = verify_child_seed(seed)
    assert match is not None
    assert match.unit_type == "央企子公司"
    assert match.parent_evidence == (source,)
    monkeypatch.setattr(
        "processing.organization_registry.fetch_announcement",
        lambda url: Announcement(url, url, "子公司甲有限公司招聘。网站页脚：母集团有限公司", [], []),
    )
    assert verify_child_seed(seed) is None


def test_public_listing_with_login_modal_is_not_a_challenge():
    class Response:
        status_code = 200
        url = "https://example.cn/announcements"
        headers = {"Content-Type": "text/html"}
        encoding = "utf-8"
        text = "<title>招聘公告</title><main>2027校园招聘岗位</main><div>登录 验证码 captcha</div>"

        def raise_for_status(self):
            return None

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    assert public_get(Session(), Response.url).status_code == 200


def test_beisen_redirect_to_another_tenant_is_not_followed(monkeypatch):
    seed = _seed("测试集团", "https://company.zhiye.com/campus/jobs")

    class Response:
        url = "https://other.zhiye.com/campus/jobs"
        text = ""

    monkeypatch.setattr("adapters.beisen.public_get", lambda session, url: Response())
    outcome = BeisenAdapter().discover(seed)
    assert outcome.leads == []
    assert "跳转" in outcome.reason
