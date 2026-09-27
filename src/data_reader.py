"""Read-only, loss-conscious adapters. Reading is not scientific validation."""
from __future__ import annotations

import csv
import json
import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator


class ReaderError(ValueError):
    """Invalid source data or reader configuration."""


@dataclass(frozen=True)
class SourceSpec:
    path: str | Path
    format: str | None = None
    table: str | None = None
    records_key: str | None = None
    delimiter: str | None = None
    encoding: str = "utf-8-sig"
    # Source column -> canonical column. Unmapped columns remain present.
    columns: dict[str, str] = field(default_factory=dict)
    # Canonical column -> user-declared unit; never inferred or converted.
    units: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Record:
    source: str
    position: int
    raw: dict[str, Any]
    values: dict[str, Any]


@dataclass(frozen=True)
class DecodedRow:
    raw: dict[str, Any]
    values: dict[str, Any]


Adapter = Callable[[Path, SourceSpec], Iterator[dict[str, Any] | DecodedRow]]


def _headers(names: list[str]) -> None:
    if not names or any(not isinstance(name, str) or not name for name in names):
        raise ReaderError("Column names must be nonempty strings")
    if len(names) != len(set(names)):
        raise ReaderError("Duplicate column names would lose data")


def _csv(path: Path, spec: SourceSpec) -> Iterator[dict[str, Any]]:
    kind = spec.format or path.suffix.lower().lstrip(".")
    delimiter = spec.delimiter if spec.delimiter is not None else ("\t" if kind == "tsv" else ",")
    if len(delimiter) != 1:
        raise ReaderError("Delimiter must be one character")
    with path.open(encoding=spec.encoding, newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter, strict=True)
        names = next(reader, None)
        if names is None:
            raise ReaderError("CSV has no header")
        _headers(names)
        for row in reader:
            if len(row) != len(names):
                raise ReaderError(f"CSV line {reader.line_num}: expected {len(names)} cells, got {len(row)}")
            yield dict(zip(names, row))


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReaderError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ReaderError(f"Nonstandard JSON number: {value}")


def _loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_object, parse_constant=_invalid_constant,
                      parse_float=_finite_float)


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ReaderError(f"JSON number exceeds finite float range: {text}")
    return value


def _json(path: Path, spec: SourceSpec) -> Iterator[dict[str, Any]]:
    data = _loads(path.read_text(encoding=spec.encoding))
    if spec.records_key is not None:
        if not isinstance(data, dict) or spec.records_key not in data:
            raise ReaderError(f"JSON records key not found: {spec.records_key}")
        data = data[spec.records_key]
    if not isinstance(data, list):
        raise ReaderError("JSON must contain an array of objects; set records_key for an envelope")
    yield from data


def _jsonl(path: Path, spec: SourceSpec) -> Iterator[dict[str, Any]]:
    with path.open(encoding=spec.encoding) as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                raise ReaderError(f"JSONL line {line_number}: blank records are not allowed")
            try:
                yield _loads(line)
            except ValueError as exc:
                raise ReaderError(f"JSONL line {line_number}: {exc}") from exc


def _sqlite(path: Path, spec: SourceSpec) -> Iterator[dict[str, Any]]:
    if not spec.table:
        raise ReaderError("SQLite requires an explicit table name")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (spec.table,)
        ).fetchone()
        if not exists:
            raise ReaderError(f"SQLite table not found: {spec.table}")
        identifier = '"' + spec.table.replace('"', '""') + '"'
        cursor = connection.execute(f"SELECT * FROM {identifier}")
        names = [column[0] for column in cursor.description]
        _headers(names)
        for row in cursor:
            yield dict(zip(names, row))


class DataReader:
    """Register adapters; obtain records without writes, coercion or filtering."""

    def __init__(self) -> None:
        self.adapters: dict[str, Adapter] = {
            "csv": _csv, "tsv": _csv, "json": _json,
            "jsonl": _jsonl, "ndjson": _jsonl, "sqlite": _sqlite,
        }
        from src.noaa_adapter import read_noaa
        self.adapters["noaa-global-hourly"] = read_noaa

    def register(self, name: str, adapter: Adapter) -> None:
        if not name or name in self.adapters or not callable(adapter):
            raise ReaderError("Adapter needs a unique name and a callable")
        self.adapters[name] = adapter

    def describe(self, spec: SourceSpec) -> dict[str, Any]:
        try:
            path = Path(spec.path).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ReaderError(f"Cannot access source: {exc}") from exc
        if not path.is_file():
            raise ReaderError("Source must be a local file")
        kind = spec.format or path.suffix.lower().lstrip(".")
        kind = {"db": "sqlite", "sqlite3": "sqlite"}.get(kind, kind)
        if kind not in self.adapters:
            raise ReaderError(f"Unsupported format: {kind}; choose {sorted(self.adapters)}")
        if any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
               for k, v in spec.columns.items()):
            raise ReaderError("Column mappings require nonempty string names")
        if len(set(spec.columns.values())) != len(spec.columns):
            raise ReaderError("Column mappings have duplicate targets")
        return {"source": str(path), "format": kind, "table": spec.table,
                "records_key": spec.records_key, "column_mapping": dict(spec.columns),
                "declared_units": dict(spec.units), "metadata": dict(spec.metadata),
                "scientifically_validated": False}

    def read(self, spec: SourceSpec) -> Iterator[Record]:
        info = self.describe(spec)
        path = Path(info["source"])
        try:
            with closing(self.adapters[info["format"]](path, spec)) as rows:
                for position, raw in enumerate(rows, 1):
                    original = raw.raw if isinstance(raw, DecodedRow) else raw
                    raw = raw.values if isinstance(raw, DecodedRow) else raw
                    if not isinstance(raw, dict):
                        raise ReaderError(f"Record {position}: expected an object")
                    _headers(list(raw))
                    missing = set(spec.columns) - raw.keys()
                    if missing:
                        raise ReaderError(f"Record {position}: missing mapped columns {sorted(missing)}")
                    names = [spec.columns.get(name, name) for name in raw]
                    _headers(names)
                    values = dict(zip(names, raw.values()))
                    if set(spec.units) - values.keys():
                        raise ReaderError(f"Record {position}: units refer to absent columns")
                    yield Record(str(path), position, dict(original), values)
        except (OSError, UnicodeError, csv.Error, sqlite3.Error, ValueError) as exc:
            raise ReaderError(f"{path.name}: {exc}") from exc
