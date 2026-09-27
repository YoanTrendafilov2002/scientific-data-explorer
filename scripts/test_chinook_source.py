"""Read-only probe of a pinned native SQLite sample database, not scientific data."""
import dataclasses
import hashlib
import json
import sqlite3
import sys
import urllib.request
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_reader import DataReader, SourceSpec
from src.discovery import discover_source, recognize_science


def main():
    folder = ROOT / 'workflow_runs' / ('chinook_' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    url = 'https://github.com/lerocha/chinook-database/releases/download/v1.4.5/Chinook_Sqlite.sqlite'
    license_url = 'https://raw.githubusercontent.com/lerocha/chinook-database/v1.4.5/LICENSE.md'
    path = folder / 'Chinook.sqlite'
    for target, source in ((path, url), (folder / 'LICENSE.md', license_url)):
        with urllib.request.urlopen(source, timeout=45) as response:
            payload = response.read(5 * 1024 * 1024 + 1)
        if len(payload) > 5 * 1024 * 1024:
            raise ValueError('Probe download limit exceeded')
        target.write_bytes(payload)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'source_url': url, 'license_url': license_url, 'license': 'MIT-style permission grant',
        'sha256': before, 'captured_at': datetime.now(timezone.utc).isoformat(),
        'engine': 'SQLite', 'scientific_dataset': False,
        'scope': 'Music catalog tables only; customer/employee/invoice data not queried', 'tables': []}
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        for table in ('Album', 'Artist', 'Genre', 'MediaType', 'Playlist', 'PlaylistTrack', 'Track'):
            cursor = connection.execute('SELECT * FROM "' + table + '"')
            names = [column[0] for column in cursor.description]
            reference = [dict(zip(names, row)) for row in cursor]
            actual = [r.values for r in DataReader().read(SourceSpec(path, table=table))]
            assert reference == actual
            inventory = discover_source(path, table=table)
            mappings = recognize_science(inventory)
            relative_inventory = discover_source(path.relative_to(Path.cwd()), table=table)
            report['tables'].append({'table': table, 'rows': len(actual), 'exact_match': True,
                'declared_types': {f.name: f.declared_type for f in inventory.fields},
                'relative_path_declared_types': {f.name: f.declared_type for f in relative_inventory.fields},
                'relative_metadata_matches': relative_inventory.schema_metadata == inventory.schema_metadata,
                'recognition': [dataclasses.asdict(m) for m in mappings]})
            print(table, len(actual), 'exact read PASS; relative schema match:', report['tables'][-1]['relative_metadata_matches'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    report['source_unchanged'] = True
    (folder / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Report: ' + str(folder / 'report.json'))


if __name__ == '__main__':
    main()
