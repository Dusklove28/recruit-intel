"""Internal URL provenance for each of the 17 exported fields."""

from collectors.campaign import CampaignBundle
from collectors.public_jobs import StructuredJobs
from extractor.schema import FIELD_NAMES, RecruitmentRecord


def build_field_evidence(
    record: RecruitmentRecord,
    bundle: CampaignBundle,
    jobs: StructuredJobs | None,
) -> dict[str, list[str]]:
    source = bundle.pages[0].final_url
    job_urls = [jobs.campaign_page_url, jobs.listing_url] if jobs else [source]
    detail_urls = [jobs.campaign_page_url, jobs.detail_api_url] if jobs else [source]
    application_source = (
        bundle.application_candidates[0].evidence_url if bundle.application_candidates else source
    )
    roles = {
        "序号": [source],
        "单位名称": [source],
        "单位类型": [],
        "所属集团/主管单位": [source],
        "招聘批次": [source],
        "招聘岗位": [source, *job_urls] if jobs else [source],
        "招聘对象": [source],
        "学历要求": job_urls,
        "专业/硬性要求": detail_urls,
        "工作地点": job_urls,
        "更新时间": [source],
        "截止时间": [source],
        "招聘状态": [source],
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
