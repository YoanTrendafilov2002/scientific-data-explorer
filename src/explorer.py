"""Read-only exploratory previews, separate from approved scientific execution."""
import base64
import binascii
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from src.data_reader import DataReader, SourceSpec, ReaderError
from src.discovery.execution import source_hash

MAX_UPLOAD = 5 * 1024 * 1024
PREVIEW_ROWS = 5000
FORMATS = {"csv", "tsv", "json", "jsonl", "ndjson", "sqlite", "db", "sqlite3"}


def preview(root, body):
    try:
        if not isinstance(body, dict):
            raise ValueError("Request must be an object")
        for key in ("path", "filename", "content", "table", "records_key"):
            if key in body and not isinstance(body[key], str):
                raise ValueError(f"{key} must be text")
        if "content" in body:
            name = Path(body.get("filename", "")).name
            suffix = Path(name).suffix.lower()
            if suffix.lstrip(".") not in FORMATS:
                raise ValueError("Choose CSV, TSV, JSON, JSONL, NDJSON or SQLite")
            if len(body["content"]) > (MAX_UPLOAD + 2) // 3 * 4:
                raise ValueError("Uploads are limited to 5 MiB")
            data = base64.b64decode(body["content"], validate=True)
            if len(data) > MAX_UPLOAD:
                raise ValueError("Uploads are limited to 5 MiB")
            # Fixed name prevents traversal. Temporary copy is removed after reading.
            with tempfile.TemporaryDirectory(prefix="scientific-explorer-") as directory:
                path = Path(directory) / ("source" + suffix)
                path.write_bytes(data)
                return 200, _read(path, body, name)
        path = (Path(root) / body.get("path", "")).resolve()
        if not path.is_relative_to(Path(root).resolve()):
            raise ValueError("Path is outside the project directory")
        if path.suffix.lower().lstrip(".") not in FORMATS:
            raise ValueError("Unsupported data format")
        return 200, _read(path, body, body.get("path", ""))
    except (ValueError, OSError, sqlite3.Error, binascii.Error, TypeError, RecursionError) as exc:
        return 422, {"error": str(exc)}


def _read(path, body, label):
    digest = source_hash(path)
    tables = []
    if path.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        if not body.get("table"):
            return {"source": label, "sha256": digest, "tables": tables, "rows": [], "fields": [], "needs_table": True}
    rows = []
    fields = []
    truncated = False
    stream = DataReader().read(SourceSpec(path, table=body.get("table") or None,
                                             records_key=body.get("records_key") or None))
    try:
        for record in stream:
            if len(rows) == PREVIEW_ROWS:
                truncated = True
                break
            row = record.values
            # BLOBs and nonfinite SQLite numbers must not crash JSON transport.
            json.dumps(row, allow_nan=False)
            rows.append(row)
            for field in row:
                if field not in fields:
                    fields.append(field)
    finally:
        stream.close()
    if source_hash(path) != digest:
        raise ReaderError("Source changed while reading; load again")
    return {"source": label, "sha256": digest, "tables": tables, "rows": rows,
            "fields": fields, "truncated": truncated, "limit": PREVIEW_ROWS,
            "notice": "Exploratory raw data only. No QC filtering, calibration, unit conversion or scientific approval."}
