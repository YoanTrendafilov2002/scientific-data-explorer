"""Public ecological-source integration test with explicit NA normalization.

Source is retained intact. A separate two-field projection tests missing policies.
Automated technical-test approvals are not human scientific certification.
"""
import csv
import hashlib
import io
import json
import sys
import urllib.request
import uuid
from collections import defaultdict
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_reader import DataReader, SourceSpec
from scripts import ui_server as api


def main():
    folder = ROOT / 'workflow_runs' / ('penguins_' + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    url = 'https://raw.githubusercontent.com/allisonhorst/palmerpenguins/main/inst/extdata/penguins.csv'
    with urllib.request.urlopen(url, timeout=45) as response:
        raw = response.read(1024 * 1024 + 1)
    assert len(raw) <= 1024 * 1024
    source = folder / 'penguins.csv'
    source.write_bytes(raw)
    original = hashlib.sha256(raw).hexdigest()
    reference = list(csv.DictReader(io.StringIO(raw.decode('utf-8'))))
    actual = [r.values for r in DataReader().read(SourceSpec(source))]
    assert reference == actual and len(actual) == 344
    base = {'path': str(source.relative_to(ROOT)), 'format': 'csv', 'outcome': 'mean body mass by species'}
    status, discovered = api._handle_discover(base)
    assert status == 200, discovered
    # Preserve raw sentinel spelling; normalize only in an explicit derivative.
    records = [{'species': r['species'], 'body_mass': None if r['body_mass_g'] == 'NA' else r['body_mass_g']}
               for r in actual]
    projected = folder / 'body_mass_projection.json'
    projected.write_text(json.dumps(records), encoding='utf-8')
    request = {'path': str(projected.relative_to(ROOT)), 'format': 'json',
        'outcome': 'mean body mass grouped by species',
        'provider': 'palmerpenguins; Horst, Hill, Gorman (2020)',
        'documentation': 'https://allisonhorst.github.io/palmerpenguins/',
        'unit_overrides': {'body_mass': {'unit': 'g', 'evidence':
            'Official penguins documentation defines body_mass_g in grams; this projection retains values and maps documented NA to JSON null.'}}}
    status, response = api._handle_discover(request)
    assert status == 200 and not response['contract']['blocked_reasons'], response
    questions = response['contract']['unresolved_questions']
    request.update(approver='Automated technical test; not human scientific approval', decision='approve',
        source_revision=response['source_revision'], question_decisions={q: 'approve' for q in questions},
        answers={q: 'Confirmed for technical test: species grouping is non-temporal; documented body_mass_g is grams; NA is represented as null in a separate derivative.' for q in questions})
    status, response = api._handle_discover(request)
    assert status == 200, response
    request['step_confirmations'] = {q: {'decision': 'approve', 'note':
        'Technical test specification: arithmetic mean in grams by species, equal weights, compare reject versus explicit null-drop policy; no QC or calibration.'}
        for step in response['workflow_plan']['steps'] for q in step['required_approvals']}
    settings = {'value_field': 'body_mass', 'group_by': ['species'], 'method': 'mean',
        'weighting': 'equal', 'missing_values': 'reject'}
    rejected_status, rejected = api._prepare_execution(dict(request, settings=settings))
    assert rejected_status == 422 and 'missing measurement' in rejected['error'], rejected
    settings = dict(settings, missing_values='drop')
    status, preview = api._prepare_execution(dict(request, settings=settings))
    assert status == 200, preview
    expected = defaultdict(list)
    for row in reference:
        if row['body_mass_g'] != 'NA':
            expected[row['species']].append(Decimal(row['body_mass_g']))
    for result in preview['preview']:
        values = expected[result['group']['species']]
        assert result['sample_count'] == len(values)
        assert abs(Decimal(str(result['value'])) - sum(values) / len(values)) < Decimal('1e-9')
    assert preview['counts']['missing_measurements_dropped'] == 2
    assert sum(r['sample_count'] for r in preview['preview']) == 342
    status, run = api._execute({'execution_ticket': preview.pop('execution_ticket'),
        'decision': 'approve', 'approved_by': 'Automated technical test; not scientific publication'})
    assert status == 200, run
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    report = {'captured_at': datetime.now(timezone.utc).isoformat(), 'source_url': url,
        'documentation': request['documentation'], 'license': 'CC0 per official package documentation',
        'citation': 'Horst AM, Hill AP, Gorman KB (2020), DOI 10.5281/zenodo.3960218',
        'source_sha256': original, 'rows': len(actual), 'columns': list(actual[0]),
        'round_trip_exact': True, 'source_unchanged': True,
        'na_counts': {k: sum(r[k] == 'NA' for r in actual) for k in actual[0]},
        'raw_discovery': discovered, 'projection': 'species and body_mass_g only; body_mass_g renamed body_mass; exact NA converted to null; all other values unchanged',
        'projection_sha256': hashlib.sha256(projected.read_bytes()).hexdigest(),
        'reject_policy_response': rejected, 'drop_policy_preview': preview, 'run': run,
        'independent_reference': 'Decimal sum / count from original non-NA strings; tolerance 1e-9 g',
        'scientifically_validated': False}
    (folder / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('rows','source_sha256','na_counts','drop_policy_preview','run')}, indent=2))
    print('Report: ' + str(folder / 'report.json'))


if __name__ == '__main__':
    main()
