"""Read structured jobs exposed by a 51job campaign's own public XHR.

Only job IDs from the campaign-specific position list are queried. The
client-side signing value is read from the campaign's public script at runtime;
it is never logged, saved, or checked into the repository.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import requests

from collectors.campaign import CampaignBundle, campaign_prefix, within_campaign


MAX_JOBS = 1000
PAGE_SIZE = 200
DETAIL_WORKERS = 4
DEGREE_ORDER = ["中技/中专", "大专", "本科", "硕士", "博士"]


@dataclass(frozen=True)
class JobDetail:
    job_id: str
    title: str
    education: str | None
    location: str | None
    professional_requirement: str | None
    qualification: str | None
    full_text: str


@dataclass(frozen=True)
class StructuredJobs:
    campaign_page_url: str
    listing_url: str
    detail_api_url: str
    total_jobs: int
    jobs: list[dict]
    details: list[JobDetail]
    warnings: list[str]

    @property
    def education_summary(self) -> str | None:
        degrees = {str(job.get("degree") or "").strip() for job in self.jobs}
        degrees.discard("")
        if not degrees:
            return None
        ordered = [name for name in DEGREE_ORDER if name in degrees]
        ordered.extend(sorted(degrees - set(ordered)))
        return "、".join(ordered) + "（各岗位要求不同）"

    @property
    def location_summary(self) -> str | None:
        counts = Counter(str(job.get("address") or "").strip() for job in self.jobs)
        counts.pop("", None)
        if not counts:
            return None
        names = [name for name, _count in counts.most_common(8)]
        if len(counts) <= 8:
            return "、".join(names)
        return "、".join(names) + f"等（共{len(counts)}个工作地点）"

    def prompt_summary(self) -> str:
        majors = Counter(detail.professional_requirement for detail in self.details if detail.professional_requirement)
        qualifications = Counter(detail.qualification for detail in self.details if detail.qualification)
        major_lines = [f"{phrase}（{count}岗）" for phrase, count in majors.most_common(180)]
        qualification_lines = [f"{phrase}（{count}岗）" for phrase, count in qualifications.most_common(60)]
        degree_counts = Counter(job.get("degree") for job in self.jobs)
        degree_text = "、".join(f"{key}:{value}岗" for key, value in degree_counts.items() if key)
        return (
            f"公开岗位列表：{self.total_jobs}岗；全部明细成功读取：{len(self.details)}岗。\n"
            f"岗位级学历统计：{degree_text}\n"
            f"学历汇总：{self.education_summary or '未知'}\n"
            f"地点汇总：{self.location_summary or '未知'}\n"
            "岗位详情中的专业要求（按出现频次列出）：\n"
            + ("\n".join(major_lines) or "未检出明确专业要求")
            + "\n岗位详情中的任职资格（按出现频次列出）：\n"
            + ("\n".join(qualification_lines) or "未检出明确任职资格")
            + f"\n如有未列出的不同要求，仍以岗位详情为准。专业要求提取覆盖 {len(majors)} 种表述。"
        )

    def raw_job_text(self) -> str:
        return "\n".join(
            f"岗位ID:{detail.job_id} | {detail.title} | 学历:{detail.education or '未知'} | "
            f"地点:{detail.location or '未知'} | 专业:{detail.professional_requirement or '未写明'} | "
            f"资格:{detail.qualification or '未写明'} | 详情:{detail.full_text}"
            for detail in self.details
        )


def _public_script_urls(bundle: CampaignBundle) -> tuple[str, str, str] | None:
    for page in bundle.pages:
        if "index/position_list" not in page.html or "coapi.getJobDetail" not in page.html:
            continue
        soup = BeautifulSoup(page.html, "lxml")
        sources = [urljoin(page.final_url, tag["src"]) for tag in soup.select("script[src]")]
        host, prefix = campaign_prefix(page.final_url)
        local_url = next(
            (
                url for url in sources
                if urlparse(url).path.endswith("/js/url.js") and within_campaign(url, host, prefix)
            ),
            None,
        )
        detail_script = next(
            (
                url for url in sources
                if urlparse(url).hostname == "js.51jobcdn.com"
                and urlparse(url).path.endswith("/coapi.min.js")
            ),
            None,
        )
        if local_url and detail_script:
            return page.final_url, local_url, detail_script
    return None


def _list_jobs(client: requests.Session, listing_url: str) -> tuple[int, list[dict]]:
    results: list[dict] = []
    total = None
    page_number = 1
    while total is None or len(results) < total:
        response = client.post(
            listing_url,
            data={
                "pageIndex": page_number,
                "pageSize": PAGE_SIZE,
                "orgId": "",
                "degree": "",
                "workArea": "",
                "keyword": "",
            },
            timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json().get("data", {})
        total = int(payload.get("total", 0))
        if total > MAX_JOBS:
            raise ValueError(f"专题公开岗位数 {total} 超过 V1 上限 {MAX_JOBS}，未做部分抽取")
        batch = payload.get("list", [])
        if not batch and len(results) < total:
            raise ValueError("岗位接口提前返回空页，未做部分抽取")
        results.extend(batch)
        page_number += 1
    unique = {str(job.get("jobId")): job for job in results if job.get("jobId")}
    if len(unique) != total:
        raise ValueError(f"岗位列表去重后为 {len(unique)} 条，接口宣称 {total} 条，未做部分抽取")
    return total, list(unique.values())


def _read_public_detail_script(client: requests.Session, script_url: str) -> tuple[str, str]:
    response = client.get(script_url, timeout=(10, 20))
    response.raise_for_status()
    script = response.text
    if 'md5("coapi"+sParams+this.key.substr(keyindex,15))' not in script:
        raise ValueError("岗位详情公开脚本的请求格式已变化")
    client_value = re.search(r'key:"([^"]+)"', script)
    endpoint = re.search(r'getJobDetail:function.*?(https://coapi\.51job\.com/job_detail\.php)', script)
    if not client_value or not endpoint:
        raise ValueError("无法从招聘专题公开脚本确认岗位详情接口")
    return client_value.group(1), endpoint.group(1)


def _extract_section(text: str, heading: str, following: str) -> str | None:
    match = re.search(
        rf"(?:{heading})\s*[:：]?\s*(.*?)(?={following}|$)", text, flags=re.I | re.S
    )
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" ：:;；")
    return value[:300] if value else None


def _fetch_detail(job: dict, endpoint: str, client_value: str) -> JobDetail:
    job_id = str(job["jobId"])
    params_json = json.dumps({"jobid": job_id}, separators=(",", ":"))
    key_index = 1
    signature = hashlib.md5(
        ("coapi" + params_json + client_value[key_index : key_index + 15]).encode("utf-8")
    ).hexdigest()
    response = requests.get(
        endpoint,
        params={"jsoncallback": "cb", "key": key_index, "sign": signature, "params": params_json},
        timeout=(10, 20),
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    body = response.text
    payload = json.loads(body[3:-1] if body.startswith("cb(") and body.endswith(")") else body)
    if str(payload.get("status")) != "1":
        raise ValueError("公开岗位详情接口未返回有效数据")
    detail = payload.get("resultbody") or {}
    if str(detail.get("jobid")) != job_id:
        raise ValueError("岗位详情 ID 与列表不一致")
    full_text = BeautifulSoup(detail.get("jobinfo") or "", "lxml").get_text(" ", strip=True)
    raw_major = detail.get("major")
    major = raw_major.strip() if isinstance(raw_major, str) and raw_major.strip() else _extract_section(
        full_text,
        "专业要求",
        r"岗位职责|工作职责|任职资格|任职要求|学历要求",
    )
    qualification = _extract_section(
        full_text,
        "任职资格|任职要求",
        r"岗位职责|工作职责|专业要求|招聘人数",
    )
    return JobDetail(
        job_id=job_id,
        title=str(detail.get("jobname") or job.get("jobName") or ""),
        education=detail.get("degreefrom") or job.get("degree"),
        location=detail.get("address") or job.get("address"),
        professional_requirement=major,
        qualification=qualification,
        full_text=full_text,
    )


def collect_structured_jobs(
    bundle: CampaignBundle, session: requests.Session | None = None
) -> StructuredJobs | None:
    discovered = _public_script_urls(bundle)
    if discovered is None:
        return None
    campaign_page_url, local_script_url, detail_script_url = discovered
    client = session or requests.Session()
    local_response = client.get(local_script_url, timeout=(10, 20))
    local_response.raise_for_status()
    local_response.encoding = "utf-8"
    api_match = re.search(r"^\s*(?:let|var|const)\s+url\s*=\s*['\"](https?://[^'\"]+)['\"]", local_response.text, re.M)
    if not api_match:
        raise ValueError("招聘专题未提供可确认的岗位列表接口地址")
    api_base = api_match.group(1)
    parsed_base = urlparse(api_base)
    if parsed_base.scheme != "https" or parsed_base.hostname != "be.51job.com":
        raise ValueError("招聘专题岗位接口不在预期的官方 API 域名")
    listing_url = urljoin(api_base, "index/position_list")
    total, jobs = _list_jobs(client, listing_url)
    client_value, detail_endpoint = _read_public_detail_script(client, detail_script_url)
    details: list[JobDetail] = []
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
        futures = {pool.submit(_fetch_detail, job, detail_endpoint, client_value): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                details.append(future.result())
            except Exception as error:
                warnings.append(f"岗位 {job.get('jobId')} 详情读取失败（{type(error).__name__}）")
    details.sort(key=lambda item: item.job_id)
    if len(details) < total * 0.9:
        raise ValueError(f"岗位详情仅成功读取 {len(details)}/{total}，不足以可靠汇总")
    if warnings:
        warnings.append(f"共有 {len(warnings)} 个岗位详情未能读取，专业汇总可能不完整")
    return StructuredJobs(campaign_page_url, listing_url, detail_endpoint, total, jobs, details, warnings)
