import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from src.explorer import preview, PREVIEW_ROWS


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_upload_preserves_cells_and_no_persistent_file(self):
        raw = b'id,value\n0007,0\n0008,NA\n'
        status, data = preview(self.root, {'filename':'../../source.csv', 'content':base64.b64encode(raw).decode()})
        self.assertEqual(status,200)
        self.assertEqual(data['rows'],[{'id':'0007','value':'0'},{'id':'0008','value':'NA'}])
        self.assertEqual(data['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(list(self.root.iterdir()),[])

    def test_reject_bad_inputs_and_traversal(self):
        for body in ([], {'path':'../escape.json'}, {'path':2}, {'filename':'x.json','content':'!'},
                     {'filename':'x.exe','content':''}, {'filename':'x.json','content':base64.b64encode(b'[{"v":NaN}]').decode()}):
            with self.subTest(body=body):self.assertEqual(preview(self.root,body)[0],422)

    def test_limit_is_disclosed(self):
        path=self.root/'data.jsonl'
        path.write_text('\n'.join(json.dumps({'id':i}) for i in range(PREVIEW_ROWS+1)))
        status,data=preview(self.root,{'path':path.name})
        self.assertEqual(status,200)
        self.assertEqual(len(data['rows']),PREVIEW_ROWS)
        self.assertTrue(data['truncated'])

    def test_envelope_and_union_of_fields(self):
        path=self.root/'data.json'
        path.write_text('{"records":[{"a":1},{"b":2}]}')
        status,data=preview(self.root,{'path':path.name,'records_key':'records'})
        self.assertEqual(status,200)
        self.assertEqual(data['fields'],['a','b'])
        self.assertFalse(data['truncated'])

    def test_sqlite_table_selection_and_unchanged_hash(self):
        path=self.root/'data.sqlite'
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE measurements (value REAL)')
            conn.execute('INSERT INTO measurements VALUES (2)')
        conn.close()
        before=path.read_bytes()
        status,data=preview(self.root,{'path':path.name})
        self.assertEqual(status,200)
        self.assertTrue(data['needs_table'])
        self.assertEqual(data['tables'],['measurements'])
        status,data=preview(self.root,{'path':path.name,'table':'measurements'})
        self.assertEqual(status,200)
        self.assertEqual(data['rows'],[{'value':2.0}])
        self.assertEqual(path.read_bytes(),before)

    def test_blob_rejected_cleanly(self):
        path=self.root/'data.sqlite'
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE data (value BLOB)')
            conn.execute('INSERT INTO data VALUES (?)',(b'bytes',))
        conn.close()
        self.assertEqual(preview(self.root,{'path':path.name,'table':'data'})[0],422)
