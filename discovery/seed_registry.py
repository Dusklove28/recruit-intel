"""Small, independently verified employer career-source registry."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlparse


PLATFORMS = frozenset({"moka", "beisen", "feishu", "51job_campus", "iguopin", "custom", "unknown"})
TYPES = frozenset({"央企", "央企子公司", "地方国企"})
SEED_FILE = Path(__file__).with_name("seeds.json")


@dataclass(frozen=True)
class Seed:
    organization_name: str
    organization_type: str | None
    parent_group: str | None
    career_url: str
    official_domain: str
    platform: str
    source: str
    verified_at: date | None
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: dict) -> "Seed":
        seed = cls(**{**value, "verified_at": date.fromisoformat(value["verified_at"]) if value.get("verified_at") else None})
        if seed.platform not in PLATFORMS or seed.organization_type not in TYPES | {None}:
            raise ValueError(f"无效 Seed 分类：{seed.organization_name}")
        for url in (seed.career_url, seed.source):
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError(f"无效 Seed 证据链接：{seed.organization_name}")
        if not seed.organization_name or not seed.official_domain:
            raise ValueError("Seed 缺少单位名称或官方域名")
        return seed


def load_seeds(path: Path = SEED_FILE) -> list[Seed]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    seeds = [Seed.from_dict(item) for item in raw]
    if len({seed.career_url for seed in seeds}) != len(seeds):
        raise ValueError("Seed Registry 存在重复招聘入口")
    return seeds


def sync_seeds(connection: sqlite3.Connection, seeds: list[Seed]) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS career_seeds (
        career_url TEXT PRIMARY KEY,
        organization_name TEXT NOT NULL,
        organization_type TEXT,
        parent_group TEXT,
        official_domain TEXT NOT NULL,
        platform TEXT NOT NULL,
        source TEXT NOT NULL,
        verified_at TEXT,
        enabled INTEGER NOT NULL
    )""")
    connection.executemany("""INSERT INTO career_seeds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(career_url) DO UPDATE SET
        organization_name=excluded.organization_name,
        organization_type=excluded.organization_type,
        parent_group=excluded.parent_group,
        official_domain=excluded.official_domain,
        platform=excluded.platform,
        source=excluded.source,
        verified_at=COALESCE(excluded.verified_at, career_seeds.verified_at),
        enabled=excluded.enabled""", [
        (s.career_url, s.organization_name, s.organization_type, s.parent_group,
         s.official_domain, s.platform, s.source, s.verified_at.isoformat() if s.verified_at else None,
         int(s.enabled)) for s in seeds
    ])
    connection.commit()


STATUSES = frozenset({
    "success", "no_2027_recruitment", "expired", "pending_manual_review",
    "access_control", "unsupported_platform", "parse_failed",
})


def save_seed_check(
    connection: sqlite3.Connection, seed: Seed, status: str, *,
    platform: str | None = None, reason: str = "", failed_url: str | None = None,
    http_status: int | None = None, discovered: int = 0, parsed: int = 0,
    accessible: bool = False,
) -> None:
    if status not in STATUSES:
        raise ValueError(f"无效 Seed 检查状态：{status}")
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection.execute("""CREATE TABLE IF NOT EXISTS career_seed_checks (
        career_url TEXT PRIMARY KEY,
        organization_name TEXT NOT NULL,
        status TEXT NOT NULL,
        platform TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        failed_url TEXT,
        http_status INTEGER,
        reason TEXT NOT NULL,
        discovered INTEGER NOT NULL,
        parsed INTEGER NOT NULL
    )""")
    connection.execute("""INSERT INTO career_seed_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(career_url) DO UPDATE SET
        status=excluded.status, platform=excluded.platform, checked_at=excluded.checked_at,
        failed_url=excluded.failed_url, http_status=excluded.http_status,
        reason=excluded.reason, discovered=excluded.discovered, parsed=excluded.parsed""",
        (seed.career_url, seed.organization_name, status, platform or seed.platform,
         checked_at, failed_url, http_status, reason, discovered, parsed),
    )
    if accessible:
        connection.execute(
            "UPDATE career_seeds SET verified_at=? WHERE career_url=?",
            (datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date().isoformat(), seed.career_url),
        )
    connection.commit()
