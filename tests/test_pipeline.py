from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from src import database_pipeline


ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        database_pipeline.create_schema(self.connection)
        self.connection.executescript((ROOT / "reference" / "input.sql").read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.connection.close()

    def test_exact_kelvin_offset(self) -> None:
        self.assertEqual(database_pipeline.KELVIN_OFFSET, 273.15)

    def test_bad_and_suspect_rows_are_excluded(self) -> None:
        database_pipeline.build_daily_temperature_product(self.connection)
        count_sum = self.connection.execute(
            "SELECT SUM(valid_observation_count) FROM daily_temperature_products"
        ).fetchone()[0]
        good_count = self.connection.execute(
            "SELECT COUNT(*) FROM raw_observations WHERE qc_flag='GOOD'"
        ).fetchone()[0]
        self.assertEqual(count_sum, good_count)

    def test_temporal_calibration_is_station_specific(self) -> None:
        database_pipeline.build_daily_temperature_product(self.connection)
        products = database_pipeline.fetch_products(self.connection)
        station_values = {row["station_id"]: row["daily_mean_temperature_k"] for row in products if row["day"] == "2026-09-25"}
        self.assertAlmostEqual(station_values["STATION_A"], 293.07, places=9)
        self.assertAlmostEqual(station_values["STATION_B"], 290.196, places=9)


if __name__ == "__main__":
    unittest.main()

