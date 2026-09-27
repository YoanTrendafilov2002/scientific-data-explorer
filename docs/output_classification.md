# Output classification

## File level

| Path | Role | Format |
|---|---|---|
| `reference/input.sql` | Raw database fixture plus calibration metadata | SQL |
| `reference/expected_daily_temperature.csv` | Processed scientific reference product | CSV |
| `scientific_contract.yaml` | Scientific metadata and validation configuration | JSON-compatible YAML |
| `metrics/*.json` | Validation and provenance evidence | JSON |
| `docs/dependency_graph.json` | Machine-readable scientific impact graph | JSON |

## Variable level

| Variable | Classification | Level | Unit | Source |
|---|---|---:|---|---|
| `observation_id` | `METADATA` | L0 | 1 | raw table |
| `observed_at` | `COORDINATE` | L0 | UTC | raw table |
| `station_id` | `METADATA` | L0 | 1 | raw table |
| `raw_temperature_c` | `RAW_ACQUISITION` | L0 | degC | raw table |
| `qc_flag` | `QUALITY_CONTROL` | L0 | 1 | raw table |
| `calibration_scale` | `CALIBRATION_DATA` | L1 | 1 | calibration table |
| `calibration_offset_c` | `CALIBRATION_DATA` | L1 | degC | calibration table |
| `calibrated_temperature_c` | `CALIBRATED_MEASUREMENT` | L1 | degC | T001 |
| `temperature_k` | `SCIENTIFIC_INTERMEDIATE` | L2 | K | T002 |
| `qc_valid_temperature_k` | `SCIENTIFIC_INTERMEDIATE` | L2 | K | T003 |
| `daily_mean_temperature_k` | `DERIVED_PRODUCT` | L3 | K | T004 |
| `valid_observation_count` | `QUALITY_CONTROL` | L3 | 1 | T004 |

Full datatypes, dimensions, ranges, dependencies, and associated QC variables are machine-readable in `scientific_contract.yaml`.

