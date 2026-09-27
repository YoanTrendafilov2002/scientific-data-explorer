"""Reproducible public-source ingestion matrix. Does not grant approvals."""
import csv
import hashlib
import io
import json
import sqlite3
import sys
import time
import urllib.request
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_reader import DataReader, SourceSpec
from scripts.ui_server import _handle_discover


def main():
    folder = ROOT / 'workflow_runs' / ('public_sources_' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'sources': [], 'tests': []}

    def download(name, url, license_note, documentation):
        with urllib.request.urlopen(url, timeout=45) as response:
            data = response.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError('Download exceeds probe limit')
        path = folder / name
        path.write_bytes(data)
        report['sources'].append({'name': name, 'url': url, 'documentation': documentation,
            'license': license_note, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        return path

    def probe(path, fmt, expected, **kwargs):
        started = time.perf_counter()
        spec = SourceSpec(path, format=fmt, **kwargs)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        rows = [r.values for r in DataReader().read(spec)]
        assert rows == expected, 'Round-trip mismatch'
        status, response = _handle_discover({'path': str(path.relative_to(ROOT)), 'format': fmt,
            **kwargs, 'outcome': 'Export all records unchanged'})
        (folder / (path.name + '.discovery.json')).write_text(json.dumps(response, indent=2), encoding='utf-8')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        contract = response.get('contract', {})
        report['tests'].append({'file': path.name, 'format': fmt, 'rows': len(rows),
            'exact_round_trip': True, 'source_unchanged': True, 'sha256': before,
            'seconds': time.perf_counter() - started, 'discovery_status': status,
            'contract_state': contract.get('state'), 'blocked_reasons': contract.get('blocked_reasons'),
            'questions': contract.get('unresolved_questions'),
            'classifications': {m['source_field']: m['classification'] for m in contract.get('variable_mappings', [])}})

    try:
        source = download('iris.zip', 'https://archive.ics.uci.edu/static/public/53/iris.zip',
            'CC BY 4.0; Fisher, R. (1936), Iris, DOI 10.24432/C56C76',
            'https://archive.ics.uci.edu/dataset/53/iris')
        with zipfile.ZipFile(source) as archive:
            raw = archive.read('iris.data').decode('utf-8')
        headers = ['sepal_length', 'sepal_width', 'petal_length', 'petal_width', 'species']
        rows = [dict(zip(headers, row)) for row in csv.reader(io.StringIO(raw)) if row]
        assert len(rows) == 150 and all(len(r) == 5 for r in rows)
        # Preserve lexical numeric strings in every format to test exact identity.
        for fmt in ('csv', 'tsv', 'json', 'jsonl', 'sqlite'):
            path = folder / ('iris.' + fmt)
            if fmt in ('csv', 'tsv'):
                with path.open('w', newline='', encoding='utf-8') as stream:
                    writer = csv.DictWriter(stream, fieldnames=headers, delimiter='\t' if fmt == 'tsv' else ',')
                    writer.writeheader()
                    writer.writerows(rows)
            elif fmt == 'json':
                path.write_text(json.dumps(rows), encoding='utf-8')
            elif fmt == 'jsonl':
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
            else:
                with closing(sqlite3.connect(path)) as connection:
                    connection.execute('CREATE TABLE iris (' + ','.join(h + ' TEXT' for h in headers) + ')')
                    connection.executemany('INSERT INTO iris VALUES (?,?,?,?,?)', [tuple(r.values()) for r in rows])
                    connection.commit()
            probe(path, fmt, rows, **({'table': 'iris'} if fmt == 'sqlite' else {}))
        report['iris_preprocessing'] = 'Headerless iris.data mapped to five documented fields; blank lines omitted; values kept as strings; five converted fixtures, not five independent sources.'
        try:
            source = download('usgs.geojson', 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson',
                'USGS public feed; third-party contributor rights not individually verified; local testing only',
                'https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php')
            data = json.loads(source.read_bytes())
            probe(source, 'json', data['features'], records_key='features')
            report['usgs_feed_metadata'] = data.get('metadata')
        except Exception as exc:
            report['usgs_error'] = str(exc)
    finally:
        (folder / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
        print('Report: ' + str(folder / 'report.json'))


if __name__ == '__main__':
    main()
