"""Preview local data without changing the source."""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import closing
from dataclasses import asdict
from itertools import islice
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_reader import DataReader, SourceSpec
from src.data_inspector import inspect_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?")
    parser.add_argument("--config", type=Path, help="JSON SourceSpec; paths relative to this file")
    parser.add_argument("--format")
    parser.add_argument("--table")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--inspect", action="store_true", help="Profile fields and missingness")
    parser.add_argument("--contract", type=Path, help="JSON ingestion contract")
    parser.add_argument("--scan-limit", type=int, help="Cap inspection; partial scans cannot pass")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8-sig")) if args.config else {}
        if args.source:
            config["path"] = args.source
        elif args.config and "path" in config:
            config["path"] = args.config.parent / config["path"]
        if args.format:
            config["format"] = args.format
        if args.table:
            config["table"] = args.table
        spec = SourceSpec(**config)
        if args.inspect or args.contract:
            contract = json.loads(args.contract.read_text(encoding="utf-8-sig")) if args.contract else None
            result = inspect_data(spec, contract, args.scan_limit)
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0 if result["validation"]["status"] in {"passed", "not_requested"} else 2
        reader = DataReader()
        with closing(reader.read(spec)) as records:
            preview = [asdict(row) for row in islice(records, args.limit + 1)]
        result = {"source": reader.describe(spec), "preview_only": True,
                  "has_more": len(preview) > args.limit, "records": preview[:args.limit]}
        print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f"Reader error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
