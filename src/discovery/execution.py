"""Bounded workflow runner. No generated code, shell commands or source writes."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.data_reader import DataReader, SourceSpec

MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
SUPPORTED = {"read_and_validate_source", "apply_qc_filter", "temporal_aggregation",
             "aggregate_records", "export_records"}


class ExecutionError(ValueError):
    pass


def source_hash(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise ExecutionError("Use a local source file no larger than 20 MiB")
    # A live SQLite journal cannot be represented by hashing the main file alone.
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-journal")):
        raise ExecutionError("Use a closed SQLite snapshot without a WAL or journal")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required(row, field, position):
    if field not in row or row[field] is None or row[field] == "":
        raise ExecutionError(f"Record {position}: required field '{field}' is missing or empty")
    return row[field]


def calculate(contract: dict, plan: dict, config: dict) -> dict:
    """Read all records and calculate in memory; output publication is separate."""
    if contract.get("state") != "approved" or contract.get("blocked_reasons") or contract.get("unresolved_questions"):
        raise ExecutionError("An approved contract is required")
    if plan.get("blocked_reasons") or plan.get("missing_information") or not plan.get("steps"):
        raise ExecutionError("All workflow decisions must be reviewed first")
    names = [step["name"] for step in plan["steps"]]
    if names == ["read_and_validate_source"] and plan.get("warnings"):
        raise ExecutionError("The requested outcome was not recognized; request an explicit supported export or aggregation")
    if set(names) - SUPPORTED or names[0] != "read_and_validate_source" or len(names) != len(set(names)):
        raise ExecutionError("This plan contains unsupported or duplicate operations")
    connector = contract["inventory"]["connector"]
    if not connector["sampling_complete"] or connector.get("sampling_limit") is not None:
        raise ExecutionError("Inspect the full dataset without a sampling limit before execution")
    if not isinstance(config, dict) or set(config) - {"qc_field", "accepted_qc", "value_field", "group_by", "timestamp_field", "period", "method", "weighting", "missing_values"}:
        raise ExecutionError("Invalid execution settings")
    fields = {m["source_field"]: m for m in contract["variable_mappings"]}
    use_qc = "apply_qc_filter" in names
    aggregate = "temporal_aggregation" in names or "aggregate_records" in names
    temporal = "temporal_aggregation" in names
    qc = config.get("qc_field")
    accepted = config.get("accepted_qc")
    if use_qc:
        if qc not in fields or fields[qc]["classification"] != "QUALITY_CONTROL":
            raise ExecutionError("Choose an approved quality-control field")
        if not isinstance(accepted, list) or not accepted or any(not isinstance(v, str) or not v for v in accepted):
            raise ExecutionError("Declare a nonempty list of accepted QC codes")
        if any(v.upper() in ("SUSPECT", "BAD") for v in accepted):
            raise ExecutionError("SUSPECT and BAD cannot enter published products under the current safety policy")
    elif qc or accepted:
        raise ExecutionError("QC settings do not match this plan")
    groups = config.get("group_by", [])
    if not isinstance(groups, list) or any(not isinstance(g, str) or g not in fields for g in groups) or len(groups) != len(set(groups)):
        raise ExecutionError("Grouping keys must be distinct source fields")
    value = config.get("value_field")
    method = config.get("method")
    if aggregate:
        if value not in fields or fields[value]["classification"] not in ("DIRECT_MEASUREMENT", "CALIBRATED_MEASUREMENT") or fields[value]["proposed_unit"] == "unknown":
            raise ExecutionError("Choose an approved measurement with a known unit")
        if method not in ("mean", "sum", "min", "max") or config.get("weighting") != "equal":
            raise ExecutionError("Choose mean/sum/min/max and explicitly confirm equal sample weights")
        if config.get("missing_values") not in ("reject", "drop"):
            raise ExecutionError("Choose reject or drop for null/blank measurements")
    elif any(config.get(k) for k in ("value_field", "method", "weighting", "missing_values", "group_by")):
        raise ExecutionError("Aggregation settings do not match this plan")
    timestamp = config.get("timestamp_field")
    period = config.get("period")
    if temporal:
        if timestamp not in fields or fields[timestamp]["classification"] != "COORDINATE" or period not in ("hourly", "daily", "monthly"):
            raise ExecutionError("Select a temporal coordinate and hourly/daily/monthly UTC period")
    elif timestamp or period:
        raise ExecutionError("Temporal settings do not match this plan")

    path = Path(connector["path"])
    before = source_hash(path)
    source_rows, retained, rejected, dropped = 0, [], 0, 0
    spec = SourceSpec(path, format=connector["format"], table=connector.get("table"), records_key=connector.get("records_key"))
    buckets = {}
    for record in DataReader().read(spec):
        source_rows += 1
        if source_rows > MAX_ROWS:
            raise ExecutionError("Execution limit is 100,000 records")
        row = record.values
        if use_qc and str(_required(row, qc, record.position)) not in accepted:
            rejected += 1
            continue
        if not aggregate:
            retained.append(row)
            continue
        raw = row.get(value)
        if raw is None or raw == "":
            if config["missing_values"] == "drop":
                dropped += 1
                continue
            raise ExecutionError(f"Record {record.position}: missing measurement '{value}'")
        try:
            if isinstance(raw, bool):
                raise ValueError()
            number = float(raw)
            if not math.isfinite(number):
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise ExecutionError(f"Record {record.position}: measurement must be a finite number") from None
        grouping = {g: _required(row, g, record.position) for g in groups}
        if any(isinstance(v, (dict, list)) for v in grouping.values()):
            raise ExecutionError("Grouping keys must be scalar values")
        period_start = None
        if temporal:
            try:
                dt = datetime.fromisoformat(str(_required(row, timestamp, record.position)).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    raise ValueError()
                dt = dt.astimezone(timezone.utc)
                dt = dt.replace(minute=0, second=0, microsecond=0)
                if period in ("daily", "monthly"):
                    dt = dt.replace(hour=0)
                if period == "monthly":
                    dt = dt.replace(day=1)
                period_start = dt.isoformat()
            except (ValueError, TypeError):
                raise ExecutionError(f"Record {record.position}: use ISO timestamps with explicit UTC offset") from None
        key = json.dumps([grouping, period_start], sort_keys=True, allow_nan=False)
        bucket = buckets.setdefault(key, {"group": grouping, "period_start_utc": period_start, "values": []})
        bucket["values"].append(number)
    if source_hash(path) != before:
        raise ExecutionError("Source changed while reading; inspect and approve again")
    if aggregate:
        for key in sorted(buckets):
            bucket = buckets[key]
            values = bucket.pop("values")
            try:
                result = {"min": min, "max": max, "sum": math.fsum,
                          "mean": lambda v: math.fsum(x / len(v) for x in v)}[method](values)
                if not math.isfinite(result):
                    raise ValueError()
            except (ValueError, OverflowError):
                raise ExecutionError("Aggregation produced a non-finite result") from None
            retained.append({**bucket, "field": value, "method": method, "value": result,
                             "unit": fields[value]["proposed_unit"], "sample_count": len(values)})
    if not retained:
        raise ExecutionError("No output records remain; no product will be published")
    # Strict serialization also rejects unsupported SQLite blobs and nested NaN.
    try:
        json.dumps(retained, allow_nan=False)
    except (TypeError, ValueError):
        raise ExecutionError("Output cannot be represented losslessly as standard JSON") from None
    return {"records": retained, "source_sha256": before, "settings": dict(config),
            "counts": {"source_rows": source_rows, "qc_excluded": rejected,
                       "missing_measurements_dropped": dropped, "output_rows": len(retained)},
            "unit_conversion": "none", "calibration": "none"}


def publish(root: Path, prepared: dict, approved_by: str) -> dict:
    """Write a new run directory only; never overwrite an existing output."""
    destination = root / "workflow_runs"
    if destination.is_symlink() or not destination.resolve().is_relative_to(root.resolve()):
        raise ExecutionError("Output directory must remain inside the project")
    destination.mkdir(exist_ok=True)
    run_id = uuid.uuid4().hex
    run = destination / run_id
    run.mkdir()
    result = prepared["result"]
    data = json.dumps(result["records"], ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    provenance = {"run_id": run_id, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                  "execution_approved_by": approved_by, "source": prepared["request"]["path"],
                  "source_sha256": result["source_sha256"], "settings": result["settings"],
                  "counts": result["counts"], "contract": prepared["contract"], "plan": prepared["plan"],
                  "step_confirmations": prepared["request"].get("step_confirmations"),
                  "result_sha256": hashlib.sha256(data).hexdigest(),
                  "unit_conversion": "none", "calibration": "none", "scientifically_validated": False}
    with (run / "result.json").open("xb") as stream:
        stream.write(data)
    with (run / "provenance.json").open("x", encoding="utf-8") as stream:
        json.dump(provenance, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return {"run_id": run_id, "counts": result["counts"],
            "result_url": f"/api/runs/{run_id}/result.json",
            "provenance_url": f"/api/runs/{run_id}/provenance.json"}
