# First IBM Bob task

Extend this scientific-data reader with NOAA Global Hourly sea-level pressure
decoding, using the existing adapter and four-layer scientific contract.

Read AGENTS.md, docs/inspection_workflow.md, contracts/noaa_scientific_contract.json,
contracts/noaa_ingestion.json, src/noaa_adapter.py and tests/test_inspector.py first.
Explain the scientific impact before editing. Consult NOAA's official ISD format
specification for SLP encoding, units, missing values and quality codes:
https://www.ncei.noaa.gov/pub/data/noaa/isd-format-document.pdf

Requirements:

- Preserve every original source field and all existing temperature behavior.
- Decode native SLP into pressure and QC fields with explicit units. Do not
  guess missing codes, apply calibration, drop rows or conflate ingestion checks
  with publication eligibility.
- Handle optional absent SLP explicitly; distinguish it from a real zero.
- Update the source/variable/transformation/validation contract layers and
  implementation mappings. Keep this independent of the synthetic calibration
  and daily-temperature pipeline. Do not introduce FIDAS dependencies.
- Add independently specified expected-value tests for normal, missing,
  malformed and unknown-QC cases, plus a real-extract integration check.
- Run `python -m unittest discover -s tests -v`, `python scripts/validate.py`,
  and the NOAA inspection command documented in docs/inspection_workflow.md.
  Do not weaken tolerances or rules to make tests pass.
- Summarize files changed, actual test outcomes, and scientific limitations.
  Do not attribute existing code to Bob: this is Bob's first implementation task.

Stay within this project. Do not publish, push, install packages, change security
settings, or access credentials. Ask if new permissions are needed.
