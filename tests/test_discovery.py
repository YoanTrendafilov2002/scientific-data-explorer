"""Tests for the source-neutral discovery and contract planning layer.

Two independent synthetic schemas are used throughout:

Schema A – Water Quality Sensor (CSV + SQLite)
  site_id, sample_time (ISO UTC), ph, do_mg_l, temp_c, qc_flag, instrument_id

Schema B – Particle Counter (JSON + JSONL)
  detector_id, event_ts (Unix epoch → ambiguous timezone), channel_1..4,
  background, run_id

Blocking tests verify that ambiguous units, missing timestamps, and unapproved
contracts prevent workflow planning.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.discovery import (
    ApprovalRecord as ReviewRecord,
    ContractNotApprovedError,
    apply_approval,
    build_draft_contract,
    discover_source,
    plan_workflow,
    recognize_science,
    recognize_structure,
)
from src.discovery.models import BlockedReason, DraftContract, VariableMapping, EvidenceItem
from src.data_reader import ReaderError

ROOT = Path(__file__).resolve().parents[1]

def ApprovalRecord(*args, **kwargs):
    """Explicitly approve fixtures; production defaults remain unresolved."""
    answers = kwargs.get("approved_answers", args[1] if len(args) > 1 else {})
    return ReviewRecord(*args, **kwargs, decision="approve",
                        question_decisions={q: "approve" for q in answers})


# ===========================================================================
# Helper factories
# ===========================================================================

def _wq_csv(path: Path) -> Path:
    """Write Schema A (water quality) as CSV."""
    path.write_text(
        "site_id,sample_time,ph,do_mg_l,temp_c,qc_flag,instrument_id\n"
        "SITE_A,2024-03-01T08:00:00Z,7.4,8.2,14.5,GOOD,WQ-001\n"
        "SITE_A,2024-03-01T09:00:00Z,7.2,8.0,14.8,GOOD,WQ-001\n"
        "SITE_B,2024-03-01T08:00:00Z,6.9,6.5,15.1,SUSPECT,WQ-002\n",
        encoding="utf-8",
    )
    return path


def _wq_sqlite(path: Path) -> Path:
    """Write Schema A as SQLite."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE observations "
        "(site_id TEXT, sample_time TEXT, ph REAL, do_mg_l REAL, "
        " temp_c REAL, qc_flag TEXT, instrument_id TEXT)"
    )
    conn.executemany(
        "INSERT INTO observations VALUES (?,?,?,?,?,?,?)",
        [
            ("SITE_A", "2024-03-01T08:00:00Z", 7.4, 8.2, 14.5, "GOOD", "WQ-001"),
            ("SITE_A", "2024-03-01T09:00:00Z", 7.2, 8.0, 14.8, "GOOD", "WQ-001"),
            ("SITE_B", "2024-03-01T08:00:00Z", 6.9, 6.5, 15.1, "SUSPECT", "WQ-002"),
        ],
    )
    conn.commit()
    conn.close()
    return path


