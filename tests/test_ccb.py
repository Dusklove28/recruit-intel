"""The approved CCB notice is a public JSON-body plus PDF-attachment case."""

import json
from types import SimpleNamespace

import fitz
import pytest

from collectors.ccb import APPROVED_ANNO_ID, collect_ccb_campaign, create_ccb_session
from collectors.generic import Announcement
from config import Settings
from main import run
from storage.database import connect_database, list_records

from test_extraction import sample_payload


SOURCE_URL = (
    "https://job2.ccb.com/cn/job/announcement.html?"
    f"annoId={APPROVED_ANNO_ID}&planType=XY"
)


class FakeResponse:
    def __init__(self, url, *, payload=None, content=None):
        self.url = url
        self.payload = payload
        self.content = content if content is not None else json.dumps(payload, ensure_ascii=False).encode()

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class FakeSession:
    def __init__(self, pdf_bytes):
        self.pdf_bytes = pdf_bytes
        self.requested = []
        self.cookies = SimpleNamespace(clear=lambda: None)

    def get(self, url, **_kwargs):
        self.requested.append(url)
        if "TXCODE=NHR106" in url:
            return FakeResponse(url, payload={
                "SUCCESS": "true",
                "annoTitle": "中国建设银行总部2027年度校园招聘公告",
                "annoOrgName": "中国建设银行股份有限公司",
                "annoDate": "2026-09-04 14:00",
                "annoContent": "<p>2027届应届毕业生，硕士研究生及以上；计算机相关专业。</p>"
                               "<p>报名截止时间为2026年10月8日24点。</p>",
                "attachList": [{"filePath": "ABCD1234", "file_Name": "岗位需求.pdf"}],
            })
        if "FileDownloadZPServlet" in url:
            return FakeResponse(url, content=self.pdf_bytes)
        raise AssertionError(f"读取了公告范围外的 URL：{url}")


def test_ccb_requires_the_approved_announcement_id():
    with pytest.raises(ValueError, match="仅批准读取指定"):
        collect_ccb_campaign(SOURCE_URL.replace(APPROVED_ANNO_ID, "999"), FakeSession(b""))


def test_ccb_session_uses_only_public_browser_header_and_no_redirects():
    session = create_ccb_session()
    assert session.headers["User-Agent"] == "Mozilla/5.0"
    assert session.max_redirects == 0


def test_ccb_public_api_pdf_llm_and_isolated_export(monkeypatch, tmp_path):
    import collectors.ccb as ccb
    import main

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "PDF POSITION EVIDENCE: Beijing and Shanghai")
    pdf_bytes = document.tobytes()
    document.close()
    session = FakeSession(pdf_bytes)
    shell = Announcement(SOURCE_URL, SOURCE_URL, "{{detail.annoTitle}}", [], [], "<main></main>")
    monkeypatch.setattr(ccb, "fetch_announcement", lambda url, client: shell)
    monkeypatch.setattr(main, "create_ccb_session", lambda: session)

    class FakeQwenClient:
        def __init__(self, _settings):
            pass

        def complete_json(self, _system_prompt, user_prompt):
            assert "硕士研究生及以上" in user_prompt
            assert "PDF POSITION EVIDENCE" in user_prompt
            payload = sample_payload()
            payload.update({
                "单位名称": "中国建设银行股份有限公司",
                "单位类型": "央企",  # The model's unsupported guess must be discarded.
                "所属集团/主管单位": "国务院国资委",
                "学历要求": "硕士研究生及以上",
                "专业/硬性要求": "计算机相关专业",
                "工作地点": "北京、上海",
                "截止时间": "2026-10-08",
                "报名入口": None,
            })
            return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(main, "QwenClient", FakeQwenClient)
    settings = Settings(
        api_key="test-value",
        base_url="https://example.com/v1",
        model="test-model",
        database_path=tmp_path / "acceptance.sqlite3",
        attachments_dir=tmp_path / "attachments",
        output_path=tmp_path / "acceptance.xlsx",
    )
    run(SOURCE_URL, settings)
    with connect_database(settings.database_path) as connection:
        records = list_records(connection)
        raw_text, evidence_json = connection.execute(
            "SELECT raw_text, field_evidence FROM recruitment"
        ).fetchone()
    assert len(records) == 1
    assert records[0].status == "已截止"
    assert records[0].unit_type is None
    assert records[0].parent_unit is None
    assert records[0].education == "硕士研究生及以上"
    assert "PDF POSITION EVIDENCE" in raw_text
    evidence = json.loads(evidence_json)
    assert any("TXCODE=NHR106" in url for url in evidence["学历要求"])
    assert any("FileDownloadZPServlet" in url for url in evidence["招聘岗位"])
    assert not any("FileDownloadZPServlet" in url for url in evidence["学历要求"])
    assert len(session.requested) == 2  # Exact-ID API and its PDF, no other notices.
    assert settings.output_path.exists()
