"""Documented technical test approval, not human scientific certification."""
import json
import hashlib
import sys
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import ui_server as api


def check_format(folder, fmt):
    rows = json.loads((folder / 'iris.json').read_text())
    fields = ['sepal_length', 'sepal_width', 'petal_length', 'petal_width']
    source = folder / ('iris.' + fmt)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    request = {'path': str(source.relative_to(ROOT)), 'format': fmt,
        'outcome': 'mean sepal length grouped by species',
        'provider': 'UCI Iris, Fisher (1936), DOI 10.24432/C56C76',
        'documentation': 'https://archive.ics.uci.edu/dataset/53/iris',
        'unit_overrides': {f: {'unit': 'cm', 'evidence':
            'UCI Iris variables table explicitly lists this measurement in cm; no conversion applied.'} for f in fields}}
    if fmt == 'sqlite':
        request['table'] = 'iris'
    status, discovered = api._handle_discover(request)
    assert status == 200, discovered
    assert not discovered['contract']['blocked_reasons'], discovered
    questions = discovered['contract']['unresolved_questions']
    notes = {q: ('Confirmed for this non-temporal technical test: each record is a plant; '
                 'species grouping needs no timestamp.' if 'temporal' in q else
                 'Confirmed against UCI Iris variable definitions: all four lengths are cm; values retained unchanged.') for q in questions}
    request.update(approver='Codex automated integration test (not human scientific approval)',
        decision='approve', answers=notes, question_decisions={q: 'approve' for q in questions},
        source_revision=discovered['source_revision'])
    status, reviewed = api._handle_discover(request)
    assert status == 200, reviewed
    request['step_confirmations'] = {q: {'decision': 'approve', 'note':
        f'Technical regression specification: {fmt} source, arithmetic mean of sepal_length in cm, species grouping, equal plant weights, reject missing values.'}
        for step in reviewed['workflow_plan']['steps'] for q in step['required_approvals']}
    request['settings'] = {'value_field': 'sepal_length', 'group_by': ['species'],
        'method': 'mean', 'weighting': 'equal', 'missing_values': 'reject'}
    status, preview = api._prepare_execution(request)
    assert status == 200, preview
    expected = defaultdict(list)
    for row in rows:
        expected[row['species']].append(Decimal(row['sepal_length']))
    expected = {species: sum(values) / len(values) for species, values in expected.items()}
    for record in preview['preview']:
        assert record['sample_count'] == 50
        assert abs(Decimal(str(record['value'])) - expected[record['group']['species']]) < Decimal('1e-12')
    status, result = api._execute({'execution_ticket': preview['execution_ticket'],
        'decision': 'approve', 'approved_by': 'Codex automated integration test; not publication validation'})
    assert status == 200, result
    run_folder = ROOT / 'workflow_runs' / result['run_id']
    output_bytes = (run_folder / 'result.json').read_bytes()
    saved = json.loads(output_bytes)
    provenance = json.loads((run_folder / 'provenance.json').read_text(encoding='utf-8'))
    assert saved == preview['preview']
    assert len(saved) == 3 and sum(row['sample_count'] for row in saved) == 150
    assert provenance['result_sha256'] == hashlib.sha256(output_bytes).hexdigest()
    assert provenance['source_sha256'] == before
    assert provenance['settings'] == request['settings']
    assert provenance['scientifically_validated'] is False
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    replay_status, _ = api._execute({'execution_ticket': preview['execution_ticket'],
        'decision': 'approve', 'approved_by': 'Technical replay rejection test'})
    assert replay_status == 409
    evidence = {'format': fmt, 'technical_test_only': True, 'human_scientific_approval': False,
        'saved_result_matches_preview': True, 'provenance_hashes_match': True,
        'source_unchanged': True, 'ticket_replay_rejected': True,
        'reference_method': 'Independent Decimal arithmetic from preserved original decimal strings',
        'expected_cm': {k: str(v) for k, v in expected.items()}, 'preview': preview, 'run': result}
    evidence['preview'].pop('execution_ticket')
    return evidence


def main():
    folder = Path(sys.argv[1]).resolve()
    folder.relative_to(ROOT / 'workflow_runs')
    evidence = [check_format(folder, fmt) for fmt in ('csv', 'tsv', 'json', 'jsonl', 'sqlite')]
    path = folder / ('iris_execution_matrix_' + uuid.uuid4().hex[:12] + '.json')
    path.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    for item in evidence:
        print(item['format'], item['run']['counts'], 'hashes/round-trip/replay: PASS')
    print('Evidence: ' + str(path))


if __name__ == '__main__':
    main()
