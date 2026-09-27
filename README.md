# Scientific Data Explorer

[Three-minute video and captions](demo/README.md)

Double-click **Start Explorer.bat** with Python 3.10+ installed, or run `python scripts/launch_explorer.py`. No third-party Python packages are required.

[Explorer manual](docs/EXPLORER_USER_MANUAL.md) · [Workflow manual](docs/USER_MANUAL.md) · [Three-minute script](docs/PRESENTATION_3_MIN.md) · [Bob evidence](bob_sessions/README.md)

# Scientific Contract for Safe Database Modernization

## Submission evidence and current status

See [Bob usage evidence](bob_sessions/README.md) for the genuine task-summary screenshot and contribution attribution. This is a clean manual-upload copy; private data, session exports and generated runs are excluded. Uploading these files is not a hackathon submission.

Bob implemented the pressure extension, layered discovery/planning prototype, browser UI and an initial review-fix pass. Codex built the earlier foundation, completed further approval-safety fixes, and added bounded workflow execution. The UI can now run reviewed read/QC/aggregation/export workflows, with concrete settings, a computed preview, and a separate save approval. Results and provenance are written to unique local run folders; arbitrary generated code is not executed. See the [user manual](docs/USER_MANUAL.md).

## Adaptable reader (new)

The reader now includes field inspection, a native NOAA Global Hourly temperature
adapter, a real one-day NOAA extract, and executable ingestion contracts.
See [inspection workflow](docs/inspection_workflow.md) for the four-layer scientific
contract and runnable demo. The initial reader/inspector foundation was built in Codex; subsequent Bob work and Codex follow-up are documented in the contribution record above.

```powershell
python scripts/read_data.py --config examples/noaa_config.json --inspect --contract contracts/noaa_ingestion.json
```

A separate read-only ingestion layer now supports local CSV/TSV, JSON, JSONL,
and SQLite tables, with explicit column mappings, declared units, source metadata,
and original decoded values. It does not yet feed the temperature demonstrator.
See [reader documentation](docs/data_reader.md) for configuration and limitations.

```powershell
python scripts/read_data.py --config examples/reader_config.json
```

This hackathon prototype demonstrates one proposition:

> IBM Bob can safely modernize scientific database software when it is given a machine-readable Scientific Contract describing what must remain scientifically true.

The demo is deliberately generic. It is not tied to an instrument, vendor, proprietary file format, or live database. One deterministic SQLite fixture represents a common scientific pattern:

`raw observations → temporal calibration → unit conversion → QC gate → daily product`

The schema and Bob workflow are designed to transfer to PostgreSQL, DuckDB, CSV-backed stores, and other scientific databases.

## Why ordinary software tests are insufficient

A query can execute successfully, return the expected columns, and satisfy type checks while still changing the science. Examples include using the wrong conversion constant, joining the wrong calibration version, including rejected observations, changing time-zone boundaries, or altering aggregation weights.

The Scientific Contract connects those implicit scientific expectations to executable checks. It records column semantics, units, ranges, dependencies, calibration policy, QC policy, equations, assumptions, provenance, reference results, and numerical tolerances.

## Demonstrator

The source tables contain long-form air-temperature observations and station-specific affine calibrations. The product query:

1. selects the latest applicable calibration by station, variable, and observation time;
2. calculates `T_cal_C = T_raw_C × scale + offset_C`;
3. converts with `T_K = T_C + 273.15`;
4. admits only rows whose QC flag is `GOOD`;
5. calculates an equally weighted mean for each UTC day, station, and variable.

The fixture is synthetic and carries no claim of representing a particular instrument or network.

## Controlled scientific failure

`scenarios/controlled_failure/database_pipeline.py` uses `273.00` instead of `273.15`. The SQL remains valid and its results look plausible, but every derived daily temperature is biased by exactly **−0.15 K**.

Measured results from the checked-in validator:

| Metric | Controlled defect | Repaired pipeline |
|---|---:|---:|
| Scientific checks passed | 23/27 | 27/27 |
| Scientific Contract violations | 4 | 0 |
| Maximum reference error | 0.15 K | 5.68×10⁻¹⁴ K (floating-point roundoff) |
| Unit tests for the final repository | — | 10/10 |

Regenerate these numbers instead of copying them into a submission:

```powershell
python scripts/run_demo.py
```

The command writes detailed evidence to `metrics/before.json`, `metrics/after.json`, and `metrics/before_after.md`.

## Run validation

The project uses only the Python standard library and Python 3.10 or later.

```powershell
python scripts/validate.py
python -m unittest discover -s tests -v
```

To validate the controlled defect:

```powershell
python scripts/validate.py --pipeline scenarios/controlled_failure/database_pipeline.py
```

That command intentionally exits nonzero after reporting the contract violations.

## Repository map

- `scientific_contract.yaml` — JSON-compatible YAML contract; readable with the standard-library JSON parser.
- `contracts/` — reusable schema for contract structure.
- `src/` — repaired SQL pipeline, contract loader, and scientific validator.
- `tests/` — contract, pipeline, QC, impact-tracing, and regression tests.
- `reference/` — deterministic source fixture and independently declared expected product.
- `.bob/` — Bob rules and reusable project skills.
- `scenarios/controlled_failure/` — intentionally defective SQL implementation.
- `docs/` — provenance, code mapping, impact graph, and demo runbook.
- `metrics/` — measured before/after reports.

## IBM Bob workflow

Bob provides the engineering loop:

`inspect → plan → modify → test → diagnose → repair → regress → document`

The repository supplies the scientific constraints Bob would not otherwise know:

`semantics → units → calibrations → transformations → QC → assumptions → references → tolerances`

Project-specific skills teach Bob to read the contract, map code to transformations, trace downstream impact, run the executable validator, and reject changes outside tolerance. See `.bob/skills/` and `AGENTS.md`.

## Adapting to a real scientific database

Keep the contract and validation engine, then replace the fixture-specific pieces:

1. inventory real tables, views, columns, units, and keys;
2. map each field to a semantic classification and processing level;
3. document query/view/function transformations and calibration/QC dependencies;
4. add small, approved reference extracts without confidential or personal data;
5. bind validation rules to the production dialect and CI environment;
6. generate the impact graph and rerun regression checks for every modernization change.

Do not connect this prototype directly to a production scientific database until credentials, privacy, data ownership, and write isolation are reviewed.
