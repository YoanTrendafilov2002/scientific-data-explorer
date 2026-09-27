from __future__ import annotations

import unittest
from pathlib import Path

from src.validation import validate_pipeline


ROOT = Path(__file__).resolve().parents[1]


class RegressionTests(unittest.TestCase):
    def test_repaired_pipeline_passes_every_scientific_check(self) -> None:
        report = validate_pipeline(ROOT, ROOT / "src" / "database_pipeline.py")
        failures = [check for check in report["checks"] if not check["passed"]]
        self.assertEqual(failures, [])

    def test_controlled_defect_is_detected_and_traced(self) -> None:
        report = validate_pipeline(ROOT, ROOT / "scenarios" / "controlled_failure" / "database_pipeline.py")
        self.assertGreater(report["summary"]["failed"], 0)
        self.assertIn("T002", report["affected_transformations"])
        self.assertIn("daily_mean_temperature_k", report["affected_outputs"])


if __name__ == "__main__":
    unittest.main()

