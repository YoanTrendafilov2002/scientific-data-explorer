# Adaptable data reader

Update: [inspection and NOAA workflow](inspection_workflow.md) adds explicit native
source decoding and ingestion validation. The generic adapters below remain
non-coercing; the NOAA adapter preserves original fields in `raw` and adds decoded
fields to `values`. Public-source download is supplied as a checked-in example,
not a general HTTP adapter.

This is a separate ingestion foundation, not a replacement for the temperature
pipeline or evidence of a Bob session. It reads local sources without applying
calibration, unit conversion, QC filtering, aggregation, or scientific approval.
No third-party Python packages are required.

## Try it

From the project directory:

```powershell
python scripts/read_data.py --config examples/reader_config.json
python scripts/read_data.py reference/expected_daily_temperature.csv --limit 3
python scripts/read_data.py path/to/observations.sqlite --table observations
```

The JSON preview labels itself `preview_only`. `has_more` indicates additional
records beyond the limit. It reads one extra record to determine that flag;
successful preview does not validate the rest of a file. The example is synthetic.

## Source configuration

`SourceSpec` accepts `path`, optional `format`, `table` (SQLite), `records_key`
(top-level JSON array selector), `delimiter`, `encoding`, `columns`, `units`,
and arbitrary user-supplied `metadata`. Config paths resolve relative to the
configuration file; a command-line source override resolves from the current
working directory. Format defaults to the filename extension.

- CSV/TSV: a header is required. Values stay strings, preserving `0007`, empty
  cells, textual missing markers, and source precision. Duplicate/empty headers,
  malformed quoting, and inconsistent row widths are errors.
- JSON: an array of objects, optionally inside an explicitly selected top-level
  key. Native JSON types and nested fields are retained. Duplicate keys and
  nonstandard NaN/Infinity values are rejected. Python's ordinary JSON number
  decoding is used: decimal numbers become binary floats, not exact decimals.
  Envelope fields outside the selected array are not extracted; keep the original
  file and declare relevant metadata in the configuration.
- JSONL/NDJSON: one object per line, streamed. Blank lines are rejected.
- SQLite: an explicit existing table, opened with `mode=ro` and query-only mode.
  No arbitrary SQL or writes are accepted. Native SQLite types are retained by
  the library, including bytes; the JSON CLI intentionally errors on binary
  values rather than silently converting them. Row order is not guaranteed.

Column mapping uses source-name to canonical-name pairs. Unmapped columns remain
present; missing mapped fields and target-name collisions fail. Units are declared
metadata attached to canonical names, not inferred or verified. No row is excluded
because of its quality flag. Missing values never become zero. Per-row raw data is
the decoded source record, not a byte-exact archival copy.

Every `Record` includes the resolved source path, one-based record position,
`raw` fields, and mapped `values`. Positions are iteration positions, not stable
database identifiers. Source descriptions include the mapping, declared units,
and user metadata. Keep source files unchanged during a read; this version does
not fingerprint or snapshot them. JSON is loaded in memory; other built-in
formats stream records. Mapping/unit presence checks apply to encountered records;
an empty dataset does not prove that its configured fields exist.

## Python extension point

```python
from contextlib import closing
from src.data_reader import DataReader, SourceSpec

reader = DataReader()
spec = SourceSpec("observations.csv", columns={"TEMP": "temperature"},
                  units={"temperature": "degC"})
with closing(reader.read(spec)) as records:
    for record in records:
        print(record.values)
```

Register another format with `reader.register("name", adapter)`. An adapter is
a generator function taking `(resolved_path, spec)` and yielding dictionaries;
it must release resources on generator close. Use `closing` when stopping early.
Nested field selection, HTTP APIs, NetCDF/HDF5, remote databases, automatic
semantic mapping, and binding to the existing Scientific Contract are future
adapters or validation stages, not currently supported features.

For Bob, a bounded next task is to implement one source-specific adapter using
official format documentation, add a small licensed fixture, and demonstrate
that identifiers, QC codes, units, and missing-value semantics survive ingestion.
