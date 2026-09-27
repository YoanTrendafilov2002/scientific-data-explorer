"""Layer 1: Source discovery — read-only inventory via existing connectors.

Reuses DataReader and inspect_data without modification.
Never interprets field values as instructions.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from src.data_reader import DataReader, ReaderError, SourceSpec
from src.data_inspector import inspect_data
from src.discovery.models import (
    ConnectorInfo,
    FieldProfile,
    SourceInventory,
)


def discover_source(
    path: str | Path,
    *,
    format: str | None = None,
    table: str | None = None,
    records_key: str | None = None,
    encoding: str = "utf-8-sig",
    sampling_limit: int | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> SourceInventory:
    """Inspect a source file and return a SourceInventory.

    Parameters
    ----------
    path:
        Local file path.  Must already exist; this function never creates files.
    format:
        Optional format override (csv, json, jsonl, sqlite, noaa-global-hourly …).
        If omitted, inferred from file extension.
    table:
        Required for SQLite sources.
    records_key:
        For JSON sources whose records are nested under a key.
    encoding:
        File encoding (default utf-8-sig to handle BOM).
    sampling_limit:
        Cap the number of rows scanned.  None = full scan.
    source_metadata:
        Caller-supplied key/value pairs (provider, documentation, etc.).
        Stored verbatim; never interpreted as instructions.
    """
    path = Path(path)
    spec = SourceSpec(
        path=path,
        format=format,
        table=table,
        records_key=records_key,
        encoding=encoding,
    )

    # Use inspect_data (existing) to produce field profiles
    profile_report = inspect_data(spec, contract=None, limit=sampling_limit)

    sampling_complete: bool = profile_report["complete"]
    rows_scanned: int = profile_report["rows_scanned"]

    # Build FieldProfile objects
    field_profiles: list[FieldProfile] = []
    for name, stats in profile_report["fields"].items():
        examples_raw = stats.get("examples", [])
        # Examples are repr() strings from the inspector; we store them as-is
        field_profiles.append(FieldProfile(
            name=name,
            present_count=stats.get("present", 0),
            absent_count=stats.get("absent", 0),
            null_count=stats.get("null", 0),
            blank_count=stats.get("blank", 0),
            observed_types=dict(stats.get("types", {})),
            examples=tuple(examples_raw[:3]),
            declared_type=None,  # enriched below for SQLite
        ))

    # Enrich SQLite with declared schema types
    reader = DataReader()
    source_info = reader.describe(spec)
    # URI construction requires an absolute path. Reuse the reader's validated
    # path so relative CLI inputs retain the same schema evidence as the UI.
    path = Path(source_info["source"])
    actual_format = source_info["format"]
    schema_metadata: dict[str, Any] = {"format": actual_format}

    declared_types: dict[str, str] = {}
    if actual_format == "sqlite" and table:
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                pragma = conn.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34)*2)}")')
                for row in pragma:
                    declared_types[row[1]] = row[2]  # name → type affinity
                schema_metadata["pragma_columns"] = list(declared_types.keys())
                # Enumerate all tables
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )]
                schema_metadata["tables"] = tables
        except Exception:  # noqa: BLE001
            pass

    # Re-build profiles with declared_type where available
    if declared_types:
        field_profiles = [
            FieldProfile(
                name=fp.name,
                present_count=fp.present_count,
                absent_count=fp.absent_count,
                null_count=fp.null_count,
                blank_count=fp.blank_count,
                observed_types=fp.observed_types,
                examples=fp.examples,
                declared_type=declared_types.get(fp.name),
            )
            for fp in field_profiles
        ]

    # Enumerate all tables for SQLite sources (even if table wasn't set)
    if actual_format == "sqlite" and "tables" not in schema_metadata:
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                tables = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )]
                schema_metadata["tables"] = tables
        except Exception:  # noqa: BLE001
            pass

    connector = ConnectorInfo(
        format=actual_format,
        path=str(path.resolve()),
        table=table,
        records_key=records_key,
        row_count_estimate=rows_scanned if sampling_complete else None,
        sampling_limit=sampling_limit,
        sampling_complete=sampling_complete,
    )

    warnings: list[str] = []
    if not sampling_complete:
        warnings.append(
            f"Sampling was capped at {sampling_limit} rows; "
            "full-population statistics are unavailable."
        )
    if rows_scanned == 0:
        warnings.append("Source contained no records; field profiles are empty.")

    return SourceInventory(
        connector=connector,
        fields=tuple(field_profiles),
        schema_metadata=schema_metadata,
        source_metadata=dict(source_metadata or {}),
        warnings=tuple(warnings),
    )
