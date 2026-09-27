"""Actual loopback HTTP checks against fresh application code, ephemeral port."""
import http.client
import json
import threading
import unittest
from http.server import HTTPServer

from scripts import ui_server as api


class HttpCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), api.DiscoveryHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, payload, headers=None, route='/api/discover'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request('POST', route, body=payload,
                headers={'Content-Type': 'application/json', **(headers or {})})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_valid_discovery(self):
        status, response = self.request(json.dumps({'path': 'examples/reader_data.json'}))
        self.assertEqual(status, 200)
        self.assertIn('source_revision', response)

    def test_explorer_reads_without_creating_approval(self):
        status, response = self.request(json.dumps({'path': 'examples/reader_data.json'}), route='/api/explore')
        self.assertEqual(status, 200)
        self.assertEqual(len(response['rows']), 3)
        self.assertNotIn('execution_ticket', response)
        self.assertIn('No QC filtering', response['notice'])

    def test_explorer_same_origin_gate(self):
        self.assertEqual(self.request('', {'Origin': 'https://example.com', 'Content-Length': '2'}, route='/api/explore')[0], 403)

    def test_nonstandard_json_and_duplicate_keys_rejected(self):
        for payload in ('{"path":"examples/reader_data.json","sampling_limit":Infinity}',
                        '{"path":"examples/reader_data.json","sampling_limit":NaN}',
                        '{"path":"examples/reader_data.json","provider":1e999}',
                        '{"path":"examples/reader_data.json","path":"examples/reader_data.json"}'):
            with self.subTest(payload=payload):
                self.assertEqual(self.request(payload)[0], 400)

    def test_deep_json_is_client_error(self):
        self.assertEqual(self.request('[' * 1200 + '0' + ']' * 1200)[0], 400)

    def test_sampling_limit_requires_positive_integer(self):
        for value in (False, True, 0, -1, 1.5, '1.5', [], {}):
            with self.subTest(value=value):
                status, _ = api._handle_discover({'path': 'examples/reader_data.json', 'sampling_limit': value})
                self.assertEqual(status, 400)

    def test_infinite_direct_sampling_limit_is_client_error(self):
        status, _ = api._handle_discover({'path': 'examples/reader_data.json', 'sampling_limit': float('inf')})
        self.assertEqual(status, 400)

    def test_cross_origin_and_host_rejected(self):
        for headers in ({'Origin': 'https://example.com'}, {'Host': 'example.com'}):
            self.assertEqual(self.request('', {'Content-Length': '2', **headers})[0], 403)

    def test_wrong_content_type_and_oversized_body_rejected(self):
        # Send only headers: early rejection must not wait for or consume a body.
        # Sending extra unread bytes can produce a Windows TCP reset on close.
        self.assertEqual(self.request('', {'Content-Type': 'text/plain', 'Content-Length': '2'})[0], 400)
        self.assertEqual(self.request('', {'Content-Length': str(1024 * 1024 + 1)})[0], 400)

    def test_positive_string_limit_supported(self):
        status, response = self.request(json.dumps({'path': 'examples/reader_data.json', 'sampling_limit': '1'}))
        self.assertEqual(status, 200)
        self.assertFalse(response['contract']['inventory']['connector']['sampling_complete'])


if __name__ == '__main__':
    unittest.main()
