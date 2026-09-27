"""Streaming profiles and explicit, limited ingestion contracts."""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta
import math

from src.data_reader import DataReader, ReaderError


def validate_contract(contract):
    if set(contract) != {"version", "fields"} or contract["version"] != 1:
        raise ReaderError("Ingestion contract requires version=1 and fields")
    if not isinstance(contract["fields"], dict) or not contract["fields"]:
        raise ReaderError("Contract fields must be a nonempty object")
    supported = {"required", "nullable", "type", "unit", "unit_field", "minimum", "maximum", "allowed"}
    for name, rule in contract["fields"].items():
        if not isinstance(rule, dict) or set(rule) - supported:
            raise ReaderError(f"Unsupported contract rule for {name}")
        if rule.get("type") not in {"string", "number", "integer", "boolean", "utc_timestamp"}:
            raise ReaderError(f"Unsupported or absent type for {name}")
        for key in ("required", "nullable"):
            if key in rule and not isinstance(rule[key], bool):
                raise ReaderError(f"{name}.{key} must be boolean")
        for key in ("minimum", "maximum"):
            if key in rule and (type(rule[key]) not in (int, float) or not math.isfinite(rule[key])):
                raise ReaderError(f"{name}.{key} must be finite numeric")
        if rule.get("minimum", -math.inf) > rule.get("maximum", math.inf):
            raise ReaderError(f"Inverted range for {name}")
        if "allowed" in rule and not isinstance(rule["allowed"], list):
            raise ReaderError(f"{name}.allowed must be a list")


def _matches(value, kind):
    if kind == "utc_timestamp":
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)
        except (ValueError, AttributeError, TypeError):
            return False
    return {"string": isinstance(value, str), "number": type(value) in (int, float),
            "integer": type(value) is int, "boolean": type(value) is bool}[kind]


def inspect_data(spec, contract=None, limit=None):
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ReaderError("Scan limit must be positive")
    if contract is not None:
        validate_contract(contract)
    reader = DataReader()
    profile, issues, counts = {}, [], Counter()
    total, complete = 0, True

    def issue(position, field, code):
        counts[code] += 1
        if len(issues) < 100:
            issues.append({"record": position, "field": field, "code": code})

    with closing(reader.read(spec)) as records:
        for record in records:
            if limit is not None and total == limit:
                complete = False
                break
            total += 1
            for name, value in record.values.items():
                item = profile.setdefault(name, {"present": 0, "null": 0, "blank": 0,
                                                   "types": Counter(), "examples": []})
                item["present"] += 1
                item["types"][type(value).__name__] += 1
                item["null"] += value is None
                item["blank"] += isinstance(value, str) and value == ""
                example = repr(value)[:160]
                if example not in item["examples"] and len(item["examples"]) < 3:
                    item["examples"].append(example)
            if contract is None:
                continue
            for name, rule in contract["fields"].items():
                if name not in record.values:
                    if rule.get("required", True):
                        issue(total, name, "absent")
                    continue
                value = record.values[name]
                if "unit" in rule:
                    actual = record.values.get(rule["unit_field"]) if "unit_field" in rule else spec.units.get(name)
                    if actual != rule["unit"]:
                        issue(total, name, "unit_mismatch")
                if value is None or value == "":
                    if not rule.get("nullable", False):
                        issue(total, name, "missing_value")
                    continue
                if not _matches(value, rule["type"]):
                    issue(total, name, "type_mismatch")
                    continue
                if type(value) in (int, float):
                    if not math.isfinite(value):
                        issue(total, name, "nonfinite")
                    elif value < rule.get("minimum", -math.inf) or value > rule.get("maximum", math.inf):
                        issue(total, name, "out_of_range")
                if "allowed" in rule and value not in rule["allowed"]:
                    issue(total, name, "unknown_code")
    for item in profile.values():
        item["absent"] = total - item["present"]
    if contract is not None and total == 0:
        issue(None, None, "empty_dataset")
    status = "not_requested" if contract is None else ("failed" if counts else ("passed" if complete else "partial"))
    return {"source": reader.describe(spec), "rows_scanned": total, "complete": complete,
            "fields": profile, "validation": {"status": status, "scope": "ingestion rules only",
            "violation_count": sum(counts.values()), "counts": dict(counts), "examples": issues}}
