"""Run and report the user-approved first 100 historical source checks."""

import argparse
import json

from discovery.historical_batch_runner import run_historical_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="重新核验首批历史央国企招聘源并发现2027校招")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--no-search", action="store_true", help="只核验历史入口，不调用搜索 API")
    args = parser.parse_args()
    report = run_historical_batch(limit=args.limit, sleep_seconds=args.delay, search_enabled=not args.no_search)
    print(json.dumps({
        "seed_total": report["seed_total"],
        "source_registry": report["source_registry"],
        "current_2027_batch": report["current_2027_batch"],
        "tavily": report["tavily"],
        "qwen": report["qwen"],
        "average_seconds_per_company": report["average_seconds_per_company"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
