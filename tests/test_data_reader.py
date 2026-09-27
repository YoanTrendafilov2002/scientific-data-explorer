from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.data_reader import DataReader, ReaderError, SourceSpec


class DataReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reader = DataReader()

    def source(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def test_csv_preserves_identifiers_blanks_zero_and_flags(self):
        path = self.source("data.csv", '\ufeffid,value,qc\n0007,0,BAD\n0008,,SUSPECT\n')
        rows = list(self.reader.read(SourceSpec(path, columns={"id": "station"}, units={"value": "K"})))
        self.assertEqual(rows[0].values, {"station": "0007", "value": "0", "qc": "BAD"})
        self.assertEqual(rows[1].raw["value"], "")
        self.assertEqual(rows[1].position, 2)

    def test_csv_quoted_delimiter_and_newline(self):
        path = self.source("data.csv", 'id,note\n1,"a,b\nc"\n')
        self.assertEqual(list(self.reader.read(SourceSpec(path)))[0].values["note"], "a,b\nc")

    def test_tsv(self):
        path = self.source("data.tsv", 'id\tvalue\n001\t4\n')
        self.assertEqual(list(self.reader.read(SourceSpec(path)))[0].raw["id"], "001")

    def test_csv_rejects_duplicate_headers_and_ragged_rows(self):
        for text in ["id,id\n1,2\n", "id,x\n1\n", "id\n1,2\n", ""]:
            with self.subTest(text=text), self.assertRaises(ReaderError):
                list(self.reader.read(SourceSpec(self.source("bad.csv", text))))

    def test_json_preserves_types_and_nested_metadata(self):
        path = self.source("data.json", '[{"id":"007","value":null,"zero":0,"meta":{"qc":false}}]')
        raw = list(self.reader.read(SourceSpec(path)))[0].raw
        self.assertIsNone(raw["value"])
        self.assertEqual(raw["zero"], 0)
        self.assertEqual(raw["meta"], {"qc": False})

    def test_json_envelope(self):
        path = self.source("data.json", '{"results":[{"x":1}],"extra":"metadata"}')
        self.assertEqual(list(self.reader.read(SourceSpec(path, records_key="results")))[0].raw, {"x": 1})
        with self.assertRaises(ReaderError):
            list(self.reader.read(SourceSpec(path)))

    def test_json_rejects_duplicates_nonobjects_and_nonfinite(self):
        for text in ['[{"x":1,"x":2}]', '[1]', '[{"x":NaN}]', '[{"x":Infinity}]']:
            with self.subTest(text=text), self.assertRaises(ReaderError):
                list(self.reader.read(SourceSpec(self.source("bad.json", text))))

    def test_jsonl_streams_and_reports_bad_later_record(self):
        path = self.source("data.jsonl", '{"x":1}\ninvalid\n')
        rows = self.reader.read(SourceSpec(path))
        self.assertEqual(next(rows).raw, {"x": 1})
        with self.assertRaisesRegex(ReaderError, "line 2"):
            next(rows)

    def test_mapping_collisions_and_missing_fields_rejected(self):
        path = self.source("data.json", '[{"x":1,"y":2}]')
        for mapping in [{"x": "y"}, {"absent": "z"}, {"x": "z", "y": "z"}]:
            with self.subTest(mapping=mapping), self.assertRaises(ReaderError):
                list(self.reader.read(SourceSpec(path, columns=mapping)))

    def test_units_must_reference_present_columns(self):
        path = self.source("data.json", '[{"x":1}]')
        with self.assertRaises(ReaderError):
            list(self.reader.read(SourceSpec(path, units={"absent": "K"})))

    def test_sqlite_read_only_and_quoted_table(self):
        path = self.root / "source.sqlite"
        connection = sqlite3.connect(path)
        connection.execute('CREATE TABLE "a""b" (id TEXT, value REAL)')
        connection.execute('INSERT INTO "a""b" VALUES (?, ?)', ("0007", None))
        connection.commit()
        connection.close()
        before = path.read_bytes()
        rows = list(self.reader.read(SourceSpec(path, table='a"b')))
        self.assertEqual(rows[0].raw, {"id": "0007", "value": None})
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(ReaderError):
            list(self.reader.read(SourceSpec(path, table='a; DROP TABLE x;--')))

    def test_missing_database_is_not_created(self):
        path = self.root / "absent.db"
        with self.assertRaises(ReaderError):
            list(self.reader.read(SourceSpec(path, table="x")))
        self.assertFalse(path.exists())

    def test_custom_adapter(self):
        def adapter(path, spec):
            yield {"value": path.read_text()}
        self.reader.register("custom", adapter)
        path = self.source("data.custom", "007")
        self.assertEqual(list(self.reader.read(SourceSpec(path)))[0].raw, {"value": "007"})
        with self.assertRaises(ReaderError):
            self.reader.register("custom", adapter)

    def test_example(self):
        root = Path(__file__).resolve().parents[1] / "examples"
        config = json.loads((root / "reader_config.json").read_text())
        config["path"] = root / config["path"]
        spec = SourceSpec(**config)
        self.assertEqual(len(list(self.reader.read(spec))), 3)
        self.assertFalse(self.reader.describe(spec)["scientifically_validated"])


if __name__ == "__main__":
    unittest.main()
