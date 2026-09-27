"""Execution safety and numeric regressions using temporary local datasets."""
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import ui_server as api
from src.discovery.execution import calculate, ExecutionError, source_hash


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "data.json"
        self.rows = [
            {"site": "A", "time": "2026-09-25T12:00:00Z", "temperature": 20, "quality": "GOOD"},
            {"site": "A", "time": "2026-09-25T13:00:00Z", "temperature": 24, "quality": "GOOD"},
            {"site": "A", "time": "2026-09-25T14:00:00Z", "temperature": 100, "quality": "BAD"},
            {"site": "B", "time": "2026-09-26T00:30:00+02:00", "temperature": 10, "quality": "GOOD"},
        ]
        self.save()
        self.addCleanup(patch.stopall)
        patch.object(api, "ROOT", self.root).start()
        patch.object(api, "PREPARED", {}).start()
        self.settings = {"qc_field": "quality", "accepted_qc": ["GOOD"], "value_field": "temperature",
                         "group_by": ["site"], "method": "mean", "weighting": "equal",
                         "missing_values": "reject", "timestamp_field": "time", "period": "daily"}

    def save(self):
        self.source.write_text(json.dumps(self.rows), encoding="utf-8")

    def reviewed(self, outcome="daily summary of valid observations"):
        request = {"path": "data.json", "outcome": outcome}
        status, response = api._handle_discover(request)
        self.assertEqual(status, 200, response)
        questions = response["contract"]["unresolved_questions"]
        request.update(approver="TEST ONLY", decision="approve", source_revision=response["source_revision"],
                       answers={q: "Confirmed for synthetic fixture" for q in questions},
                       question_decisions={q: "approve" for q in questions})
        _, response = api._handle_discover(request)
        request["step_confirmations"] = {r: {"decision": "approve", "note": "Test fixture settings"}
            for s in response["workflow_plan"]["steps"] for r in s["required_approvals"]}
        return request

    def prepare(self, settings=None, request=None):
        return api._prepare_execution(dict(request or self.reviewed(), settings=settings or self.settings))

    def test_daily_mean_qc_timezone_and_publication(self):
        original = self.source.read_bytes()
        status, preview = self.prepare()
        self.assertEqual(status, 200, preview)
        self.assertFalse((self.root / "workflow_runs").exists())
        self.assertEqual(preview["counts"], {"source_rows": 4, "qc_excluded": 1, "missing_measurements_dropped": 0, "output_rows": 2})
        self.assertEqual(preview["preview"][0]["value"], 22)
        self.assertEqual(preview["preview"][0]["sample_count"], 2)
        self.assertEqual(preview["preview"][1]["period_start_utc"], "2026-09-25T00:00:00+00:00")
        status, run = api._execute({"execution_ticket": preview["execution_ticket"], "decision": "approve", "approved_by": "TEST"})
        self.assertEqual(status, 200, run)
        folder = self.root / "workflow_runs" / run["run_id"]
        self.assertEqual(json.loads((folder / "result.json").read_text())[0]["unit"], "degC")
        provenance = json.loads((folder / "provenance.json").read_text())
        self.assertEqual(provenance["settings"], self.settings)
        self.assertEqual(provenance["source_sha256"], source_hash(self.source))
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(api._execute({"execution_ticket": preview["execution_ticket"], "decision": "approve", "approved_by": "TEST"})[0], 409)

    def test_changed_source_after_review_or_preview_blocks(self):
        request = self.reviewed()
        self.rows[0]["temperature"] = 999
        self.save()
        self.assertEqual(self.prepare(request=request)[0], 409)
        _, preview = self.prepare()
        self.rows[0]["temperature"] = 1000
        self.save()
        self.assertEqual(api._execute({"execution_ticket": preview["execution_ticket"], "decision": "approve", "approved_by": "TEST"})[0], 409)
        self.assertFalse((self.root / "workflow_runs").exists())

    def test_unapproved_or_unconfirmed_cannot_prepare(self):
        request = self.reviewed()
        request["decision"] = "reject"
        self.assertEqual(self.prepare(request=request)[0], 422)
        request = self.reviewed()
        request["step_confirmations"] = {}
        self.assertEqual(self.prepare(request=request)[0], 422)

    def test_no_implicit_qc_for_unchanged_export(self):
        for row in self.rows:
            del row["time"]
        self.save()
        status, response = api._prepare_execution(dict(self.reviewed("Export all records unchanged"), settings={}))
        self.assertEqual(status, 200, response)
        self.assertEqual(response["preview"], self.rows)
        self.assertEqual(response["counts"]["qc_excluded"], 0)

    def test_missing_values_policy_is_explicit(self):
        self.rows[0]["temperature"] = None
        self.save()
        self.assertEqual(self.prepare()[0], 422)
        status, response = self.prepare(settings=dict(self.settings, missing_values="drop"))
        self.assertEqual(status, 200, response)
        self.assertEqual(response["counts"]["missing_measurements_dropped"], 1)
        self.assertEqual(response["preview"][0]["value"], 24)

    def test_invalid_settings_and_rejected_codes(self):
        for change in ({"accepted_qc": ["SUSPECT"]}, {"accepted_qc": ["BAD"]},
                       {"weighting": "invented"}, {"group_by": ["absent"]},
                       {"method": "eval"}, {"period": "weekly"}, {"timestamp_field": "site"},
                       {"output_path": "../../overwrite.json"}):
            with self.subTest(change=change):
                self.assertEqual(self.prepare(settings=dict(self.settings, **change))[0], 422)

    def test_naive_time_and_invalid_numeric_rejected(self):
        self.rows[0]["time"] = "2026-09-25T12:00:00"
        self.save()
        self.assertEqual(self.prepare()[0], 422)
        self.rows[0]["time"] += "Z"
        self.rows[0]["temperature"] = "NaN"
        self.save()
        self.assertEqual(self.prepare()[0], 422)

    def test_partial_scan_cannot_execute(self):
        request = dict(self.reviewed(), sampling_limit=1)
        self.assertEqual(self.prepare(request=request)[0], 422)

    def test_expired_and_unapproved_execution(self):
        _, response = self.prepare()
        ticket = response["execution_ticket"]
        self.assertEqual(api._execute({"execution_ticket": ticket, "decision": "reject", "approved_by": "TEST"})[0], 400)
        api.PREPARED[ticket]["created"] = time.monotonic() - 601
        self.assertEqual(api._execute({"execution_ticket": ticket, "decision": "approve", "approved_by": "TEST"})[0], 409)

    def test_zero_rows_no_publication(self):
        status, _ = self.prepare(settings=dict(self.settings, accepted_qc=["NOT_PRESENT"]))
        self.assertEqual(status, 422)
        self.assertFalse((self.root / "workflow_runs").exists())


if __name__ == "__main__":
    unittest.main()
