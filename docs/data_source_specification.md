# Generic scientific database specification

## Scope

The MVP models a relational scientific-observation database rather than a physical instrument. SQLite is used only to make the demo reproducible without services or credentials. The contract is intended to map to PostgreSQL, DuckDB, and other structured stores.

## Data model

`raw_observations` is a long-form fact table. Each record has a stable ID, UTC time coordinate, station and variable identifiers, a raw numeric value and unit, and a QC flag.

`calibrations` contains versioned affine calibration coefficients keyed by station, variable, and validity start time. An observation uses the latest calibration whose `valid_from` is not later than its timestamp.

`daily_temperature_products` is a derived scientific product keyed by UTC day, station, and variable. It contains the count of admitted samples and their arithmetic mean in kelvin.

## Measurement and processing assumptions

- Raw temperature is stored in degrees Celsius.
- The affine calibration is applied before unit conversion.
- Celsius-to-kelvin conversion uses an offset of exactly 273.15.
- Only observations explicitly marked `GOOD` enter the product.
- Samples are equally weighted.
- Day boundaries are UTC.
- Missing calibration is an error, not a reason to silently use identity calibration.

The synthetic fixture is intentionally small and contains no personal, confidential, or client data.

