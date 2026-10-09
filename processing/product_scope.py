"""Keep the customer workbook within the approved 2027 campus hiring scope."""

from datetime import date
import re

from extractor.schema import RecruitmentRecord


ENTERPRISE_TYPES = frozenset({"央企", "央企子公司", "地方国企"})
CAMPUS_TERMS = re.compile(r"校园招聘|校招|应届毕业生|应届生")


def is_product_record(record: RecruitmentRecord, on_date: date) -> bool:
    """Only verified enterprise campus campaigns still open for applications."""
    if record.unit_type not in ENTERPRISE_TYPES:
        return False
    campaign_text = " ".join(part for part in (record.batch, record.audience) if part)
    if "2027" not in campaign_text or not CAMPUS_TERMS.search(campaign_text):
        return False
    if record.status not in {"招聘中", "即将截止"}:
        return False
    if record.deadline is not None and record.deadline < on_date:
        return False
    return True
