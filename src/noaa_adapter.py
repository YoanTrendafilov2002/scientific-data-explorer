"""NCEI Global Hourly native TMP and SLP decoding; not the units-converted API format."""
from datetime import datetime, timezone
import re

from src.data_reader import DecodedRow, ReaderError, _csv, _json

# ISD SLP: unsigned 5-digit integer (tenths of hPa) + QC char. 99999 = missing.
# Valid atmospheric range per ISD documentation: 8600–10900 tenths-of-hPa (860–1090 hPa).
_SLP_PATTERN = re.compile(r"([0-9]{5}),([0-9A-Z])")
_SLP_MISSING = "99999"
_SLP_DIVISOR = 10.0
_SLP_MIN_HPA = 860.0
_SLP_MAX_HPA = 1090.0


def read_noaa(path, spec):
    loader = _json if path.suffix.lower() == ".json" else _csv
    for position, raw in enumerate(loader(path, spec), 1):
        if not isinstance(raw, dict) or not {"STATION", "DATE", "TMP"} <= raw.keys():
            raise ReaderError(f"NOAA record {position}: requires STATION, DATE, TMP")
        if not isinstance(raw["STATION"], str) or not raw["STATION"]:
            raise ReaderError(f"NOAA record {position}: station must be a nonempty string")
        match = re.fullmatch(r"([+-][0-9]{4}),([0-9A-Z])", str(raw["TMP"]))
        if not match:
            raise ReaderError(f"NOAA record {position}: invalid native TMP encoding")
        encoded, quality = match.groups()
        date = raw["DATE"]
        if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?", date):
            raise ReaderError(f"NOAA record {position}: expected native UTC DATE")
        timestamp = datetime.fromisoformat(date.rstrip("Z")).replace(tzinfo=timezone.utc)
        decoded = {
            "station_id": raw["STATION"],
            "observed_at": timestamp.isoformat().replace("+00:00", "Z"),
            "temperature_c": None if encoded == "+9999" else int(encoded) / 10,
            "temperature_unit": "degC",
            "temperature_qc": quality,
        }
        if "SLP" in raw:
            slp_match = _SLP_PATTERN.fullmatch(str(raw["SLP"]))
            if not slp_match:
                raise ReaderError(f"NOAA record {position}: invalid native SLP encoding")
            slp_encoded, slp_quality = slp_match.groups()
            decoded["sea_level_pressure_hpa"] = (
                None if slp_encoded == _SLP_MISSING else int(slp_encoded) / _SLP_DIVISOR
            )
            decoded["slp_unit"] = "hPa"
            decoded["slp_qc"] = slp_quality
        if decoded.keys() & raw.keys():
            raise ReaderError("NOAA decoded fields collide with source columns")
        yield DecodedRow(dict(raw), {**raw, **decoded})
