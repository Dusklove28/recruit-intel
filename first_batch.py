"""Discover only the four approved official recruitment columns."""

from contextlib import closing

from collectors.discovery import discover_approved_sources
from config import PROJECT_ROOT
from storage.candidates import save_candidates
from storage.database import connect_database


def main() -> None:
    candidates, warnings, duplicates = discover_approved_sources()
    with closing(connect_database(PROJECT_ROOT / "data" / "recruitment.sqlite3")) as database:
        newly_saved = save_candidates(database, candidates)
        total = database.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    print(f"本次发现 {len(candidates)} 条；新增候选 {newly_saved} 条；候选库共 {total} 条")
    print(f"重复链接 {duplicates} 条；页面失败 {len(warnings)} 个")
    for warning in warnings:
        print(warning)


if __name__ == "__main__":
    main()
