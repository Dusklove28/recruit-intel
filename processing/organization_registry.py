"""Small, evidence-backed registry of verified organization relationships.

Entries are exact official names checked against the linked authority. This is
deliberately a curated registry, not a guess from a name or a site crawler.
"""

from dataclasses import dataclass
from functools import lru_cache
import json
import re
import sqlite3
from urllib.parse import urlparse

from bs4 import BeautifulSoup
import requests

from collectors.generic import fetch_announcement
from discovery.seed_registry import Seed


SASAC_CENTRAL_ENTERPRISES_URL = (
    "http://wap.sasac.gov.cn/n2588045/n27271785/n27271792/c14159097/content.html"
)
SASAC_CENTRAL_ENTERPRISE_RULE_URL = (
    "http://wap.sasac.gov.cn/n2588035/n2588320/n2588335/c20164244/content.html"
)


@dataclass(frozen=True)
class OrganizationMatch:
    unit_type: str
    parent_unit: str
    type_evidence: tuple[str, ...]
    parent_evidence: tuple[str, ...]


# The official directory lists 中粮集团有限公司 as a group-level central enterprise.
# The linked SASAC rule defines central enterprises as those for which SASAC
# performs the investor's duties on behalf of the State Council.
REGISTRY = {
    "中粮集团有限公司": OrganizationMatch(
        unit_type="央企",
        parent_unit="国务院国资委",
        type_evidence=(SASAC_CENTRAL_ENTERPRISES_URL,),
        parent_evidence=(SASAC_CENTRAL_ENTERPRISES_URL, SASAC_CENTRAL_ENTERPRISE_RULE_URL),
    ),
}


def lookup_organization(official_name: str | None) -> OrganizationMatch | None:
    """Only exact, preverified official names may populate organization fields."""
    return REGISTRY.get(official_name.strip()) if official_name else None


@lru_cache(maxsize=1)
def central_enterprise_names() -> frozenset[str]:
    """Read the official directory once; persist only organizations actually used."""
    response = requests.get(
        SASAC_CENTRAL_ENTERPRISES_URL,
        timeout=(10, 30),
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    names = {
        cell.get_text(" ", strip=True).split("[")[0]
        for cell in soup.find_all("td")
        if not cell.find("td") and re.search(r"(?:有限责任公司|有限公司|总局)$", cell.get_text(" ", strip=True).split("[")[0])
    }
    if len(names) < 50:
        raise ValueError("国务院国资委央企名录解析结果不足，拒绝用不完整名录核验")
    return frozenset(names)


def verify_central_group(official_name: str | None) -> OrganizationMatch | None:
    """Match the exact group name in the official SASAC directory."""
    if not official_name or official_name.strip() not in central_enterprise_names():
        return None
    return OrganizationMatch(
        unit_type="央企",
        parent_unit="国务院国资委",
        type_evidence=(SASAC_CENTRAL_ENTERPRISES_URL,),
        parent_evidence=(SASAC_CENTRAL_ENTERPRISES_URL, SASAC_CENTRAL_ENTERPRISE_RULE_URL),
    )


def verify_child_seed(seed: Seed) -> OrganizationMatch | None:
    """Use an official company page with an explicit exact-name parent relation."""
    if seed.organization_type != "央企子公司" or not seed.parent_group:
        return None
    source_host = (urlparse(seed.source).hostname or "").lower()
    official_domain = seed.official_domain.lower().lstrip(".")
    if source_host != official_domain and not source_host.endswith("." + official_domain):
        return None
    if seed.parent_group not in central_enterprise_names():
        return None
    page = fetch_announcement(seed.source)
    if (urlparse(page.final_url).hostname or "").lower() != source_host:
        return None
    body = re.sub(r"\s+", "", page.text)
    child, parent = re.escape(seed.organization_name), re.escape(seed.parent_group)
    relation = re.search(
        rf"{child}.{{0,160}}?{parent}.{{0,24}}?(?:子企业|子公司|旗下)"
        rf"|{child}.{{0,160}}?(?:母公司为|隶属于){parent}",
        body,
    )
    if not relation:
        return None
    return OrganizationMatch(
        unit_type="央企子公司",
        parent_unit=seed.parent_group,
        type_evidence=(seed.source, SASAC_CENTRAL_ENTERPRISES_URL),
        parent_evidence=(seed.source,),
    )


def save_verified_organization(
    database: sqlite3.Connection, official_name: str, match: OrganizationMatch
) -> None:
    database.execute("""CREATE TABLE IF NOT EXISTS verified_organizations (
        official_name TEXT PRIMARY KEY,
        unit_type TEXT NOT NULL,
        parent_unit TEXT NOT NULL,
        type_evidence TEXT NOT NULL,
        parent_evidence TEXT NOT NULL
    )""")
    database.execute(
        """INSERT OR REPLACE INTO verified_organizations VALUES (?, ?, ?, ?, ?)""",
        (official_name, match.unit_type, match.parent_unit,
         json.dumps(match.type_evidence, ensure_ascii=False),
         json.dumps(match.parent_evidence, ensure_ascii=False)),
    )
    database.commit()
