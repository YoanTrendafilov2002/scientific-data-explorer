from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.validation import validate_pipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a database pipeline against the Scientific Contract.")
    parser.add_argument("--pipeline", default="src/database_pipeline.py")
    args = parser.parse_args()
    report = validate_pipeline(ROOT, ROOT / args.pipeline)
    print(json.dumps(report, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
