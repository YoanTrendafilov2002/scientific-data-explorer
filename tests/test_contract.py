from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.contract import REQUIRED_TOP_LEVEL, load_contract, transformation_index, variable_index


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_contract(ROOT / "scientific_contract.yaml")

    def test_required_sections(self) -> None:
        self.assertTrue(REQUIRED_TOP_LEVEL.issubset(self.contract))

    def test_schema_is_valid_json(self) -> None:
        schema = json.loads((ROOT / "contracts" / "scientific_contract.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["title"], "Scientific Data Contract")

    def test_variable_ids_are_unique(self) -> None:
        self.assertEqual(len(variable_index(self.contract)), len(self.contract["variables"]))

    def test_transformation_ids_are_unique(self) -> None:
        self.assertEqual(len(transformation_index(self.contract)), len(self.contract["transformations"]))

    def test_code_mappings_resolve(self) -> None:
        transformations = transformation_index(self.contract)
        for mapping in self.contract["code_mappings"]:
            self.assertIn(mapping["transformation"], transformations)
            self.assertTrue((ROOT / mapping["file"]).exists())


if __name__ == "__main__":
    unittest.main()

