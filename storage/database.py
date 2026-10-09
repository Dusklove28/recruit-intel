"""One announcement URL is one row; repeated runs update that row."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from extractor.schema import RecruitmentRecord


COLUMNS = list(RecruitmentRecord.model_fields)
SCHEMA_TYPES = {
    "sequence": "INTEGER",
    **{name: "TEXT" for name in COLUMNS if name != "sequence"},
}


def connect_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    column_definitions = ",\n".join(f"{name} {SCHEMA_TYPES[name]}" for name in COLUMNS)
    connection.execute(
        f"""CREATE TABLE IF NOT EXISTS recruitment (
            source_url TEXT PRIMARY KEY,
            {column_definitions},
            raw_text TEXT NOT NULL,
            field_evidence TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    existing = {row[1] for row in connection.execute("PRAGMA table_info(recruitment)")}
    if "field_evidence" not in existing:
        connection.execute("ALTER TABLE recruitment ADD COLUMN field_evidence TEXT NOT NULL DEFAULT '{}'")
    connection.commit()
    return connection


def save_record(
    connection: sqlite3.Connection, source_url: str, record: RecruitmentRecord, raw_text: str,
    field_evidence: dict[str, list[str]] | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    values = record.model_dump(mode="json")
    names = ["source_url", *COLUMNS, "raw_text", "field_evidence", "created_at", "updated_at"]
    placeholders = ", ".join("?" for _ in names)
    update_assignments = ", ".join(
        f"{name}=excluded.{name}" for name in [*COLUMNS, "raw_text", "field_evidence", "updated_at"]
    )
    connection.execute(
        f"INSERT INTO recruitment ({', '.join(names)}) VALUES ({placeholders}) "
        f"ON CONFLICT(source_url) DO UPDATE SET {update_assignments}",
        [source_url, *(values[name] for name in COLUMNS), raw_text,
         json.dumps(field_evidence or {}, ensure_ascii=False), now, now],
    )
    connection.commit()


def list_records(connection: sqlite3.Connection) -> list[RecruitmentRecord]:
    rows = connection.execute(
        f"SELECT {', '.join(COLUMNS)} FROM recruitment ORDER BY created_at, source_url"
    ).fetchall()
    return [RecruitmentRecord.model_validate(dict(row)) for row in rows]
