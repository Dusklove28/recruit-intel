"""Small, evidence-backed registry of verified organization relationships.

Entries are exact official names checked against the linked authority. This is
deliberately a curated registry, not a guess from a name or a site crawler.
"""

from dataclasses import dataclass


SASAC_CENTRAL_ENTERPRISES_URL = (
    "https://wap.sasac.gov.cn/n2588045/n27271785/n27271792/c14159097/content.html"
)
SASAC_CENTRAL_ENTERPRISE_RULE_URL = (
    "https://wap.sasac.gov.cn/n2588035/n2588320/n2588335/c20164244/content.html"
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
