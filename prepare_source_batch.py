"""Prepare, but do not verify, the first bounded batch from a supplied workbook."""

from dataclasses import asdict
import json
from pathlib import Path

from discovery.historical_seed_import import load_priority_batch


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "央国企历史招聘SourceSeed库_2025-2026_复核版.xlsx"
OUTPUT = ROOT / "data" / "cache" / "source_registry_batch_100.json"


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(f"历史 Seed 文件未放在项目根目录：{INPUT.name}")
    selected = load_priority_batch(INPUT, limit=100)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps([asdict(item) for item in selected], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已准备首批候选：{len(selected)} 家")
    print(f"本地候选清单：{OUTPUT}")
    print("注意：候选根入口和历史链接都尚未核验，不代表当前有效来源。")


if __name__ == "__main__":
    main()
