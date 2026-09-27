"""Naming-pattern regressions exposed by external database probes."""
import unittest

from src.discovery.models import FieldProfile, SourceInventory, ConnectorInfo
from src.discovery.recognition import recognize_science


def mapping(name, values):
    types = {}
    for value in values:
        types[type(value).__name__] = types.get(type(value).__name__, 0) + 1
    field = FieldProfile(name, len(values), 0, 0, 0, types, tuple(repr(v) for v in values))
    inventory = SourceInventory(ConnectorInfo('json', 'synthetic.json'), (field,), {}, {}, ())
    return recognize_science(inventory)[0]


class RecognitionCampaignTests(unittest.TestCase):
    def test_camelcase_ids_are_metadata(self):
        for name in ('TrackId', 'AlbumId', 'ArtistId', 'MediaTypeId', 'trackID', 'sampleId'):
            with self.subTest(name=name):
                self.assertEqual(mapping(name, [1, 2, 3]).classification, 'METADATA')

    def test_words_ending_in_id_are_not_identifiers(self):
        for name in ('fluid', 'Fluid', 'FLUID', 'lipid', 'Lipid', 'acid'):
            with self.subTest(name=name):
                self.assertEqual(mapping(name, [1.2, 2.3]).classification, 'DIRECT_MEASUREMENT')

    def test_timestamp_substrings_do_not_capture_measurements(self):
        for name in ('counts', 'volts', 'results', 'candidate', 'runtime_seconds'):
            with self.subTest(name=name):
                self.assertEqual(mapping(name, [12, 13]).classification, 'DIRECT_MEASUREMENT')

    def test_timestamp_tokens_and_camelcase_still_detected(self):
        for name in ('sample_time', 'event_ts', 'sampleTime', 'eventTS', 'observed_at', 'timestamp'):
            with self.subTest(name=name):
                self.assertEqual(mapping(name, [1709280000]).classification, 'COORDINATE')

    def test_mixed_naive_and_aware_timestamps_require_review(self):
        result = mapping('time', ['2026-09-25T12:00:00Z', '2026-09-25T13:00:00'])
        self.assertTrue(result.unresolved)
        self.assertEqual(result.proposed_unit, 'unknown')


if __name__ == '__main__':
    unittest.main()
