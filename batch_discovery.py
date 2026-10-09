"""CLI for the bounded 20-employer Seed trial."""

import argparse
import json

from discovery.batch_runner import run_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="核验少量央国企招聘入口并导出成品表")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    report, output = run_batch(limit=args.limit)
    print(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    print(f"Excel：{output}")


if __name__ == "__main__":
    main()
