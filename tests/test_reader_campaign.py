"""Adversarial ingestion regressions; synthetic cases, not scientific data."""
import math
import sqlite3
import tempfile
import unittest
from contextlib import closing, chdir
from pathlib import Path

from src.data_reader import DataReader, ReaderError, SourceSpec
from src.discovery import discover_source


class ReaderCampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def read(self, text, fmt, suffix='.txt', **kwargs):
        path = self.root / ('input' + suffix)
        path.write_text(text, encoding='utf-8')
        return [r.values for r in DataReader().read(SourceSpec(path, format=fmt, **kwargs))]

    def test_explicit_tsv_overrides_extension(self):
        self.assertEqual(self.read('id\tvalue\n001\t2\n', 'tsv'), [{'id': '001', 'value': '2'}])

    def test_explicit_csv_overrides_tsv_extension(self):
        self.assertEqual(self.read('id,value\n001,2\n', 'csv', '.tsv'), [{'id': '001', 'value': '2'}])

    def test_explicit_delimiter_takes_precedence(self):
        self.assertEqual(self.read('id;value\n001;2\n', 'tsv', delimiter=';'), [{'id': '001', 'value': '2'}])

    def test_json_overflow_is_rejected_including_nested_values(self):
        for text, fmt in [('[{"value":1e999}]', 'json'),
                          ('{"value":{"nested":-1e999}}\n', 'jsonl')]:
            with self.subTest(fmt=fmt), self.assertRaises(ReaderError):
                self.read(text, fmt)

    def test_finite_extreme_json_is_preserved(self):
        value = self.read('[{"value":1e308}]', 'json')[0]['value']
        self.assertTrue(math.isfinite(value))
        self.assertEqual(value, 1e308)

    def test_missing_source_has_reader_error(self):
        with self.assertRaises(ReaderError):
            list(DataReader().read(SourceSpec(self.root / 'absent.csv')))

    def test_sqlite_quoted_table_is_readonly_and_preserves_values(self):
        path = self.root / 'fixture.db'
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE "odd""table" (id TEXT, value REAL)')
            connection.execute('INSERT INTO "odd""table" VALUES (?, ?)', ('001', 2.5))
            connection.commit()
        original = path.read_bytes()
        rows = [r.values for r in DataReader().read(SourceSpec(path, table='odd"table'))]
        self.assertEqual(rows, [{'id': '001', 'value': 2.5}])
        self.assertEqual(path.read_bytes(), original)

    def test_relative_sqlite_discovery_preserves_declared_schema(self):
        path = self.root / 'schema.db'
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE measurements (id TEXT, reading REAL)')
            connection.execute('INSERT INTO measurements VALUES (?,?)', ('001', 1.5))
            connection.commit()
        absolute = discover_source(path, table='measurements')
        with chdir(self.root):
            relative = discover_source('schema.db', table='measurements')
        self.assertEqual(relative.schema_metadata, absolute.schema_metadata)
        self.assertEqual({f.name: f.declared_type for f in relative.fields},
                         {'id': 'TEXT', 'reading': 'REAL'})


if __name__ == '__main__':
    unittest.main()
