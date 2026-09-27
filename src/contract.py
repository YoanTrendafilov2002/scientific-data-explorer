from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL = {
    "contract_version",
    "data_source",
    "files",
    "variables",
    "transformations",
    "validation_rules",
    "reference_datasets",
    "assumptions",
    "quality_rules",
    "code_mappings",
}


def load_contract(path: str | Path) -> dict[str, Any]:
    """Load the JSON-compatible YAML contract without third-party packages."""
    contract_path = Path(path)
    data = json.loads(contract_path.read_text(encoding="utf-8"))
    missing = REQUIRED_TOP_LEVEL.difference(data)
    if missing:
        raise ValueError(f"Contract is missing top-level keys: {sorted(missing)}")
    return data


def variable_index(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {variable["id"]: variable for variable in contract["variables"]}


def transformation_index(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in contract["transformations"]}

