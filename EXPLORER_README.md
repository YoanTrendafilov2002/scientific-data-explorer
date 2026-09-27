# Scientific Data Explorer

[User manual](docs/EXPLORER_USER_MANUAL.md) · [Reviewed workflow guide](docs/USER_MANUAL.md) · [Three-minute presentation](docs/PRESENTATION_3_MIN.md)

Unzip the package. On Windows, double-click **Start Explorer.bat**. Requires Python 3.10+; no pip packages or internet connection are needed. This is a portable source package, not a standalone executable.

On other systems run `python3 scripts/launch_explorer.py`. The launcher opens a browser on a free loopback-only port. Keep the terminal open; Ctrl+C stops it.

1. Select a project dataset, enter a project-relative path, or browse for CSV, TSV, JSON, JSONL/NDJSON or a closed SQLite snapshot.
2. For SQLite, load once to list tables, choose a table, and load again. For an enveloped JSON array enter its key (for saved workflow results this is `records`).
3. Choose scatter, line, individual-row bars or a ten-bin histogram. Select the columns. Inspect exact source values in the table or focus/hover chart marks.
4. Use **Open reviewed workflow** for contract review and approved execution. Exploration never grants approval or saves scientific products.

Uploads are sent only to your local Python process, read through a temporary copy, and deleted after the request. Maximum upload 5 MiB; project-relative sources 20 MiB. Charts use the first 5,000 records and disclose partial sources; the table shows the first 100. No remote scripts, telemetry or cloud upload.

Numeric strings are plotted as finite decimal numbers. Empty values, booleans, nested objects and non-numeric strings are omitted from charts and counted; original cells remain visible. No unit inference, missing-value imputation or QC filtering. Line plots use source row order and keep gaps; they are not time-series resampling. Bars show individual rows (maximum 40), never category totals. Histograms count numeric rows in ten equal-width bins (one bin for constant values), with the last bin including the maximum. Binary floating-point precision applies. SQLite BLOB/nonfinite values are rejected instead of silently rewritten. Nested fields require an explicit separate projection; Excel, remote database servers and HTML archives are not supported in this picker.

The ZIP excludes private data, campaign snapshots, Bob conversations, previous workflow results and credentials. Code, tests, the scientific contract, reference fixtures and the existing reader/NOAA example fixtures are included. Tests: `python -m unittest discover -s tests -q`; scientific checks: `python scripts/validate.py`. Optional chart calculation tests: `node tests/test_explorer_charts.cjs` (Node is not needed to run the app).
