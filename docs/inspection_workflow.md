# Inspect, decode, and validate scientific data

Run from the repository directory, using Python 3.10+:

```powershell
# Inspect original fields without decoding scientific values.
python scripts/read_data.py examples/noaa_lga_20240101.json --inspect

# Preview original and decoded fields side by side.
python scripts/read_data.py --config examples/noaa_config.json --limit 2

# Inspect the complete extract and run the ingestion contract.
python scripts/read_data.py --config examples/noaa_config.json --inspect --contract contracts/noaa_ingestion.json

# Bounded scan: returns partial, not passed, if more records exist.
python scripts/read_data.py --config examples/noaa_config.json --contract contracts/noaa_ingestion.json --scan-limit 5
```

Exit codes: 0 for completed passing validation or inspection without a contract;
1 for a read/configuration error; 2 for failed or partial contract validation.
An inspection-only bounded scan can return 0, but its `complete` flag is false.
The preview limit and scan limit are separate controls. A full scan is the default
for inspection/validation. A bounded scan decodes one extra row to detect truncation.

## Inspector

Each encountered field reports present, absent, null, blank-string, observed Python
types and up to three truncated examples. Missingness is structural: arbitrary
sentinels such as `-999` are not guessed. Native NOAA `+9999` is explicitly decoded
by its adapter, so the derived temperature field correctly counts it as null.
Mixed types remain visible; the inspector never silently fixes them. Examples may
contain source values: do not publish reports from private datasets without review.

## Source and scientific meaning

The checked-in JSON file is a real NOAA NCEI Global Hourly API response for station
72503014732 (LaGuardia), requested for 2024-01-01. The exact URL and retrieval date
are in `examples/noaa_config.json`. It is not the synthetic temperature fixture.

Source documentation: [NOAA ISD format specification, pages 5 and 10–11](https://www.ncei.noaa.gov/pub/data/noaa/isd-format-document.pdf).
The adapter preserves all original fields and adds decoded fields. Native TMP
uses a signed integer in tenths of a degree Celsius plus a QC character. The
missing sentinel is handled before scaling. DATE is documented as UTC. No
calibration, QC filtering, aggregation or sensor-physics inference occurs.

The adapter accepts native Global Hourly CSV or JSON. It does not support
units-converted API exports, fixed-width ISD files, or decoding of other weather
variables. Extra source fields remain available, undecoded. Unknown QC characters
are retained by reading and flagged by the contract. Recognized suspect/error
codes pass the code-vocabulary check: that is not permission to publish those
measurements. Range limits follow the documented TMP range, not a new climate model.

## Four contract layers

`contracts/noaa_scientific_contract.json` implements the requested organization:

1. Source/instrument: dataset identity, documented semantics, unknown sensor details.
2. Variables: classification, units, coordinates and quality dependencies.
3. Transformations: decoding, assumptions and implementation references.
4. Validation: executable ingestion rules and regression-test references.

The declarative manifest links to `contracts/noaa_ingestion.json`. The inspector
executes that smaller rule set: required fields, nullability, types, UTC timestamps,
numeric ranges, exact unit-label equality and allowed codes. Unknown rule keys are
rejected. Unit labels are not dimensional analysis; a matching declared label
alone cannot prove physical correctness. Rule violations are fully counted but
only the first 100 examples are retained. Empty inputs fail. Partial scans cannot
claim a validation pass. A pass covers only these ingestion rules, not all science.

This is separate from the existing affine-calibration/daily-product contract and
dependency graph, whose meaning and tolerances are unchanged. The new manifest is
not automatically compiled into an impact graph yet. It intentionally does not
copy the FIDAS example or claim that public observations are raw sensor events.

## Bob handoff

This implementation was authored in Codex. No Bob execution is claimed. A useful
next Bob task is to add another quantity, such as pressure, with documented units,
missing codes, independent expected decoding tests, and corresponding contract
entries. Capture Bob's actual planning, changes and test runs for the hackathon.
