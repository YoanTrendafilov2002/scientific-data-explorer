import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

from src.data_reader import DataReader, ReaderError, SourceSpec
from src.data_inspector import inspect_data


ROOT = Path(__file__).resolve().parents[1]


class NoaaTMPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rows.json"
        self.contract = json.loads((ROOT / "contracts/noaa_ingestion.json").read_text())

    def spec(self, rows):
        self.path.write_text(json.dumps(rows), encoding="utf-8")
        return SourceSpec(self.path, format="noaa-global-hourly")

    def row(self, value="+0061,1", **extra):
        return {"STATION": "00000000001", "DATE": "2024-01-01T00:00:00", "TMP": value, **extra}

    def test_tmp_decode(self):
        spec = self.spec([self.row(), self.row("-0012,2"), self.row("+9999,9"), self.row("+0000,5")])
        rows = list(DataReader().read(spec))
        self.assertEqual([r.values["temperature_c"] for r in rows], [6.1, -1.2, None, 0])
        self.assertEqual(rows[0].raw["TMP"], "+0061,1")
        self.assertNotIn("temperature_c", rows[0].raw)
        self.assertEqual(rows[0].values["observed_at"], "2024-01-01T00:00:00Z")
        self.assertEqual(rows[1].values["temperature_qc"], "2")
        self.assertEqual(inspect_data(spec, self.contract)["validation"]["status"], "passed")

    def test_range_and_unknown_quality_fail_without_filtering(self):
        report = inspect_data(self.spec([self.row("+0800,8")]), self.contract)
        self.assertEqual(report["rows_scanned"], 1)
        self.assertEqual(report["validation"]["counts"], {"out_of_range": 1, "unknown_code": 1})

    def test_malformed_source_rejected(self):
        for row in [self.row("6.1,1"), self.row(DATE="2024-02-30T00:00:00"), self.row(temperature_c=5), self.row(STATION=7)]:
            with self.subTest(row=row), self.assertRaises(ReaderError):
                list(DataReader().read(self.spec([row])))

    def test_partial_never_passes(self):
        report = inspect_data(self.spec([self.row(), self.row()]), self.contract, limit=1)
        self.assertFalse(report["complete"])
        self.assertEqual(report["validation"]["status"], "partial")

    def test_empty_fails(self):
        self.assertEqual(inspect_data(self.spec([]), self.contract)["validation"]["status"], "failed")

    def test_profile_missing_types_and_absent(self):
        spec = self.spec([{"x": None}, {"x": ""}, {"other": 0}])
        report = inspect_data(SourceSpec(spec.path))
        self.assertEqual(report["fields"]["x"]["null"], 1)
        self.assertEqual(report["fields"]["x"]["blank"], 1)
        self.assertEqual(report["fields"]["x"]["absent"], 1)

    def test_generic_contract_and_unit_mismatch(self):
        spec = self.spec([{"x": 4}, {"x": "4"}, {}])
        # Empty records are rejected by the base reader, so use an unrelated field.
        self.path.write_text('[{"x":4},{"x":"4"},{"other":1}]')
        contract = {"version": 1, "fields": {"x": {"type": "number", "unit": "K"}}}
        report = inspect_data(SourceSpec(spec.path, units={}), contract)
        self.assertEqual(report["validation"]["counts"], {"unit_mismatch": 2, "type_mismatch": 1, "absent": 1})

    def test_unknown_rule_rejected(self):
        with self.assertRaises(ReaderError):
            inspect_data(self.spec([]), {"version": 1, "fields": {"x": {"type": "number", "typo": True}}})

    def test_noaa_csv(self):
        path = self.path.with_suffix(".csv")
        path.write_text('STATION,DATE,TMP\n0001,2024-01-01T00:00:00,"+0061,1"\n')
        self.assertEqual(list(DataReader().read(SourceSpec(path, format="noaa-global-hourly")))[0].values["temperature_c"], 6.1)

    def test_real_extract(self):
        spec = SourceSpec(ROOT / "examples/noaa_lga_20240101.json", format="noaa-global-hourly")
        report = inspect_data(spec, self.contract)
        self.assertEqual(report["rows_scanned"], 36)
        self.assertEqual(report["fields"]["temperature_c"]["null"], 2)
        self.assertEqual(report["validation"]["status"], "passed")

    def test_cli_partial_exit_code(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/read_data.py"),
                                 "--config", str(ROOT / "examples/noaa_config.json"),
                                 "--contract", str(ROOT / "contracts/noaa_ingestion.json"),
                                 "--scan-limit", "1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["validation"]["status"], "partial")


# Keep the original class name as an alias so any external references survive.
InspectorTests = NoaaTMPTests


class NoaaSLPTests(unittest.TestCase):
    """Independent tests for NOAA ISD sea-level pressure decoding.

    SLP encoding (ISD format spec):
      <5-digit unsigned integer tenths-of-hPa>,<QC char>
      99999 = missing; otherwise divide by 10 to obtain hPa.
      SLP field is optional; not all record types include it.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rows.json"
        self.contract = json.loads((ROOT / "contracts/noaa_ingestion.json").read_text())

    def spec(self, rows):
        self.path.write_text(json.dumps(rows), encoding="utf-8")
        return SourceSpec(self.path, format="noaa-global-hourly")

    def base_row(self, **extra):
        """Minimal valid row. Extra kwargs override or add fields."""
        return {"STATION": "72503014732", "DATE": "2024-01-01T00:00:00", "TMP": "+0061,1", **extra}

    # ------------------------------------------------------------------
    # Normal decoding
    # ------------------------------------------------------------------

    def test_normal_slp_decodes_correctly(self):
        """10158 tenths-of-hPa → 1015.8 hPa; QC code preserved verbatim."""
        rows = list(DataReader().read(self.spec([self.base_row(SLP="10158,1")])))
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].values["sea_level_pressure_hpa"], 1015.8, places=12)
        self.assertEqual(rows[0].values["slp_unit"], "hPa")
        self.assertEqual(rows[0].values["slp_qc"], "1")

    def test_slp_raw_field_preserved(self):
        """Original SLP text is in raw; decoded key is absent from raw."""
        rows = list(DataReader().read(self.spec([self.base_row(SLP="10158,5")])))
        self.assertEqual(rows[0].raw["SLP"], "10158,5")
        self.assertNotIn("sea_level_pressure_hpa", rows[0].raw)

    def test_slp_boundary_low(self):
        """860.0 hPa (08600 tenths) is within the allowed range."""
        rows = list(DataReader().read(self.spec([self.base_row(SLP="08600,1")])))
        self.assertAlmostEqual(rows[0].values["sea_level_pressure_hpa"], 860.0, places=12)

    def test_slp_boundary_high(self):
        """1090.0 hPa (10900 tenths) is within the allowed range."""
        rows = list(DataReader().read(self.spec([self.base_row(SLP="10900,1")])))
        self.assertAlmostEqual(rows[0].values["sea_level_pressure_hpa"], 1090.0, places=12)

    def test_zero_is_not_missing(self):
        """00000 encodes 0.0 hPa (physically nonsensical but not the missing sentinel)."""
        rows = list(DataReader().read(self.spec([self.base_row(SLP="00000,1")])))
        self.assertEqual(rows[0].values["sea_level_pressure_hpa"], 0.0)
        self.assertIsNotNone(rows[0].values["sea_level_pressure_hpa"])

    def test_several_qc_codes(self):
        """QC characters 1, 5, 9 are all passed through verbatim."""
        for qc in ("1", "5", "9"):
            with self.subTest(qc=qc):
                rows = list(DataReader().read(self.spec([self.base_row(SLP=f"10150,{qc}")])))
                self.assertEqual(rows[0].values["slp_qc"], qc)

    # ------------------------------------------------------------------
    # Missing-sentinel handling
    # ------------------------------------------------------------------

    def test_slp_missing_sentinel_yields_null(self):
        """99999 is the ISD missing sentinel; decoded to None, not 9999.9."""
        rows = list(DataReader().read(self.spec([self.base_row(SLP="99999,9")])))
        self.assertIsNone(rows[0].values["sea_level_pressure_hpa"])
        self.assertEqual(rows[0].values["slp_qc"], "9")

    def test_slp_missing_sentinel_passes_nullable_contract(self):
        """A null sea_level_pressure_hpa must not trigger a missing_value violation."""
        report = inspect_data(self.spec([self.base_row(SLP="99999,9")]), self.contract)
        self.assertNotIn("missing_value", report["validation"]["counts"])

    # ------------------------------------------------------------------
    # Absent SLP field (field not present in source record)
    # ------------------------------------------------------------------

    def test_absent_slp_yields_no_decoded_fields(self):
        """Records without SLP must not emit sea_level_pressure_hpa or slp_qc."""
        rows = list(DataReader().read(self.spec([self.base_row()])))
        self.assertNotIn("sea_level_pressure_hpa", rows[0].values)
        self.assertNotIn("slp_qc", rows[0].values)
        self.assertNotIn("slp_unit", rows[0].values)

    def test_absent_slp_passes_contract(self):
        """Absent SLP should not cause a validation failure (field is not required)."""
        report = inspect_data(self.spec([self.base_row()]), self.contract)
        self.assertNotIn("absent", report["validation"]["counts"])
        self.assertEqual(report["validation"]["status"], "passed")

    def test_mixed_absent_and_present_slp(self):
        """Rows with and without SLP coexist correctly."""
        rows = list(DataReader().read(self.spec([
            self.base_row(SLP="10158,1"),
            self.base_row(),
            self.base_row(SLP="99999,9"),
        ])))
        self.assertAlmostEqual(rows[0].values["sea_level_pressure_hpa"], 1015.8, places=12)
        self.assertNotIn("sea_level_pressure_hpa", rows[1].values)
        self.assertIsNone(rows[2].values["sea_level_pressure_hpa"])

    # ------------------------------------------------------------------
    # Malformed SLP encoding
    # ------------------------------------------------------------------

    def test_malformed_slp_rejected(self):
        """Various invalid SLP strings must raise ReaderError, not silently pass."""
        bad_values = [
            "1015.8,1",   # decimal not allowed
            "+10158,1",   # sign prefix not part of SLP format
            "1015,1",     # too few digits
            "101580,1",   # too many digits
            "10158",      # missing QC char
            "10158,",     # empty QC char
            "",           # empty string
        ]
        for bad in bad_values:
            with self.subTest(slp=bad), self.assertRaises(ReaderError):
                list(DataReader().read(self.spec([self.base_row(SLP=bad)])))

    # ------------------------------------------------------------------
    # Unknown QC code (contract-level check, not a reader-level error)
    # ------------------------------------------------------------------

    def test_unknown_slp_qc_flagged_by_contract(self):
        """QC code '8' is not in the allowed vocabulary; inspector counts it."""
        report = inspect_data(self.spec([self.base_row(SLP="10158,8")]), self.contract)
        self.assertIn("unknown_code", report["validation"]["counts"])
        self.assertGreaterEqual(report["validation"]["counts"]["unknown_code"], 1)

    def test_unknown_slp_qc_not_a_reader_error(self):
        """Unknown QC is a contract violation, not a format error; reading must succeed."""
        rows = list(DataReader().read(self.spec([self.base_row(SLP="10158,8")])))
        self.assertEqual(rows[0].values["slp_qc"], "8")

    # ------------------------------------------------------------------
    # Out-of-range pressure (contract-level check)
    # ------------------------------------------------------------------

    def test_out_of_range_slp_flagged_by_contract(self):
        """A pressure value outside [860, 1090] hPa triggers an out_of_range violation."""
        # 00001 tenths = 0.1 hPa — physically impossible, not the 99999 sentinel
        report = inspect_data(self.spec([self.base_row(SLP="00001,1")]), self.contract)
        self.assertIn("out_of_range", report["validation"]["counts"])

    # ------------------------------------------------------------------
    # Real-extract integration check
    # ------------------------------------------------------------------

    def test_real_extract_slp(self):
        """Integration: 36 rows, 4 null (99999), 32 real values; contract passes."""
        spec = SourceSpec(ROOT / "examples/noaa_lga_20240101.json", format="noaa-global-hourly")
        report = inspect_data(spec, self.contract)
        self.assertEqual(report["rows_scanned"], 36)
        # All 36 records include the SLP field in this extract.
        self.assertEqual(report["fields"]["sea_level_pressure_hpa"]["present"], 36)
        # 4 records carry the 99999 missing sentinel.
        self.assertEqual(report["fields"]["sea_level_pressure_hpa"]["null"], 4)
        # The 32 real values must all be within range and with recognized QC codes.
        self.assertEqual(report["validation"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
