from __future__ import annotations

import csv
import importlib.util
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from src.contract import REQUIRED_TOP_LEVEL, load_contract, transformation_index, variable_index


@dataclass(frozen=True)
class CheckResult:
    id: str
    name: str
    passed: bool
    category: str
    detail: str
    affected_transformations: tuple[str, ...] = ()
    affected_outputs: tuple[str, ...] = ()


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("pipeline_under_validation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import pipeline: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reference_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _result(
    id_: str,
    name: str,
    passed: bool,
    category: str,
    detail: str,
    transforms: tuple[str, ...] = (),
    outputs: tuple[str, ...] = (),
) -> CheckResult:
    return CheckResult(id_, name, bool(passed), category, detail, transforms, outputs)


def validate_pipeline(project_root: Path, pipeline_path: Path) -> dict[str, Any]:
    contract = load_contract(project_root / "scientific_contract.yaml")
    variables = variable_index(contract)
    transformations = transformation_index(contract)
    module = _load_module(pipeline_path)
    checks: list[CheckResult] = []

    checks.append(_result(
        "C001", "contract top-level structure",
        REQUIRED_TOP_LEVEL.issubset(contract), "contract",
        "All mandatory Scientific Contract sections are present."
    ))
    checks.append(_result(
        "C002", "variable identifiers are unique",
        len(variables) == len(contract["variables"]), "contract",
        f"Indexed {len(variables)} variables."
    ))
    checks.append(_result(
        "C003", "transformation identifiers are unique",
        len(transformations) == len(contract["transformations"]), "contract",
        f"Indexed {len(transformations)} transformations."
    ))
    semantic_classes = {
        "RAW_ACQUISITION", "DIRECT_MEASUREMENT", "CALIBRATED_MEASUREMENT",
        "SCIENTIFIC_INTERMEDIATE", "DERIVED_PRODUCT", "RETRIEVED_PRODUCT",
        "AUXILIARY_MEASUREMENT", "HOUSEKEEPING", "QUALITY_CONTROL",
        "CALIBRATION_DATA", "METADATA", "COORDINATE"
    }
    unknown_classes = sorted({v["classification"] for v in contract["variables"]} - semantic_classes)
    checks.append(_result(
        "C004", "semantic classifications are valid", not unknown_classes,
        "contract", f"Unknown classifications: {unknown_classes or 'none'}."
    ))
    referenced_variables = {
        variable
        for transformation in contract["transformations"]
        for variable in transformation["inputs"] + transformation["outputs"]
    }
    missing_variables = sorted(referenced_variables - set(variables))
    checks.append(_result(
        "C005", "transformation variables resolve", not missing_variables,
        "provenance", f"Missing variable definitions: {missing_variables or 'none'}."
    ))

    connection = sqlite3.connect(":memory:")
    module.create_schema(connection)
    connection.executescript((project_root / "reference" / "input.sql").read_text(encoding="utf-8"))

    required_raw = {"observation_id", "observed_at", "station_id", "variable_id", "raw_value", "raw_unit", "qc_flag"}
    required_cal = {"station_id", "variable_id", "valid_from", "scale", "offset"}
    raw_columns = {row[1] for row in connection.execute("PRAGMA table_info(raw_observations)")}
    cal_columns = {row[1] for row in connection.execute("PRAGMA table_info(calibrations)")}
    checks.append(_result(
        "D001", "required raw columns", required_raw.issubset(raw_columns),
        "schema", f"Raw columns: {sorted(raw_columns)}."
    ))
    checks.append(_result(
        "D002", "required calibration columns", required_cal.issubset(cal_columns),
        "schema", f"Calibration columns: {sorted(cal_columns)}.", ("T001",), ("calibrated_temperature_c",)
    ))
    raw_count = connection.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0]
    checks.append(_result("D003", "input is non-empty", raw_count > 0, "data_shape", f"Found {raw_count} observations."))

    timestamps = [row[0] for row in connection.execute("SELECT observed_at FROM raw_observations")]
    timestamp_valid = True
    for value in timestamps:
        try:
            timestamp_valid &= value.endswith("Z")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            timestamp_valid = False
    checks.append(_result(
        "D004", "timestamps are UTC ISO-8601", timestamp_valid,
        "timestamp_shape", f"Validated {len(timestamps)} timestamps.", ("T004",), ("daily_mean_temperature_k",)
    ))

    qc_values = {row[0] for row in connection.execute("SELECT DISTINCT qc_flag FROM raw_observations")}
    allowed_qc = set(contract["quality_rules"][0]["allowed"])
    checks.append(_result(
        "D005", "QC labels are recognized", qc_values.issubset(allowed_qc),
        "quality_control", f"Observed labels: {sorted(qc_values)}.", ("T003",), ("daily_mean_temperature_k",)
    ))
    raw_min, raw_max = connection.execute("SELECT MIN(raw_value), MAX(raw_value) FROM raw_observations").fetchone()
    raw_range = variables["raw_temperature_c"]["expected_range"]
    checks.append(_result(
        "D006", "raw values are in contract range",
        raw_range["minimum"] <= raw_min <= raw_max <= raw_range["maximum"],
        "expected_range", f"Observed raw range: [{raw_min}, {raw_max}] degC.",
        ("T001",), ("calibrated_temperature_c",)
    ))

    missing_calibrations = connection.execute(
        """
        SELECT COUNT(*) FROM raw_observations AS o
        WHERE NOT EXISTS (
            SELECT 1 FROM calibrations AS c
            WHERE c.station_id=o.station_id AND c.variable_id=o.variable_id
              AND c.valid_from <= o.observed_at
        )
        """
    ).fetchone()[0]
    checks.append(_result(
        "D007", "every observation has calibration", missing_calibrations == 0,
        "calibration", f"Observations without applicable calibration: {missing_calibrations}.",
        ("T001",), ("calibrated_temperature_c",)
    ))

    checks.append(_result(
        "T001", "kelvin offset constant", math.isclose(float(module.KELVIN_OFFSET), 273.15, abs_tol=1e-12),
        "transformation_consistency", f"Implementation uses {module.KELVIN_OFFSET}; contract requires 273.15.",
        ("T002",), ("temperature_k", "daily_mean_temperature_k")
    ))

    module.build_daily_temperature_product(connection)
    actual = module.fetch_products(connection)
    expected = _reference_rows(project_root / "reference" / "expected_daily_temperature.csv")

    checks.append(_result(
        "P001", "product row count", len(actual) == len(expected),
        "data_shape", f"Actual rows={len(actual)}, reference rows={len(expected)}.",
        ("T004",), ("daily_mean_temperature_k",)
    ))
    keys = [(row["day"], row["station_id"], row["variable_id"]) for row in actual]
    checks.append(_result(
        "P002", "product keys are unique", len(keys) == len(set(keys)),
        "data_shape", f"Product keys: {keys}.", ("T004",), ("daily_mean_temperature_k",)
    ))
    counts_positive = all(int(row["valid_observation_count"]) > 0 for row in actual)
    checks.append(_result(
        "P003", "valid counts are positive", counts_positive,
        "quality_control", "Every emitted product has at least one GOOD observation.",
        ("T003", "T004"), ("valid_observation_count",)
    ))

    expected_by_key = {
        (row["day"], row["station_id"], row["variable_id"]): row for row in expected
    }
    reference_errors: list[float] = []
    for index, row in enumerate(actual, start=1):
        key = (str(row["day"]), str(row["station_id"]), str(row["variable_id"]))
        reference = expected_by_key.get(key)
        checks.append(_result(
            f"R{index:03d}A", f"reference key {key}", reference is not None,
            "regression", "Product key exists in reference output.",
            ("T004",), ("daily_mean_temperature_k",)
        ))
        if reference is None:
            continue
        actual_count = int(row["valid_observation_count"])
        expected_count = int(reference["valid_observation_count"])
        checks.append(_result(
            f"R{index:03d}B", f"QC count {key}", actual_count == expected_count,
            "quality_control", f"Actual count={actual_count}; expected={expected_count}.",
            ("T003", "T004"), ("valid_observation_count",)
        ))
        actual_value = float(row["daily_mean_temperature_k"])
        expected_value = float(reference["daily_mean_temperature_k"])
        reference_errors.append(abs(actual_value - expected_value))
        tolerance = transformations["T004"]["validation_tolerance"]
        passed = math.isclose(actual_value, expected_value, rel_tol=tolerance["relative"], abs_tol=tolerance["absolute"])
        checks.append(_result(
            f"R{index:03d}C", f"numerical regression {key}", passed,
            "numerical_tolerance",
            f"Actual={actual_value:.12g} K; expected={expected_value:.12g} K; absolute error={abs(actual_value-expected_value):.12g} K.",
            ("T001", "T002", "T003", "T004"), ("daily_mean_temperature_k",)
        ))

    kelvin_range = variables["daily_mean_temperature_k"]["expected_range"]
    product_range_ok = all(
        kelvin_range["minimum"] <= float(row["daily_mean_temperature_k"]) <= kelvin_range["maximum"]
        for row in actual
    )
    checks.append(_result(
        "P004", "derived products are in contract range", product_range_ok,
        "expected_range", f"Required range: {kelvin_range} K.",
        ("T002", "T004"), ("daily_mean_temperature_k",)
    ))
    expected_total_good = connection.execute("SELECT COUNT(*) FROM raw_observations WHERE qc_flag='GOOD'").fetchone()[0]
    actual_total_good = sum(int(row["valid_observation_count"]) for row in actual)
    checks.append(_result(
        "P005", "QC gate excludes non-GOOD rows", actual_total_good == expected_total_good,
        "quality_control", f"Product count sum={actual_total_good}; source GOOD rows={expected_total_good}.",
        ("T003",), ("valid_observation_count", "daily_mean_temperature_k")
    ))

    failures = [asdict(check) for check in checks if not check.passed]
    passed_count = sum(check.passed for check in checks)
    report = {
        "pipeline": str(pipeline_path.relative_to(project_root)).replace("\\", "/"),
        "summary": {
            "total": len(checks),
            "passed": passed_count,
            "failed": len(checks) - passed_count,
            "contract_violations": len(failures),
            "max_reference_error_k": max(reference_errors, default=0.0),
        },
        "affected_transformations": sorted({item for failure in failures for item in failure["affected_transformations"]}),
        "affected_outputs": sorted({item for failure in failures for item in failure["affected_outputs"]}),
        "checks": [asdict(check) for check in checks],
    }
    connection.close()
    return report


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
