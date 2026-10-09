"""Provisional discoveries are kept outside the formal recruitment table."""

from datetime import datetime, timezone
import sqlite3

from collectors.discovery import Candidate


def create_candidate_table(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS candidates (
        notice_url TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        discovery_url TEXT NOT NULL,
        title TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT '待核验',
        reason TEXT,
        official_url TEXT,
        unit_name TEXT,
        first_seen_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    connection.commit()


def save_candidates(connection: sqlite3.Connection, candidates: list[Candidate]) -> int:
    create_candidate_table(connection)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = 0
    for item in candidates:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO candidates
            (notice_url, source, discovery_url, title, state, first_seen_at, updated_at)
            VALUES (?, ?, ?, ?, '待核验', ?, ?)""",
            (item.notice_url, item.source, item.discovery_url, item.title, now, now),
        )
        inserted += cursor.rowcount
    connection.commit()
    return inserted


def update_candidate(
    connection: sqlite3.Connection, notice_url: str, state: str, *,
    reason: str | None = None, official_url: str | None = None,
    unit_name: str | None = None,
) -> None:
    if state not in {"待核验", "正式收录", "重复", "已截止"}:
        raise ValueError("无效候选状态")
    cursor = connection.execute(
        """UPDATE candidates SET state=?, reason=?, official_url=?, unit_name=?, updated_at=?
        WHERE notice_url=?""",
        (state, reason, official_url, unit_name,
         datetime.now(timezone.utc).isoformat(timespec="seconds"), notice_url),
    )
    if cursor.rowcount != 1:
        raise ValueError("候选链接不存在")
    connection.commit()