def _particle_json(path: Path) -> Path:
    """Write Schema B (particle counter) as JSON."""
    records = [
        {"detector_id": "DET-01", "event_ts": 1709280000, "channel_1": 42,
         "channel_2": 17, "channel_3": 3, "channel_4": 0, "background": 5, "run_id": "RUN_001"},
        {"detector_id": "DET-01", "event_ts": 1709280060, "channel_1": 38,
         "channel_2": 20, "channel_3": 2, "channel_4": 1, "background": 4, "run_id": "RUN_001"},
    ]
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _particle_jsonl(path: Path) -> Path:
    """Write Schema B as JSONL."""
    records = [
        {"detector_id": "DET-01", "event_ts": 1709280000, "channel_1": 42,
         "channel_2": 17, "channel_3": 3, "channel_4": 0, "background": 5, "run_id": "RUN_001"},
        {"detector_id": "DET-02", "event_ts": 1709280060, "channel_1": 10,
         "channel_2": 5, "channel_3": 1, "channel_4": 0, "background": 2, "run_id": "RUN_001"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _minimal_approved_contract(inventory=None, mappings=None):
    """Build the smallest approvable contract (no unresolved questions, no blocks)."""
    from src.discovery.models import (
        ConnectorInfo, FieldProfile, SourceInventory, VariableMapping, EvidenceItem,
    )
    if inventory is None:
        conn = ConnectorInfo(format="json", path="/fake/path.json",
                             sampling_complete=True)
        fp_ts = FieldProfile("ts", 2, 0, 0, 0, {"str": 2},
                             ("2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z"))
        fp_val = FieldProfile("value", 2, 0, 0, 0, {"float": 2}, (1.0, 2.0))
        inventory = SourceInventory(connector=conn, fields=(fp_ts, fp_val),
                                    schema_metadata={}, source_metadata={},
                                    warnings=())
    if mappings is None:
        ev_ts = EvidenceItem("column_name_pattern", "looks like timestamp", 0.9)
        ev_v = EvidenceItem("observed_type", "numeric float", 0.6)
        m_ts = VariableMapping("ts", "ts", "COORDINATE", "UTC", "L0",
                               (ev_ts,), (), ())
        m_val = VariableMapping("value", "value", "DIRECT_MEASUREMENT", "K", "L0",
                                (ev_v,), (), ())
        mappings = [m_ts, m_val]
    return build_draft_contract(inventory, mappings,
                                source_instrument="test_instrument")


# ===========================================================================
# Layer 1 – Source inventory
# ===========================================================================

class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    # --- Schema A CSV ---
    def test_csv_inventory_field_count(self):
        path = _wq_csv(self.root / "wq.csv")
        inv = discover_source(path)
        self.assertEqual(len(inv.fields), 7)

    def test_csv_inventory_row_count(self):
        path = _wq_csv(self.root / "wq.csv")
        inv = discover_source(path)
        self.assertEqual(inv.connector.row_count_estimate, 3)
        self.assertTrue(inv.connector.sampling_complete)

    def test_csv_field_names_correct(self):
        path = _wq_csv(self.root / "wq.csv")
        inv = discover_source(path)
        names = {fp.name for fp in inv.fields}
        self.assertIn("ph", names)
        self.assertIn("sample_time", names)
        self.assertIn("qc_flag", names)

    def test_csv_format_detected(self):
        path = _wq_csv(self.root / "wq.csv")
        inv = discover_source(path)
        self.assertEqual(inv.connector.format, "csv")

    def test_sampling_limit_marks_incomplete(self):
        path = _wq_csv(self.root / "wq.csv")
        inv = discover_source(path, sampling_limit=1)
        self.assertFalse(inv.connector.sampling_complete)
        self.assertIsNone(inv.connector.row_count_estimate)
        self.assertTrue(any("capped" in w.lower() for w in inv.warnings))

    # --- Schema A SQLite ---
    def test_sqlite_inventory(self):
        path = _wq_sqlite(self.root / "wq.db")
        inv = discover_source(path, format="sqlite", table="observations")
        self.assertEqual(inv.connector.format, "sqlite")
        names = {fp.name for fp in inv.fields}
        self.assertIn("temp_c", names)

    def test_sqlite_declared_types_populated(self):
        path = _wq_sqlite(self.root / "wq.db")
        inv = discover_source(path, format="sqlite", table="observations")
        ph_fp = next(fp for fp in inv.fields if fp.name == "ph")
        self.assertIsNotNone(ph_fp.declared_type)

    def test_sqlite_schema_metadata_has_tables(self):
        path = _wq_sqlite(self.root / "wq.db")
        inv = discover_source(path, format="sqlite", table="observations")
        # schema_metadata["tables"] must list all tables in the database
        self.assertIn("tables", inv.schema_metadata)
        self.assertIn("observations", inv.schema_metadata["tables"])

    # --- Schema B JSON ---
    def test_json_inventory(self):
        path = _particle_json(self.root / "particles.json")
        inv = discover_source(path)
        names = {fp.name for fp in inv.fields}
        self.assertIn("channel_1", names)
        self.assertIn("event_ts", names)

    # --- Schema B JSONL ---
    def test_jsonl_inventory(self):
        path = _particle_jsonl(self.root / "particles.jsonl")
        inv = discover_source(path)
        self.assertEqual(inv.connector.format, "jsonl")
        names = {fp.name for fp in inv.fields}
        self.assertIn("detector_id", names)

    def test_same_schema_different_formats_equivalent_fields(self):
        """JSON and JSONL representations of Schema B produce same field names."""
        json_path = _particle_json(self.root / "p.json")
        jsonl_path = _particle_jsonl(self.root / "p.jsonl")
        inv_json = discover_source(json_path)
        inv_jsonl = discover_source(jsonl_path)
        json_names = {fp.name for fp in inv_json.fields}
        jsonl_names = {fp.name for fp in inv_jsonl.fields}
        # Both must include the same core fields
        for name in ("detector_id", "event_ts", "channel_1", "run_id"):
            self.assertIn(name, json_names)
            self.assertIn(name, jsonl_names)

    def test_unsupported_format_raises_reader_error(self):
        path = self.root / "data.xyz"
        path.write_text("abc", encoding="utf-8")
        with self.assertRaises(ReaderError):
            discover_source(path)

    def test_source_metadata_stored_verbatim(self):
        """Caller-supplied metadata is stored without interpretation."""
        path = _wq_csv(self.root / "wq.csv")
        inv = discover_source(path, source_metadata={"provider": "Test Lab",
                                                       "note": "exec('evil')"})
        self.assertEqual(inv.source_metadata["note"], "exec('evil')")


# ===========================================================================
# Layer 2+3 – Structural and scientific recognition
# ===========================================================================

class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _wq_inventory(self):
        return discover_source(_wq_csv(self.root / "wq.csv"))

    def _particle_inventory(self):
        return discover_source(_particle_json(self.root / "p.json"))

    # --- Schema A structural ---
    def test_wq_sample_time_is_coordinate(self):
        inv = self._wq_inventory()
        mappings = recognize_structure(inv)
        ts = next(m for m in mappings if m.source_field == "sample_time")
        self.assertEqual(ts.classification, "COORDINATE")

    def test_wq_qc_flag_is_quality_control(self):
        inv = self._wq_inventory()
        mappings = recognize_structure(inv)
        qc = next(m for m in mappings if m.source_field == "qc_flag")
        self.assertEqual(qc.classification, "QUALITY_CONTROL")

    def test_wq_site_id_is_metadata(self):
        inv = self._wq_inventory()
        mappings = recognize_structure(inv)
        sid = next(m for m in mappings if m.source_field == "site_id")
        self.assertEqual(sid.classification, "METADATA")

    def test_every_mapping_has_evidence(self):
        inv = self._wq_inventory()
        mappings = recognize_science(inv)
        for m in mappings:
            self.assertTrue(m.evidence, f"No evidence for '{m.source_field}'")
            for e in m.evidence:
                self.assertTrue(e.observation.strip())

    def test_evidence_item_rejects_empty_observation(self):
        with self.assertRaises(ValueError):
            EvidenceItem("col", "", 0.5)

    def test_evidence_item_rejects_out_of_range_confidence(self):
        with self.assertRaises(ValueError):
            EvidenceItem("col", "something", 1.5)

    # --- Schema A scientific ---
    def test_wq_temp_c_gets_degC_unit(self):
        inv = self._wq_inventory()
        mappings = recognize_science(inv)
        temp = next(m for m in mappings if m.source_field == "temp_c")
        self.assertEqual(temp.proposed_unit, "degC")

    def test_wq_temp_c_has_unresolved_unit_question(self):
        """Unit inferred from name alone must generate an unresolved question."""
        inv = self._wq_inventory()
        mappings = recognize_science(inv)
        temp = next(m for m in mappings if m.source_field == "temp_c")
        self.assertTrue(temp.unresolved,
                        "temp_c inferred unit must raise an unresolved question")

    def test_wq_ph_gets_ph_unit(self):
        inv = self._wq_inventory()
        mappings = recognize_science(inv)
        ph = next(m for m in mappings if m.source_field == "ph")
        self.assertEqual(ph.proposed_unit, "pH")

    def test_wq_do_gets_mgl_unit(self):
        inv = self._wq_inventory()
        mappings = recognize_science(inv)
        do_f = next(m for m in mappings if m.source_field == "do_mg_l")
        self.assertEqual(do_f.proposed_unit, "mg/L")

    def test_wq_utc_timestamp_recognized(self):
        """ISO-8601 UTC timestamp should be recognized with utc=UTC unit."""
        inv = self._wq_inventory()
        mappings = recognize_science(inv)
        ts = next(m for m in mappings if m.source_field == "sample_time")
        self.assertEqual(ts.proposed_unit, "UTC")

    # --- Schema B scientific ---
    def test_particle_event_ts_is_coordinate(self):
        inv = self._particle_inventory()
        mappings = recognize_science(inv)
        ts = next(m for m in mappings if m.source_field == "event_ts")
        self.assertEqual(ts.classification, "COORDINATE")

    def test_particle_event_ts_has_unresolved_epoch(self):
        """Unix epoch without timezone confirmation must be flagged as unresolved."""
        inv = self._particle_inventory()
        mappings = recognize_science(inv)
        ts = next(m for m in mappings if m.source_field == "event_ts")
        self.assertTrue(ts.unresolved,
                        "epoch timestamp must raise an unresolved timezone question")

    def test_particle_channels_are_measurements(self):
        inv = self._particle_inventory()
        mappings = recognize_science(inv)
        ch1 = next(m for m in mappings if m.source_field == "channel_1")
        self.assertEqual(ch1.classification, "DIRECT_MEASUREMENT")

    def test_particle_channels_unit_is_count(self):
        inv = self._particle_inventory()
        mappings = recognize_science(inv)
        ch1 = next(m for m in mappings if m.source_field == "channel_1")
        self.assertEqual(ch1.proposed_unit, "count")

    def test_variable_mapping_requires_evidence(self):
        """VariableMapping with no evidence raises ValueError."""
        with self.assertRaises(ValueError):
            VariableMapping("x", "x", "METADATA", "1", "L0", (), (), ())

    def test_sqlite_and_csv_same_schema_same_classification(self):
        """Schema A via CSV and SQLite must yield the same classifications."""
        csv_path = _wq_csv(self.root / "wq.csv")
        db_path = _wq_sqlite(self.root / "wq.db")
        inv_csv = discover_source(csv_path)
        inv_db = discover_source(db_path, format="sqlite", table="observations")
        maps_csv = {m.source_field: m.classification
                    for m in recognize_science(inv_csv)}
        maps_db = {m.source_field: m.classification
                   for m in recognize_science(inv_db)}
        for field in ("site_id", "sample_time", "ph", "qc_flag"):
            with self.subTest(field=field):
                self.assertEqual(maps_csv[field], maps_db[field])


# ===========================================================================
# Layer 4 – Draft contract and blocking conditions
# ===========================================================================

class DraftContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _wq_contract(self):
        inv = discover_source(_wq_csv(self.root / "wq.csv"))
        mappings = recognize_science(inv)
        return build_draft_contract(inv, mappings, source_instrument="WQ sensor")

    def _particle_contract(self):
        inv = discover_source(_particle_json(self.root / "p.json"))
        mappings = recognize_science(inv)
        return build_draft_contract(inv, mappings)

    # --- State invariants ---
    def test_wq_contract_is_not_draft(self):
        """Water quality contract has unresolved questions → needs_review, not draft."""
        c = self._wq_contract()
        self.assertIn(c.state, ("needs_review", "blocked"))

    def test_contract_cannot_be_created_as_approved(self):
        """build_draft_contract must never return state=approved."""
        c = self._wq_contract()
        self.assertNotEqual(c.state, "approved")

    def test_no_timestamp_field_becomes_unresolved_question(self):
        """Fix 3: NO_TIMESTAMP is an unresolved question, not a hard block.
        Non-temporal datasets should be allowed through to review.
        The contract may still be blocked by other conditions (e.g. AMBIGUOUS_UNIT)
        but not because of a missing timestamp alone.
        """
        from src.discovery.models import (
            ConnectorInfo, FieldProfile, SourceInventory, EvidenceItem
        )
        # A source with a known-unit measurement but no timestamp
        conn = ConnectorInfo(format="csv", path="/fake/no_ts.csv",
                             sampling_complete=True)
        ev = EvidenceItem("observed_type", "numeric float", 0.6)
        fp = FieldProfile("particle_count", 3, 0, 0, 0, {"float": 3}, (1.0,))
        inv = SourceInventory(connector=conn, fields=(fp,),
                              schema_metadata={}, source_metadata={}, warnings=())
        mappings = recognize_science(inv)
        contract = build_draft_contract(inv, mappings, source_instrument="test")
        # NO_TIMESTAMP is now an unresolved question, not a block code
        block_codes = {b.code for b in contract.blocked_reasons}
        self.assertNotIn("NO_TIMESTAMP", block_codes)
        # The question about missing timestamp must appear in unresolved_questions
        self.assertTrue(any("timestamp" in q.lower() or "temporal" in q.lower()
                            for q in contract.unresolved_questions))

    def test_unknown_unit_measurement_blocks_contract(self):
        """A measurement field with unknown unit must produce a AMBIGUOUS_UNIT block."""
        from src.discovery.models import (
            ConnectorInfo, FieldProfile, SourceInventory
        )
        # Give it a timestamp so that's not the block
        conn = ConnectorInfo(format="csv", path="/fake/ambig.csv",
                             sampling_complete=True)
        fp_ts = FieldProfile("sample_time", 2, 0, 0, 0, {"str": 2},
                             ("2024-01-01T00:00:00Z",))
        fp_m = FieldProfile("xray_flux", 2, 0, 0, 0, {"float": 2}, (0.5,))
        inv = SourceInventory(connector=conn, fields=(fp_ts, fp_m),
                              schema_metadata={}, source_metadata={}, warnings=())
        mappings = recognize_science(inv)
        contract = build_draft_contract(inv, mappings, source_instrument="test")
        self.assertEqual(contract.state, "blocked")
        codes = {b.code for b in contract.blocked_reasons}
        self.assertIn("AMBIGUOUS_UNIT", codes)

    def test_unresolved_questions_recorded(self):
        c = self._wq_contract()
        self.assertTrue(c.unresolved_questions)

    def test_blocked_reasons_have_detail(self):
        c = self._particle_contract()
        for b in c.blocked_reasons:
            self.assertTrue(b.detail.strip())

    def test_review_notes_are_human_readable(self):
        c = self._wq_contract()
        self.assertIn("Fields discovered", c.review_notes)

    # --- Approval gate ---
    def test_approval_requires_answers_to_all_unresolved(self):
        c = self._wq_contract()
        # Attempt approval with no answers
        if c.state == "blocked":
            self.skipTest("Contract is blocked, not just needs_review")
        record = ApprovalRecord(approver="Dr. Test", approved_answers={})
        with self.assertRaises(ContractNotApprovedError):
            apply_approval(c, record)

    def test_approval_empty_approver_rejected(self):
        with self.assertRaises(ValueError):
            ApprovalRecord(approver="", approved_answers={})

    def test_approval_empty_answer_rejected(self):
        with self.assertRaises(ValueError):
            ApprovalRecord(approver="Dr. Test", approved_answers={"Q": ""})

    def test_approval_blocked_requires_override_note(self):
        c = self._particle_contract()
        if not c.blocked_reasons:
            self.skipTest("Contract not blocked")
        answers = {q: "confirmed" for q in c.unresolved_questions}
        record = ApprovalRecord(approver="Dr. Test", approved_answers=answers)
        with self.assertRaises(ContractNotApprovedError):
            apply_approval(c, record)

    def test_full_approval_path(self):
        """Build an approvable contract and approve it."""
        c = _minimal_approved_contract()
        self.assertIn(c.state, ("draft", "needs_review"))
        answers = {q: "confirmed by test" for q in c.unresolved_questions}
        record = ApprovalRecord(approver="Test Approver", approved_answers=answers)
        approved = apply_approval(c, record)
        self.assertEqual(approved.state, "approved")
        self.assertEqual(approved.unresolved_questions, ())

    # --- Fix 1: rejection detection ---

    def test_rejection_answer_prevents_approval(self):
        """Fix 1: An answer that starts with 'No' must be treated as rejection."""
        c = _minimal_approved_contract()
        from dataclasses import replace
        c = replace(c, state="needs_review", unresolved_questions=("Confirm units",))
        answers = {q: "No. This is unresolved. Do not approve." for q in c.unresolved_questions}
        record = ApprovalRecord(approver="Tester", approved_answers=answers)
        with self.assertRaises(ContractNotApprovedError) as ctx:
            apply_approval(c, record)
        self.assertIn("rejection", str(ctx.exception).lower())

    def test_rejection_variants_blocked(self):
        """Fix 1: Various rejection phrases must all prevent approval."""
        from src.discovery.models import _answer_is_rejection
        for phrase in ["No", "no", "NO.", "Reject this", "rejected",
                       "unresolved", "Unknown", "Cannot confirm",
                       "do not approve", "disagree"]:
            with self.subTest(phrase=phrase):
                self.assertTrue(_answer_is_rejection(phrase),
                                f"Expected '{phrase}' to be a rejection")

    def test_affirmative_answers_not_rejected(self):
        """Fix 1: Legitimate affirmative answers must not be flagged as rejections."""
        from src.discovery.models import _answer_is_rejection
        for phrase in ["Confirmed: values are in °C", "Yes, this is UTC",
                       "Arithmetic mean", "GOOD and SUSPECT only",
                       "Nominal voltage 12V", "3.14"]:
            with self.subTest(phrase=phrase):
                self.assertFalse(_answer_is_rejection(phrase),
                                 f"Expected '{phrase}' to be affirmative")

    def test_approval_records_evidence_in_notes(self):
        """Fix 1: Approval notes must contain the actual answers as audit evidence."""
        c = _minimal_approved_contract()
        answers = {q: "Confirmed: test answer" for q in c.unresolved_questions}
        approved = apply_approval(c, ApprovalRecord("Auditor", answers))
        self.assertIn("Approved by: Auditor", approved.review_notes)
        if answers:
            self.assertIn("Approval evidence", approved.review_notes)

    def test_draft_state_contract_can_be_approved(self):
        """Fix 5 (backend): A clean draft with no unresolved questions can be approved."""
        from src.discovery.models import (
            ConnectorInfo, FieldProfile, SourceInventory, EvidenceItem
        )
        conn = ConnectorInfo(format="json", path="/fake/clean.json",
                             sampling_complete=True)
        fp_ts = FieldProfile("ts", 2, 0, 0, 0, {"str": 2},
                             ("2024-01-01T00:00:00Z",))
        fp_v = FieldProfile("value", 2, 0, 0, 0, {"float": 2}, (1.0,))
        inv = SourceInventory(connector=conn, fields=(fp_ts, fp_v),
                              schema_metadata={}, source_metadata={}, warnings=())
        ev = EvidenceItem("col", "test evidence", 0.9)
        m_ts = VariableMapping("ts", "ts", "COORDINATE", "UTC", "L0", (ev,), (), ())
        m_v = VariableMapping("value", "value", "DIRECT_MEASUREMENT", "K", "L0",
                              (ev,), (), ())
        contract = build_draft_contract(inv, [m_ts, m_v], source_instrument="test_device")
        # Instrument is provided so no instrument unresolved question
        # Any remaining unresolved questions come from unit inference
        answers = {q: "confirmed" for q in contract.unresolved_questions}
        approved = apply_approval(contract, ApprovalRecord("Tester", answers))
        self.assertEqual(approved.state, "approved")


# ===========================================================================
# Layer 5 – Workflow planning
# ===========================================================================

class WorkflowPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _approved_contract(self):
        c = _minimal_approved_contract()
        answers = {q: "confirmed" for q in c.unresolved_questions}
        record = ApprovalRecord(approver="Test", approved_answers=answers)
        return apply_approval(c, record)

    def test_unapproved_contract_raises(self):
        """Workflow planning must raise ContractNotApprovedError unless approved."""
        c = _minimal_approved_contract()
        self.assertNotEqual(c.state, "approved")
        with self.assertRaises(ContractNotApprovedError):
            plan_workflow(c, "Compute daily mean")

    def test_approved_contract_produces_plan(self):
        c = self._approved_contract()
        plan = plan_workflow(c, "Create a daily summary of valid observations")
        self.assertEqual(plan.contract_state, "approved")
        # Steps are always present for a recognised outcome
        self.assertTrue(plan.steps)
        # Without step_confirmations, the plan is blocked by unconfirmed decisions
        # (Fix 2 — this is expected and correct)
        # To get an unblocked plan, all step required_approvals must be confirmed.

    def test_plan_always_has_read_step(self):
        c = self._approved_contract()
        plan = plan_workflow(c, "Read source data")
        step_names = [s.name for s in plan.steps]
        self.assertIn("read_and_validate_source", step_names)

    def test_aggregate_outcome_produces_aggregation_step(self):
        c = self._approved_contract()
        plan = plan_workflow(c, "Create a daily mean of measurements")
        step_names = [s.name for s in plan.steps]
        self.assertIn("temporal_aggregation", step_names)

    def test_qc_outcome_produces_qc_step(self):
        """An outcome mentioning 'valid' should produce a QC step when QC fields exist."""
        from src.discovery.models import (
            ConnectorInfo, FieldProfile, SourceInventory, VariableMapping, EvidenceItem
        )
        conn = ConnectorInfo(format="csv", path="/fake/qc.csv", sampling_complete=True)
        fp_ts = FieldProfile("ts", 2, 0, 0, 0, {"str": 2}, ("2024-01-01T00:00:00Z",))
        fp_v = FieldProfile("value", 2, 0, 0, 0, {"float": 2}, (1.0,))
        fp_qc = FieldProfile("qc_flag", 2, 0, 0, 0, {"str": 2}, ("GOOD",))
        inv = SourceInventory(connector=conn, fields=(fp_ts, fp_v, fp_qc),
                              schema_metadata={}, source_metadata={}, warnings=())
        ev = EvidenceItem("col", "test evidence", 0.9)
        m_ts = VariableMapping("ts", "ts", "COORDINATE", "UTC", "L0", (ev,), (), ())
        m_v = VariableMapping("value", "value", "DIRECT_MEASUREMENT", "K", "L0", (ev,), (), ())
        m_qc = VariableMapping("qc_flag", "qc_flag", "QUALITY_CONTROL", "1", "L0", (ev,), (), ())
        c = build_draft_contract(inv, [m_ts, m_v, m_qc], source_instrument="test")
        answers = {q: "confirmed" for q in c.unresolved_questions}
        c_approved = apply_approval(c, ApprovalRecord("Test", answers))
        plan = plan_workflow(c_approved, "daily mean of valid observations")
        step_names = [s.name for s in plan.steps]
        self.assertIn("apply_qc_filter", step_names)

    def test_draft_contract_workflow_returns_blocked_plan(self):
        """Workflow plan requested for a non-approved contract must be blocked."""
        c = _minimal_approved_contract()
        self.assertIn(c.state, ("draft", "needs_review"))
        with self.assertRaises(ContractNotApprovedError):
            plan_workflow(c, "anything")

    def test_ambiguous_unit_prevents_approval_and_workflow(self):
        """End-to-end: ambiguous unit blocks contract → workflow cannot be planned."""
        from src.discovery.models import (
            ConnectorInfo, FieldProfile, SourceInventory
        )
        conn = ConnectorInfo(format="csv", path="/fake/a.csv", sampling_complete=True)
        fp_ts = FieldProfile("sample_time", 2, 0, 0, 0, {"str": 2},
                             ("2024-01-01T00:00:00Z",))
        fp_m = FieldProfile("xray_flux", 2, 0, 0, 0, {"float": 2}, (0.5,))
        inv = SourceInventory(connector=conn, fields=(fp_ts, fp_m),
                              schema_metadata={}, source_metadata={}, warnings=())
        mappings = recognize_science(inv)
        contract = build_draft_contract(inv, mappings, source_instrument="test")
        self.assertEqual(contract.state, "blocked")
        with self.assertRaises(ContractNotApprovedError):
            plan_workflow(contract, "daily mean")

    def test_no_workflow_generated_until_approved(self):
        """
        Simulate the full path: schema B particle counter.
        Epoch timestamp → unresolved timezone → blocked.
        Workflow cannot be planned.
        """
        path = _particle_json(self.root / "particles.json")
        inv = discover_source(path)
        mappings = recognize_science(inv)
        contract = build_draft_contract(inv, mappings)
        self.assertNotEqual(contract.state, "approved")
        with self.assertRaises(ContractNotApprovedError):
            plan_workflow(contract, "sum channel counts per run")

    # --- Fix 2: step decisions separate from contract approval ---

    def test_approved_plan_without_step_confirmations_is_blocked(self):
        """Fix 2: An approved contract with an outcome produces a plan blocked by
        unconfirmed step decisions, not by contract state."""
        c = self._approved_contract()
        # Aggregate outcome triggers temporal_aggregation step with required_approvals
        plan = plan_workflow(c, "Create a daily mean of measurements")
        # Steps are present
        self.assertTrue(plan.steps)
        # But the plan is blocked because step decisions are unconfirmed
        self.assertTrue(plan.blocked_reasons,
                        "Plan should be blocked when step decisions are unconfirmed")
        # At least one blocked reason should mention the step name
        step_names = [s.name for s in plan.steps]
        self.assertTrue(
            any(any(sn in br for sn in step_names) for br in plan.blocked_reasons),
            "Blocked reasons should reference unconfirmed step decisions"
        )

    def test_step_confirmations_unlock_plan(self):
        """Fix 2: Providing step confirmations removes the blocked_reasons."""
        c = self._approved_contract()
        plan = plan_workflow(c, "Create a daily mean of measurements")
        # Collect all required_approvals from all steps
        all_reqs = {}
        for step in plan.steps:
            for req in step.required_approvals:
                all_reqs[req] = {"decision": "approve", "note": "Confirmed: arithmetic mean over calendar day"}
        # Now re-plan with confirmations
        plan2 = plan_workflow(c, "Create a daily mean of measurements",
                              step_confirmations=all_reqs)
        self.assertEqual(plan2.blocked_reasons, (),
                         f"Plan should not be blocked after confirmations: {plan2.blocked_reasons}")

    def test_rejection_in_step_confirmation_keeps_plan_blocked(self):
        """Fix 2: A rejection answer in step_confirmations must keep the plan blocked."""
        c = self._approved_contract()
        plan = plan_workflow(c, "Create a daily mean of measurements")
        all_reqs = {}
        for step in plan.steps:
            for req in step.required_approvals:
                all_reqs[req] = {"decision": "reject", "note": "No, this is not confirmed."}
        plan2 = plan_workflow(c, "Create a daily mean of measurements",
                              step_confirmations=all_reqs)
        self.assertTrue(plan2.blocked_reasons,
                        "Rejection answers should keep the plan blocked")


# ===========================================================================
# CLI integration
# ===========================================================================

class DiscoveryCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _run(self, *args, expect_exit=None):
        cmd = [sys.executable, str(ROOT / "scripts/discover.py"), *args]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        if expect_exit is not None:
            self.assertEqual(result.returncode, expect_exit,
                             f"stderr: {result.stderr}\nstdout: {result.stdout[:500]}")
        return result

    def test_csv_produces_needs_review_exit_2(self):
        path = _wq_csv(self.root / "wq.csv")
        result = self._run(str(path), expect_exit=2)
        data = json.loads(result.stdout)
        self.assertIn("contract", data)
        self.assertNotEqual(data["contract"]["state"], "approved")

    def test_unsupported_format_exits_1(self):
        path = self.root / "data.xyz"
        path.write_text("x")
        self._run(str(path), expect_exit=1)

    def test_inventory_only_flag(self):
        path = _wq_csv(self.root / "wq.csv")
        result = self._run(str(path), "--inventory-only", expect_exit=0)
        data = json.loads(result.stdout)
        self.assertIn("fields", data)
        self.assertNotIn("contract", data)

    def test_outcome_without_approval_returns_blocked_plan(self):
        path = _wq_csv(self.root / "wq.csv")
        result = self._run(str(path), "--outcome", "daily mean", expect_exit=2)
        data = json.loads(result.stdout)
        self.assertIn("workflow_plan", data)
        plan = data["workflow_plan"]
        self.assertTrue(plan["blocked_reasons"])

    def test_json_source_produces_contract(self):
        path = _particle_json(self.root / "p.json")
        result = self._run(str(path), expect_exit=2)
        data = json.loads(result.stdout)
        self.assertIn("contract", data)

    def test_noaa_real_extract(self):
        """NOAA real extract produces a contract (not a read error)."""
        result = self._run(
            str(ROOT / "examples/noaa_lga_20240101.json"),
            "--format", "noaa-global-hourly",
            expect_exit=2,
        )
        data = json.loads(result.stdout)
        self.assertIn("contract", data)
        self.assertEqual(data["contract"]["contract_state"]
                         if "contract_state" in data["contract"]
                         else data["contract"]["state"],
                         data["contract"].get("state", "needs_review"))


# ===========================================================================
# Model invariants
# ===========================================================================

class ModelInvariantTests(unittest.TestCase):
    def test_draft_contract_is_frozen(self):
        c = _minimal_approved_contract()
        # Normal attribute assignment must raise FrozenInstanceError (subclass of AttributeError)
        with self.assertRaises(AttributeError):
            c.state = "approved"  # type: ignore[misc]

    def test_apply_approval_returns_new_instance(self):
        c = _minimal_approved_contract()
        answers = {q: "ok" for q in c.unresolved_questions}
        rec = ApprovalRecord("Test", answers)
        c2 = apply_approval(c, rec)
        self.assertIsNot(c, c2)
        self.assertEqual(c2.state, "approved")

    def test_blocked_reason_has_code_and_detail(self):
        b = BlockedReason("TEST_CODE", "field_x", "Something is wrong")
        self.assertEqual(b.code, "TEST_CODE")
        self.assertTrue(b.detail)


if __name__ == "__main__":
    unittest.main()
