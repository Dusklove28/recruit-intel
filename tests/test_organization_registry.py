from collectors.campaign import CampaignBundle
from collectors.generic import Announcement
from extractor.schema import RecruitmentRecord
from processing.evidence import build_field_evidence
from processing.organization_registry import (
    SASAC_CENTRAL_ENTERPRISES_URL,
    SASAC_CENTRAL_ENTERPRISE_RULE_URL,
    lookup_organization,
)

from test_extraction import sample_payload


def test_only_verified_official_name_matches():
    match = lookup_organization("中粮集团有限公司")
    assert match is not None
    assert match.unit_type == "央企"
    assert match.parent_unit == "国务院国资委"
    assert lookup_organization("中粮集团") is None
    assert lookup_organization("某国有企业") is None


def test_organization_fields_keep_official_evidence_urls():
    match = lookup_organization("中粮集团有限公司")
    payload = sample_payload()
    payload["单位名称"] = "中粮集团有限公司"
    payload["单位类型"] = match.unit_type
    payload["所属集团/主管单位"] = match.parent_unit
    record = RecruitmentRecord.model_validate(payload)
    page = Announcement(
        source_url="https://example.com/cofco/brochure.html",
        final_url="https://example.com/cofco/brochure.html",
        text="中粮集团有限公司2027届招聘",
        links=[],
        attachments=[],
    )
    bundle = CampaignBundle(page.source_url, [page], [], [], [])
    evidence = build_field_evidence(record, bundle, None, match)
    assert evidence["单位类型"] == [SASAC_CENTRAL_ENTERPRISES_URL]
    assert evidence["所属集团/主管单位"] == [
        SASAC_CENTRAL_ENTERPRISES_URL, SASAC_CENTRAL_ENTERPRISE_RULE_URL,
    ]
    assert evidence["更新时间"] == []
