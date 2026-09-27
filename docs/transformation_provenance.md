# Transformation and provenance map

## Separate generic execution layer

`src/discovery/execution.py` adds bounded execution for the reviewed discovery workflow. It does not replace or alter T001–T004 below. Its chain is: full source scan → optional explicitly configured QC filter → optional aggregation using selected grouping keys/UTC period and equal weights → JSON result plus provenance. No calibration or unit conversion is implied. Missing measurements require an explicit reject/drop policy; excluded and dropped rows are counted. SUSPECT and BAD remain prohibited for publication filtering. Results remain in the approved input unit.

An in-memory preview is bound to the source SHA-256, contract, plan and exact settings. A one-use, ten-minute approval ticket saves the prepared result only if the source remains unchanged. Run folders are unique and ignored by Git. `provenance.json` records the review evidence, settings, counts, source/result hashes and execution approver; it is not an authenticated scientific signature. Regression fixtures in `tests/test_execution.py` independently assert numeric/QC/timezone behavior. The existing scientific contract, expected temperature products and tolerances are unchanged.

## Scientific chain

```text
raw observation + time-versioned calibration
→ affine calibration (T001)
→ Celsius-to-kelvin conversion (T002)
→ GOOD-only validity gate (T003)
→ UTC daily arithmetic mean (T004)
→ daily_mean_temperature_k
```

## T001 — temporal calibration

`T_cal_C = T_raw_C × scale + offset_C`

Calibration is selected by `(station_id, variable_id)` and the latest `valid_from ≤ observed_at`. A missing applicable calibration invalidates the pipeline.

## T002 — unit conversion

`T_K = T_cal_C + 273.15`

The controlled defect replaces 273.15 with 273.00. It does not cause a SQL or type error, but introduces a systematic −0.15 K bias.

## T003 — quality gate

`include ⇔ qc_flag = 'GOOD'`

Both `SUSPECT` and `BAD` are excluded. Using `qc_flag != 'BAD'` would be a scientific-policy change, not a harmless query simplification.

## T004 — aggregation

`daily_mean_K = Σ(T_K) / N_good`

Groups are defined by UTC date, station, and variable. Samples have equal weight. The product retains `N_good` as QC evidence.

Each transformation's implementation symbol, units, assumptions, dependencies, reference result, and tolerance are defined in the contract.
