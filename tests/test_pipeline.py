import json

from config import Settings
from collectors.campaign import ApplicationCandidate, CampaignBundle
from collectors.generic import Announcement, AttachmentLink
from main import run
from parsers.html_parser import HTMLLink
from storage.database import connect_database, list_records

from test_extraction import sample_payload


def test_one_url_to_sqlite_and_xlsx_with_attachment(monkeypatch, tmp_path, capsys):
    import main

    link = AttachmentLink(
        original_url="/files/岗位表.xlsx",
        url="https://example.com/files/岗位表.xlsx",
        filename="岗位表.xlsx",
    )
    announcement = Announcement(
        source_url="https://example.com/notice",
        final_url="https://example.com/notice",
        text="中粮集团有限公司2027届招聘，学历要求详见附件1",
        links=[HTMLLink("/files/岗位表.xlsx", "附件1"), HTMLLink("/apply", "立即报名")],
        attachments=[link],
    )
    bundle = CampaignBundle(
        source_url="https://example.com/notice",
        pages=[announcement],
        attachments=[link],
        application_candidates=[ApplicationCandidate("https://example.com/apply", announcement.final_url, 0)],
        warnings=[],
    )
    monkeypatch.setattr(main, "explore_campaign", lambda url, session: bundle)
    monkeypatch.setattr(main, "collect_structured_jobs", lambda campaign, session: None)
    monkeypatch.setattr(main, "download_attachment", lambda item, folder, session: tmp_path / "岗位表.xlsx")
    monkeypatch.setattr(main, "parse_attachment", lambda path: ("学历要求 | 本科及以上", False))

    class FakeQwenClient:
        def __init__(self, settings):
            pass

        def complete_json(self, system_prompt, user_prompt):
            assert "学历要求 | 本科及以上" in user_prompt
            payload = sample_payload()
            payload["单位名称"] = "中粮集团有限公司"
            return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(main, "QwenClient", FakeQwenClient)
    settings = Settings(
        api_key="test-value",
        base_url="https://example.com/v1",
        model="test-model",
        database_path=tmp_path / "data" / "recruitment.sqlite3",
        attachments_dir=tmp_path / "data" / "attachments",
        output_path=tmp_path / "data" / "output" / "招聘汇总.xlsx",
    )

    run("https://example.com/notice", settings)
    with connect_database(settings.database_path) as connection:
        records = list_records(connection)
        evidence = json.loads(connection.execute("SELECT field_evidence FROM recruitment").fetchone()[0])
    assert len(records) == 1
    assert records[0].education == "本科及以上"
    assert records[0].unit_type == "央企"
    assert records[0].parent_unit == "国务院国资委"
    assert records[0].updated_date == records[0].verified_date
    assert len(evidence) == 17
    assert evidence["单位类型"][0].startswith("https://wap.sasac.gov.cn/")
    assert evidence["报名入口"] == ["https://example.com/notice"]
    assert settings.output_path.exists()
    output = capsys.readouterr().out
    assert "发现附件 1 个" in output
    assert "Pydantic校验通过" in output
    assert "Excel导出成功" in output
