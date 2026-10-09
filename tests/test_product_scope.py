from datetime import date

from extractor.schema import RecruitmentRecord
from processing.product_scope import is_product_record
from test_extraction import sample_payload


def test_only_open_2027_enterprise_campus_campaigns_are_exported():
    payload = sample_payload()
    payload.update({
        "单位类型": "央企",
        "招聘批次": "2027届校园招聘",
        "招聘对象": "2027届应届毕业生",
        "招聘状态": "招聘中",
        "截止时间": "2026-10-28",
    })
    record = RecruitmentRecord.model_validate(payload)
    today = date(2026, 10, 9)
    assert is_product_record(record, today)
    assert not is_product_record(record.model_copy(update={"unit_type": None}), today)
    assert not is_product_record(record.model_copy(update={"unit_type": "事业单位"}), today)
    assert not is_product_record(record.model_copy(update={"batch": "2026届校园招聘", "audience": None}), today)
    assert not is_product_record(record.model_copy(update={"batch": "2027届社会招聘", "audience": None}), today)
    assert not is_product_record(record.model_copy(update={"status": "已截止"}), today)
    assert not is_product_record(record.model_copy(update={"deadline": date(2026, 10, 8)}), today)
