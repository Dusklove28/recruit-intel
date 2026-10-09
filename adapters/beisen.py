"""Public Beisen campus API adapter; no browser automation or credentials."""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from adapters.base import AccessRestricted, CampaignLead, DiscoveryOutcome, HEADERS, public_get
from adapters.generic import _cohort_evidence
from discovery.seed_registry import Seed


JOB_COHORT = re.compile(r"2027\s*(?:届|年|年度)?[^。；\n]{0,25}(?:应届|毕业生)|(?:应届|毕业生)[^。；\n]{0,25}2027")


class BeisenAdapter:
    PAGE_SIZE = 100
    MAX_PAGES = 3

    def discover(self, seed: Seed, session: requests.Session | None = None) -> DiscoveryOutcome:
        client = session or requests.Session()
        response = public_get(client, seed.career_url)
        host = urlparse(response.url).hostname or ""
        if host != (urlparse(seed.career_url).hostname or "").lower() or not host.endswith(".zhiye.com"):
            return DiscoveryOutcome(seed, "beisen", True, [], "北森入口已跳转，需人工核验")
        # 北森公开门户的 campus 栏目是 Category 2；仅保留所访问的租户。
        category = re.search(r"/(\d+)/jobs/?$", urlparse(response.url).path)
        category_id = category.group(1) if category else "2"
        api_url = f"https://{host}/api/Jobad/GetJobAdPageList"
        rows: list[dict] = []
        seen: set[str] = set()
        for page in range(self.MAX_PAGES):
            body = {
                "PageIndex": page, "PageSize": self.PAGE_SIZE, "Category": [category_id],
                "KeyWords": "", "SpecialType": 0, "PortalId": "",
                "DisplayFields": ["Category", "Kind", "LocId", "PostDate"],
            }
            reply = client.post(api_url, json=body, headers={**HEADERS, "Referer": response.url}, timeout=(8, 20))
            if reply.status_code in {401, 403, 412, 429}:
                raise AccessRestricted(api_url, reply.status_code, "北森公开接口访问受限")
            reply.raise_for_status()
            try:
                payload = reply.json()
            except ValueError:
                return DiscoveryOutcome(seed, "beisen", True, [], "北森公开接口没有返回 JSON")
            batch = payload.get("Data") if isinstance(payload, dict) else None
            if not isinstance(batch, list):
                return DiscoveryOutcome(seed, "beisen", True, [], "北森公开接口未返回岗位数组")
            for row in batch:
                if not isinstance(row, dict):
                    continue
                job_id = str(row.get("Id") or "")
                if job_id and job_id not in seen:
                    seen.add(job_id)
                    rows.append(row)
            if len(batch) < self.PAGE_SIZE:
                break
        if not rows:
            return DiscoveryOutcome(seed, "beisen", True, [], "校招栏目无公开岗位")
        page_evidence = _cohort_evidence(response.text)
        job_rows = [
            row for row in rows
            if JOB_COHORT.search(" ".join(str(row.get(k) or "") for k in ("JobAdName", "Kind", "Require")))
            or _cohort_evidence(str(row.get("JobAdName") or ""))
        ]
        if not page_evidence and not job_rows:
            return DiscoveryOutcome(seed, "beisen", True, [], f"发现{len(rows)}个校招岗位，但未发现2027届岗位")
        # A campaign banner is not proof that every historic job belongs to it.
        selected = job_rows
        if not selected:
            return DiscoveryOutcome(seed, "beisen", True, [], "2027活动页面下岗位未标明届别")
        today = datetime.now(timezone(timedelta(hours=8))).date()
        active = []
        for row in selected:
            end = str(row.get("EndTime") or "")[:10]
            if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", end) and datetime.fromisoformat(end).date() < today:
                continue
            active.append(row)
        if not active:
            return DiscoveryOutcome(seed, "beisen", True, [], "2027届岗位均已截止")
        selected = active
        evidence = page_evidence or str(selected[0].get("Require") or "")[:120]
        lead = CampaignLead(
            url=response.url,
            title=f"{seed.organization_name}2027届校园招聘",
            evidence_url=response.url if page_evidence else api_url,
            cohort_evidence=evidence,
            structured_jobs=selected,
            listing_url=api_url,
        )
        return DiscoveryOutcome(seed, "beisen", True, [lead])
