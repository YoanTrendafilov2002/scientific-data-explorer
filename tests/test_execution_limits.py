"""Real configured resource boundaries, using disposable synthetic fixtures."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import ui_server as api
from src.discovery.execution import MAX_SOURCE_BYTES, MAX_ROWS, ExecutionError, source_hash


class ExecutionLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(api, 'ROOT', self.root).start()
        patch.object(api, 'PREPARED', {}).start()

    def reviewed_export(self, path):
        request = {'path': path.name, 'outcome': 'Export records unchanged'}
        status, response = api._handle_discover(request)
        self.assertEqual(status, 200, response)
        questions = response['contract']['unresolved_questions']
        request.update(source_revision=response['source_revision'], approver='Synthetic limit test',
            decision='approve', answers={q: 'Confirmed: synthetic identifiers only, non-temporal unchanged export.' for q in questions},
            question_decisions={q: 'approve' for q in questions})
        status, response = api._handle_discover(request)
        self.assertEqual(status, 200, response)
        request['step_confirmations'] = {q: {'decision': 'approve', 'note': 'Synthetic JSONL unchanged-export boundary test.'}
            for s in response['workflow_plan']['steps'] for q in s['required_approvals']}
        request['settings'] = {}
        return request

    def test_exact_byte_limit_and_one_byte_over(self):
        path = self.root / 'large.json'
        with path.open('wb') as stream:
            stream.write(b'[]')
            stream.write(b' ' * (MAX_SOURCE_BYTES - 2))
        self.assertEqual(source_hash(path), hashlib.sha256(path.read_bytes()).hexdigest())
        with path.open('ab') as stream:
            stream.write(b' ')
        with self.assertRaisesRegex(ExecutionError, '20 MiB'):
            source_hash(path)
        status, _ = api._handle_discover({'path': path.name})
        self.assertEqual(status, 400)

    def test_exact_row_limit_and_one_row_over_no_publication(self):
        path = self.root / 'rows.jsonl'
        with path.open('w', encoding='utf-8') as stream:
            for i in range(MAX_ROWS):
                stream.write(json.dumps({'id': str(i)}) + '\n')
        status, preview = api._prepare_execution(self.reviewed_export(path))
        self.assertEqual(status, 200, preview)
        self.assertEqual(preview['counts']['source_rows'], MAX_ROWS)
        self.assertEqual(preview['counts']['output_rows'], MAX_ROWS)
        self.assertEqual(len(preview['preview']), 10)
        self.assertFalse((self.root / 'workflow_runs').exists())
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'id': str(MAX_ROWS)}) + '\n')
        status, rejected = api._prepare_execution(self.reviewed_export(path))
        self.assertEqual(status, 422, rejected)
        self.assertIn('100,000', rejected['error'])
        self.assertFalse((self.root / 'workflow_runs').exists())
        # Previously prepared snapshot is invalidated by the changed source.
        status, _ = api._execute({'execution_ticket': preview['execution_ticket'],
            'decision': 'approve', 'approved_by': 'Synthetic test'})
        self.assertEqual(status, 409)
        self.assertFalse((self.root / 'workflow_runs').exists())

    def test_journal_companions_reject_snapshot(self):
        path = self.root / 'snapshot.sqlite'
        path.write_bytes(b'synthetic file: only the pre-read journal guard is tested')
        for suffix in ('-wal', '-journal'):
            companion = Path(str(path) + suffix)
            companion.write_bytes(b'test')
            with self.assertRaisesRegex(ExecutionError, 'closed SQLite snapshot'):
                source_hash(path)
            companion.unlink()

    def test_pending_preview_cap_rejects_eleventh(self):
        path = self.root / 'small.jsonl'
        path.write_text('{"id":"001"}\n', encoding='utf-8')
        request = self.reviewed_export(path)
        for _ in range(10):
            status, response = api._prepare_execution(request)
            self.assertEqual(status, 200, response)
        status, response = api._prepare_execution(request)
        self.assertEqual(status, 429, response)
        self.assertEqual(len(api.PREPARED), 10)
        self.assertFalse((self.root / 'workflow_runs').exists())


if __name__ == '__main__':
    unittest.main()
