from datetime import date

import pytest
from pydantic import ValidationError

from extractor.llm_extractor import extract_record
from extractor.schema import RecruitmentRecord


def sample_payload():
    return {
        "序号": 1,
        "单位名称": "某国有企业",
        "单位类型": "地方国企",
        "所属集团/主管单位": None,
        "招聘批次": "2027届校园招聘",
        "招聘岗位": "技术岗、管理岗",
        "招聘对象": "2027届应届毕业生",
        "学历要求": "本科及以上",
        "专业/硬性要求": "计算机、机械等相关专业",
        "工作地点": None,
        "更新时间": None,
        "截止时间": "2026-10-20",
        "招聘状态": None,
        "官方公告": None,
        "报名入口": "https://example.com/apply",
        "最后核验日期": None,
        "备注": None,
    }


def test_attachment_evidence_is_passed_to_llm_and_validated():
    class FakeClient:
        def complete_json(self, system_prompt, user_prompt):
            assert "网页正文：学历要求详见附件1" in user_prompt
            assert "附件1：岗位表.xlsx" in user_prompt
            assert "本科及以上" in user_prompt
            import json

            return json.dumps(sample_payload(), ensure_ascii=False)

    material = "网页正文：学历要求详见附件1\n附件1：岗位表.xlsx\n学历要求 | 本科及以上"
    record = extract_record(
        FakeClient(),
        material,
        "https://example.com/notice",
        [("报名", "https://example.com/apply")],
        date(2026, 10, 9),
    )
    assert record.education == "本科及以上"
    assert record.status == "招聘中"
    assert record.official_url == "https://example.com/notice"
    assert record.verified_date == date(2026, 10, 9)


def test_schema_rejects_missing_or_extra_fields():
    payload = sample_payload()
    payload.pop("学历要求")
    payload["额外字段"] = "错误"
    with pytest.raises(ValidationError):
        RecruitmentRecord.model_validate(payload)


def test_finalize_requires_all_17_llm_keys_even_for_deterministic_fields():
    from processing.validate import finalize_record

    payload = sample_payload()
    payload.pop("官方公告")
    with pytest.raises(ValueError, match="17列定义"):
        finalize_record(payload, "https://example.com/notice", "正文", [], date(2026, 10, 9))


def test_unsubstantiated_application_url_is_removed():
    from processing.validate import finalize_record

    payload = sample_payload()
    record = finalize_record(payload, "https://example.com/notice", "公告正文", [], date(2026, 10, 9))
    assert record.application_url is None
    assert "已留空" in record.notes


def test_unit_type_without_metadata_is_left_empty_and_job_page_is_not_signup():
    from processing.validate import finalize_record

    payload = sample_payload()
    payload["报名入口"] = "https://example.com/campus.html"
    payload["所属集团/主管单位"] = "模型猜测的集团"
    payload["更新时间"] = "2026-09-01"
    record = finalize_record(
        payload,
        "https://example.com/brochure.html",
        "招聘岗位详见岗位页",
        [("招聘岗位", "https://example.com/campus.html")],
        date(2026, 10, 9),
    )
    assert record.unit_type is None
    assert record.parent_unit is None
    assert record.updated_date is None
    assert record.application_url is None


def test_overlong_requirements_trigger_one_retry():
    import json

    class FakeClient:
        calls = 0

        def complete_json(self, system_prompt, user_prompt):
            self.calls += 1
            payload = sample_payload()
            payload["专业/硬性要求"] = "机械、电气相关专业" * 30 if self.calls == 1 else "机械、电气等相关专业，依岗位而异"
            return json.dumps(payload, ensure_ascii=False)

    client = FakeClient()
    record = extract_record(
        client, "机械、电气相关专业", "https://example.com/notice",
        [("报名入口", "https://example.com/apply")], date(2026, 10, 9),
    )
    assert client.calls == 2
    assert record.requirements == "机械、电气等相关专业，依岗位而异"


def test_unsupported_population_claim_is_rejected():
    payload = sample_payload()
    payload["专业/硬性要求"] = "多数岗位专业不限"
    with pytest.raises(ValidationError):
        RecruitmentRecord.model_validate(payload)


def test_requirements_reject_training_as_qualification_and_keep_major_condition():
    from processing.validate import finalize_record

    payload = sample_payload()
    payload["专业/硬性要求"] = "英语六级或专八；部分岗位涉及跟岗锻炼"
    source = "英语专业毕业生须通过国家英语专业八级考试（不低于60分）。"
    with pytest.raises(ValidationError):
        finalize_record(payload, "https://example.com/notice", source, [], date(2026, 10, 9))

    payload["专业/硬性要求"] = "英语六级≥425；英语专业毕业生另须专八≥60"
    record = finalize_record(payload, "https://example.com/notice", source, [], date(2026, 10, 9))
    assert "英语专业" in record.requirements
