"""Discovery CLI: inspect a source, produce a draft contract, optionally plan a workflow.

Usage examples
--------------
# Inspect and produce a draft contract (JSON to stdout):
python scripts/discover.py examples/noaa_lga_20240101.json --format noaa-global-hourly

# With an intended outcome (workflow plan blocked until contract approved):
python scripts/discover.py mydata.csv --outcome "Create a daily summary of valid observations"

# Approve a saved contract and plan a workflow:
python scripts/discover.py mydata.csv \\
    --approve contract_draft.json \\
    --approver "Dr. Smith" \\
    --answer "Field X unit" "mg/L" \\
    --outcome "Daily mean of valid measurements"

Exit codes
----------
0  Contract state is approved or inventory-only run completed.
1  Read/configuration error.
2  Contract is in draft, needs_review, or blocked state.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.discovery import (
    ApprovalRecord,
    ContractNotApprovedError,
    apply_approval,
    build_draft_contract,
    discover_source,
    plan_workflow,
    recognize_science,
)
from src.data_reader import ReaderError


# ---------------------------------------------------------------------------
# Serialisation helpers (dataclasses → plain dicts for JSON)
# ---------------------------------------------------------------------------

def _to_json(obj: Any) -> Any:
    """Recursively convert frozen dataclasses and tuples to JSON-serialisable types."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        d = dataclasses.asdict(obj)
        return _to_json(d)
    if isinstance(obj, dict):
        return {k: _to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="Path to the data file to inspect")
    parser.add_argument("--format", help="Format override (csv, json, jsonl, sqlite, …)")
    parser.add_argument("--table", help="Table name (SQLite only)")
    parser.add_argument("--records-key", dest="records_key",
                        help="JSON envelope key containing the record array")
    parser.add_argument("--sampling-limit", dest="sampling_limit", type=int,
                        help="Cap rows scanned (partial scan)")
    parser.add_argument("--provider", help="Source provider name (metadata)")
    parser.add_argument("--documentation", help="Documentation URL (metadata)")
    parser.add_argument("--instrument", help="Instrument description (metadata)")
    parser.add_argument("--outcome", help="Desired outcome for workflow planning")
    parser.add_argument("--approve", type=Path,
                        help="Path to a previously saved draft contract JSON to approve")
    parser.add_argument("--approver", help="Approver name (required with --approve)")
    parser.add_argument("--answer", nargs=2, action="append", metavar=("QUESTION", "ANSWER"),
                        help="Answer an unresolved question (repeatable)")
    parser.add_argument("--inventory-only", dest="inventory_only", action="store_true",
                        help="Only run layer 1 (source inventory); skip recognition")
    args = parser.parse_args()

    try:
        # --- Layer 1: inventory ---
        inventory = discover_source(
            args.source,
            format=args.format,
            table=args.table,
            records_key=args.records_key,
            sampling_limit=args.sampling_limit,
            source_metadata={
                k: v for k, v in [
                    ("provider", args.provider),
                    ("documentation", args.documentation),
                    ("instrument", args.instrument),
                ] if v
            },
        )

        if args.inventory_only:
            print(json.dumps(_to_json(inventory), indent=2, ensure_ascii=False))
            return 0

        # --- Layers 2 + 3: recognition ---
        mappings = recognize_science(inventory)

        # --- Layer 4: draft contract ---
        contract = build_draft_contract(
            inventory,
            mappings,
            source_provider=args.provider,
            source_documentation=args.documentation,
            source_instrument=args.instrument,
        )

        # --- Optional: apply approval ---
        if args.approve:
            if not args.approver:
                print("Error: --approver is required when using --approve", file=sys.stderr)
                return 1
            answers: dict[str, str] = {}
            for q, a in (args.answer or []):
                answers[q] = a
            record = ApprovalRecord(approver=args.approver, approved_answers=answers,
                                    decision="approve", question_decisions={q: "approve" for q in answers})
            try:
                contract = apply_approval(contract, record)
            except ContractNotApprovedError as exc:
                print(f"Approval failed: {exc}", file=sys.stderr)
                return 2

        # --- Layer 5: workflow planning (only if --outcome given and approved) ---
        workflow_plan = None
        if args.outcome:
            if contract.state == "approved":
                workflow_plan = plan_workflow(contract, args.outcome)
            else:
                # Return the plan in blocked state
                from src.discovery.models import WorkflowPlan
                workflow_plan = WorkflowPlan(
                    outcome_description=args.outcome,
                    contract_state=contract.state,
                    steps=(),
                    blocked_reasons=(
                        f"Contract is in state '{contract.state}'; "
                        "approve the contract before planning a workflow.",
                    ),
                    missing_information=(),
                    warnings=(),
                )

        # --- Output ---
        output: dict[str, Any] = {
            "contract": _to_json(contract),
        }
        if workflow_plan is not None:
            output["workflow_plan"] = _to_json(workflow_plan)

        print(json.dumps(output, indent=2, ensure_ascii=False))

        if contract.state == "approved":
            return 0
        return 2

    except ReaderError as exc:
        print(f"Reader error: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
