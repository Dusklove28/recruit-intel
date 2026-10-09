"""Internal URL provenance for each of the 17 exported fields."""

from collectors.campaign import CampaignBundle
from collectors.public_jobs import StructuredJobs
from extractor.schema import FIELD_NAMES, RecruitmentRecord
from processing.organization_registry import OrganizationMatch


def build_field_evidence(
    record: RecruitmentRecord,
    bundle: CampaignBundle,
    jobs: StructuredJobs | None,
    organization: OrganizationMatch | None = None,
) -> dict[str, list[str]]:
    source = bundle.pages[0].final_url
    content_sources = [source, *bundle.content_evidence_urls]
    attachment_sources = [item.url for item in bundle.attachments]
    attachment_fields = (
        {"招聘岗位", "招聘对象", "学历要求", "专业/硬性要求", "工作地点"}
        if bundle.attachment_evidence_fields is None
        else set(bundle.attachment_evidence_fields)
    )

    def material_sources(field: str) -> list[str]:
        return content_sources + (attachment_sources if field in attachment_fields else [])

    job_urls = [jobs.campaign_page_url, jobs.listing_url] if jobs else [source]
    detail_urls = [jobs.campaign_page_url, jobs.detail_api_url] if jobs else [source]
    application_source = (
        bundle.application_candidates[0].evidence_url if bundle.application_candidates else source
    )
    roles = {
        "序号": [source],
        "单位名称": content_sources,
        "单位类型": list(organization.type_evidence) if organization else [],
        "所属集团/主管单位": list(organization.parent_evidence) if organization else [],
        "招聘批次": content_sources,
        "招聘岗位": [*material_sources("招聘岗位"), *job_urls],
        "招聘对象": material_sources("招聘对象"),
        "学历要求": [*material_sources("学历要求"), *job_urls],
        "专业/硬性要求": [*material_sources("专业/硬性要求"), *detail_urls],
        "工作地点": [*material_sources("工作地点"), *job_urls],
        "更新时间": [],  # Internally managed content date, not an announcement date.
        "截止时间": content_sources,
        "招聘状态": content_sources,
        "官方公告": [source],
        "报名入口": [application_source],
        "最后核验日期": [source],
        "备注": [source],
    }
    values = record.model_dump(by_alias=True)
    return {
        field: list(dict.fromkeys(roles[field])) if values[field] is not None else []
        for field in FIELD_NAMES
    }
