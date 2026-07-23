"""Print or persist the stock monthly shadow-paper status."""

import argparse
import json
from pathlib import Path

from stock_shadow_paper import shadow_performance_summary, update_manifest


ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Stock shadow-paper status")
    parser.add_argument("--db", default=str(ROOT / "trading_bot.db"))
    parser.add_argument(
        "--manifest",
        default=str(ROOT / "data" / "stock_shadow_paper_manifest.json"),
    )
    parser.add_argument("--update-manifest", action="store_true")
    args = parser.parse_args()

    summary = shadow_performance_summary(args.db)
    if args.update_manifest:
        update_manifest(Path(args.manifest), summary)
    print(json.dumps(summary, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
