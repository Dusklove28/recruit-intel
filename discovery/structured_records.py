"""Evidence-preserving 17-field draft from public ATS job arrays."""

from datetime import datetime, timedelta, timezone
import json
import re
import sqlite3

from adapters.base import CampaignLead
from discovery.seed_registry import Seed
from extractor.schema import RecruitmentRecord


CHINA_TIME = timezone(timedelta(hours=8))
DEGREES = re.compile(r"(?:博士研究生|硕士研究生|本科|大专|专科)(?:及以上|以上)?")


def _unique(values: list[str], maximum: int) -> str | None:
    items = list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
    if not items:
        return None
    result = "、".join(items)
    return result[:maximum] if len(result) > maximum else result


def beisen_draft(seed: Seed, lead: CampaignLead) -> tuple[RecruitmentRecord, dict[str, list[str]]]:
    jobs = lead.structured_jobs
    source = lead.listing_url or lead.evidence_url
    degrees = []
    locations = []
    for row in jobs:
        requirement = str(row.get("Require") or "")
        degrees.extend(DEGREES.findall(requirement))
        degree = row.get("Degree")
        if isinstance(degree, str) and degree not in {"None", "null"}:
            degrees.extend(DEGREES.findall(degree))
        place = row.get("LocNames")
        if isinstance(place, list):
            locations.extend(str(item) for item in place)
        elif isinstance(place, str) and place not in {"None", "null"}:
            locations.append(place)
    position_names = [str(row.get("JobAdName") or "") for row in jobs]
    positions = _unique(position_names, 400)
    education = "；".join(dict.fromkeys(degrees)) or None
    location = _unique(locations, 180)
    today = datetime.now(CHINA_TIME).date()
    record = RecruitmentRecord.model_validate({
        "sequence": 1,
        "unit_name": seed.organization_name,
        # Seed organization metadata is retained separately until official
        # organization verification; a branded ATS page alone is insufficient.
        "unit_type": None,
        "parent_unit": None,
        "batch": "2027届校园招聘",
        "positions": positions,
        "audience": "2027届应届毕业生",
        "education": education,
        "requirements": None,
        "location": location,
        "updated_date": today,
        "deadline": None,
        "status": None,
        "official_url": lead.url,
        "application_url": None,
        "verified_date": today,
        "notes": f"北森公开校招接口返回{len(jobs)}个岗位；活动公告和投递入口待核验",
    })
    evidence = {
        "unit_name": [seed.source],
        "batch": [lead.evidence_url],
        "positions": [source] if positions else [],
        "audience": [lead.evidence_url],
        "education": [source] if education else [],
        "location": [source] if location else [],
        "official_url": [lead.url],
    }
    return record, evidence


def save_draft(
    connection: sqlite3.Connection, lead: CampaignLead,
    record: RecruitmentRecord, evidence: dict[str, list[str]],
) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS candidate_structured_records (
        campaign_url TEXT PRIMARY KEY,
        listing_url TEXT NOT NULL,
        job_count INTEGER NOT NULL,
        record_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        raw_jobs_json TEXT NOT NULL,
        checked_at TEXT NOT NULL
    )""")
    connection.execute("""INSERT INTO candidate_structured_records VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(campaign_url) DO UPDATE SET listing_url=excluded.listing_url,
        job_count=excluded.job_count, record_json=excluded.record_json,
        evidence_json=excluded.evidence_json, raw_jobs_json=excluded.raw_jobs_json,
        checked_at=excluded.checked_at""", (
        lead.url, lead.listing_url or lead.evidence_url, len(lead.structured_jobs),
        record.model_dump_json(), json.dumps(evidence, ensure_ascii=False),
        json.dumps(lead.structured_jobs, ensure_ascii=False),
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ))
    connection.commit()
