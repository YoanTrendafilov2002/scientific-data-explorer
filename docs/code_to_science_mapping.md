# Code-to-science mapping

| Scientific concept | Contract transformation | Implementation |
|---|---|---|
| Temporal calibration selection and affine correction | T001 | `src/database_pipeline.py` — `build_daily_temperature_product`, `calibrated` CTE |
| Celsius-to-kelvin conversion | T002 | `src/database_pipeline.py` — `KELVIN_OFFSET`, `valid_kelvin` CTE |
| Publication QC policy | T003 | `src/database_pipeline.py` — `valid_kelvin` CTE `WHERE` clause |
| UTC daily arithmetic mean | T004 | `src/database_pipeline.py` — final grouped `SELECT` |
| Contract parsing and identity checks | V001 | `src/contract.py` |
| Executable scientific validation and impact reporting | V002–V009 | `src/validation.py` |

When Bob changes a symbol, it follows this table into the transformation graph and then walks downstream edges in `dependency_graph.json` to determine which scientific outputs require regression.

