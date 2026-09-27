"""End-to-end handler regression tests; no scientific approval or files persisted."""
import unittest
from dataclasses import replace
from unittest.mock import patch

from scripts.ui_server import _handle_discover
from src.discovery import ApprovalRecord, apply_approval, plan_workflow


class ReviewAPITests(unittest.TestCase):
    def setUp(self):
        self.body = {"path": "examples/reader_data.json", "outcome": "daily summary of valid observations"}
        status, response = _handle_discover(self.body)
        self.assertEqual(status, 200)
        self.questions = response["contract"]["unresolved_questions"]

    def review(self, **overrides):
        body = dict(self.body, approver="AUTOMATED TEST ONLY", decision="approve",
                    answers={q: "Confirmed for test fixture" for q in self.questions},
                    question_decisions={q: "approve" for q in self.questions})
        body.update(overrides)
        return _handle_discover(body)

    def test_notes_without_explicit_decision_never_approve(self):
        body = dict(self.body, approver="TEST", answers={q: "yes" for q in self.questions})
        status, response = _handle_discover(body)
        self.assertEqual(status, 400)
        self.assertNotEqual(response["contract"]["state"], "approved")

    def test_indirect_rejection_never_approves(self):
        status, response = self.review(answers={q: "I cannot confirm this; do not approve." for q in self.questions})
        self.assertEqual(status, 422)
        self.assertNotEqual(response["contract"]["state"], "approved")

    def test_per_question_explicit_decision_required(self):
        status, _ = self.review(question_decisions={})
        self.assertEqual(status, 422)

    def test_reject_and_request_changes_preserve_questions(self):
        for decision in ("reject", "request_changes"):
            status, response = self.review(decision=decision, answers={q: "" for q in self.questions})
            self.assertEqual(status, 200)
            self.assertEqual(response["contract"]["state"], "needs_review")
            self.assertEqual(response["contract"]["unresolved_questions"], self.questions)
            self.assertEqual(response["contract"]["approval_evidence"]["decision"], decision)

    def test_full_evidence_and_mapping_resolution(self):
        note = "Evidence " + "x" * 400
        status, response = self.review(answers={q: note for q in self.questions})
        self.assertEqual(status, 200)
        contract = response["contract"]
        self.assertEqual(contract["state"], "approved")
        self.assertTrue(all(not m["unresolved"] for m in contract["variable_mappings"]))
        self.assertEqual(contract["approval_evidence"]["approved_answers"][self.questions[0]], note)
        self.assertTrue(response["workflow_plan"]["blocked_reasons"])

    def test_step_notes_do_not_unlock_but_structured_decisions_do(self):
        _, response = self.review()
        requirements = [r for s in response["workflow_plan"]["steps"] for r in s["required_approvals"]]
        _, legacy = self.review(step_confirmations={r: "yes" for r in requirements})
        self.assertTrue(legacy["workflow_plan"]["blocked_reasons"])
        _, approved = self.review(step_confirmations={r: {"decision": "approve", "note": "Test fixture choice"} for r in requirements})
        self.assertEqual(approved["workflow_plan"]["blocked_reasons"], [])

    def test_clean_draft_approval_through_handler(self):
        from src.discovery import discover_source, recognize_science, build_draft_contract
        inventory = discover_source("examples/reader_data.json")
        draft = build_draft_contract(inventory, recognize_science(inventory))
        clean = replace(draft, state="draft", unresolved_questions=(), blocked_reasons=())
        with patch("scripts.ui_server.build_draft_contract", return_value=clean):
            status, response = self.review(answers={}, question_decisions={})
        self.assertEqual(status, 200)
        self.assertEqual(response["contract"]["state"], "approved")

    def test_non_temporal_export_and_temporal_requirement(self):
        from src.discovery import discover_source, recognize_science, build_draft_contract
        inv = discover_source("examples/reader_data.json")
        mappings = [m for m in recognize_science(inv) if m.classification != "COORDINATE"]
        draft = build_draft_contract(inv, mappings)
        approved = apply_approval(draft, ApprovalRecord("TEST", {q: "Confirmed" for q in draft.unresolved_questions},
            decision="approve", question_decisions={q: "approve" for q in draft.unresolved_questions}))
        export = plan_workflow(approved, "Export all records unchanged")
        self.assertEqual([s.name for s in export.steps], ["read_and_validate_source", "export_records"])
        confirmations = {r: {"decision": "approve", "note": "Test"} for s in export.steps for r in s.required_approvals}
        self.assertFalse(plan_workflow(approved, "Export all records unchanged", confirmations).blocked_reasons)
        self.assertTrue(plan_workflow(approved, "daily mean").blocked_reasons)

    def test_unit_correction_changes_mapping_not_source_values(self):
        status, response = _handle_discover(dict(self.body, unit_overrides={
            "temperature": {"unit": "degF", "evidence": "Test-only provider declaration"}}))
        self.assertEqual(status, 200)
        mapping = next(m for m in response["contract"]["variable_mappings"] if m["source_field"] == "temperature")
        self.assertEqual(mapping["proposed_unit"], "degF")
        self.assertTrue(mapping["unresolved"])
        self.assertNotEqual(response["contract"]["state"], "approved")

    def test_invalid_body_is_client_error(self):
        for body in ([], {"path": 123}, dict(self.body, answers=[])):
            self.assertEqual(_handle_discover(body)[0], 400)


if __name__ == "__main__":
    unittest.main()
