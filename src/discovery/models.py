"""Frozen dataclasses for every discovery artefact.

Design rules
------------
* All models are frozen (immutable after construction).
* ApprovalState is the only gate between discovery and execution.
* EvidenceItem requires non-empty evidence text; a mapping without
  evidence cannot be constructed.
* Source values are never interpreted as instructions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace, asdict
from datetime import datetime, timezone
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

ApprovalState = Literal["draft", "needs_review", "approved", "blocked"]


class ContractNotApprovedError(RuntimeError):
    """Raised when workflow planning is attempted before contract approval."""


# ---------------------------------------------------------------------------
# Layer 1 – Source inventory
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConnectorInfo:
    """Which connector was used and what it can read."""
    format: str                          # e.g. "csv", "json", "sqlite"
    path: str
    table: str | None = None             # for SQLite
    records_key: str | None = None       # for JSON envelopes
    row_count_estimate: int | None = None
    sampling_limit: int | None = None    # None = full scan
    sampling_complete: bool = True


@dataclass(frozen=True)
class FieldProfile:
    """Observed statistics for one field across sampled records."""
    name: str
    present_count: int
    absent_count: int
    null_count: int
    blank_count: int
    observed_types: dict[str, int]       # Python type name → count
    examples: tuple[Any, ...]            # up to 3 representative values
    declared_type: str | None = None     # from schema if available


@dataclass(frozen=True)
class SourceInventory:
    """Full layer-1 result: everything observable without interpretation."""
    connector: ConnectorInfo
    fields: tuple[FieldProfile, ...]
    schema_metadata: dict[str, Any]      # pragma tables, JSON keys, CSV headers
    source_metadata: dict[str, Any]      # caller-supplied metadata (never executed)
    warnings: tuple[str, ...]            # e.g. sampling limits reached


# ---------------------------------------------------------------------------
# Layer 2 + 3 – Structural and scientific recognition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceItem:
    """One piece of evidence supporting a scientific inference."""
    source: str           # "column_name", "example_values", "declared_metadata", …
    observation: str      # what was observed
    confidence: float     # 0.0–1.0

    def __post_init__(self) -> None:
        if not self.observation.strip():
            raise ValueError("EvidenceItem.observation must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


@dataclass(frozen=True)
class VariableMapping:
    """Proposed scientific interpretation of one source field."""
    source_field: str
    proposed_name: str
    classification: str              # COORDINATE | METADATA | DIRECT_MEASUREMENT | …
    proposed_unit: str               # "unknown" when genuinely uncertain
    processing_level: str            # L0 | L1 | L2 | L3
    evidence: tuple[EvidenceItem, ...]
    unresolved: tuple[str, ...]      # questions that must be answered before approval
    dependencies: tuple[str, ...]    # other source_field names this depends on

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError(
                f"VariableMapping for '{self.source_field}' has no evidence; "
                "every proposed mapping must cite at least one observation."
            )


# ---------------------------------------------------------------------------
# Layer 4 – Draft contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DraftContract:
    """Machine-readable draft Scientific Contract.

    state transitions:
      draft        → needs_review  (when unresolved questions exist)
      needs_review → approved      (only via ApprovalRecord with explicit answers)
      any          → blocked       (when a blocking condition is detected)
      blocked      → needs_review  (after the block is resolved externally)
    """
    state: ApprovalState
    inventory: SourceInventory
    variable_mappings: tuple[VariableMapping, ...]
    assumptions: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    review_notes: str                         # human-readable summary
    source_metadata_section: dict[str, Any]   # provider, documentation, instrument info
    blocked_reasons: tuple[BlockedReason, ...]
    approval_evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_approvable(self) -> bool:
        return (
            self.state in ("draft", "needs_review")
            and not self.blocked_reasons
            and not self.unresolved_questions
        )


@dataclass(frozen=True)
class BlockedReason:
    code: str     # e.g. "NO_TIMESTAMP", "AMBIGUOUS_UNIT", "MISSING_METADATA"
    field: str | None
    detail: str


# Words at the start of an answer that signal rejection rather than confirmation.
# Any answer beginning with one of these (case-insensitive) is treated as a rejection.
_REJECTION_PREFIXES = (
    "no", "nope", "reject", "rejected", "refuse", "refused",
    "not approved", "unresolved", "unknown", "cannot", "can't",
    "do not approve", "don't approve", "disagree",
)


def _answer_is_rejection(answer: str) -> bool:
    """Return True when the answer text signals that the question is NOT resolved."""
    a = answer.strip().lower()
    return any(phrase in a for phrase in ("cannot confirm", "do not approve", "don't approve", "not approved")) or any(a == prefix or a.startswith(prefix + " ") or a.startswith(prefix + ".")
               or a.startswith(prefix + ",") or a.startswith(prefix + ";")
               for prefix in _REJECTION_PREFIXES)


@dataclass(frozen=True)
class ApprovalRecord:
    """Records an explicit human confirmation of a contract.

    approved_answers must map every unresolved_question key to a non-empty,
    non-rejecting answer.  Answers that begin with rejection phrases (e.g.
    "No", "Reject", "Unresolved") are treated as rejections and prevent
    approval.  This is the only path to ApprovalState == "approved".
    """
    approver: str                           # free-text name/role
    approved_answers: dict[str, str]        # question → affirmative answer
    override_note: str = ""                 # required if overriding a blocked state
    decision: str = field(default="request_changes", kw_only=True)
    question_decisions: dict[str, str] = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        if self.decision not in ("approve", "reject", "request_changes"):
            raise ValueError("Invalid review decision")
        if not self.approver.strip():
            raise ValueError("ApprovalRecord.approver must not be empty")
        for q, a in self.approved_answers.items():
            if not isinstance(q, str) or not isinstance(a, str):
                raise ValueError("Review questions and notes must be strings")
            if self.decision == "approve" and not a.strip():
                raise ValueError(f"Answer to '{q}' must not be empty")


def apply_approval(contract: DraftContract, record: ApprovalRecord) -> DraftContract:
    """Return a new DraftContract with state=approved if all conditions are met.

    Raises ContractNotApprovedError when:
    - any blocking reason exists without an explicit override_note, OR
    - any unresolved question has no answer, OR
    - any answer begins with a rejection phrase (e.g. "No", "Unresolved").
    """
    if record.decision != "approve":
        return replace(contract, state="blocked" if contract.blocked_reasons else "needs_review",
                       approval_evidence={**asdict(record), "reviewed_at": datetime.now(timezone.utc).isoformat()})
    if contract.blocked_reasons:
        raise ContractNotApprovedError(
            "Contract has blocking conditions; correct the source metadata before approval."
        )
    if any(record.question_decisions.get(q) != "approve" for q in contract.unresolved_questions):
        raise ContractNotApprovedError("Every unresolved question requires an explicit approve decision; rejection or requested changes remain unresolved.")
    unanswered = [q for q in contract.unresolved_questions
                  if q not in record.approved_answers]
    if unanswered:
        raise ContractNotApprovedError(
            f"Unresolved questions must be answered before approval: {unanswered}"
        )
    # Detect rejection phrases — submitting "No. Do not approve." is not approval.
    rejected = [
        q for q, a in record.approved_answers.items()
        if _answer_is_rejection(a)
    ]
    if rejected:
        raise ContractNotApprovedError(
            f"The following questions were answered with a rejection and remain "
            f"unresolved; the contract cannot be approved: {rejected}"
        )
    # Record answers as audit evidence in review_notes
    evidence_lines = [f"  [{q}]: {a}" for q, a in record.approved_answers.items()]
    evidence_block = "\n".join(evidence_lines)
    new_notes = (
        contract.review_notes
        + f"\nApproved by: {record.approver}"
        + f"\nApproval evidence:\n{evidence_block}"
    )
    return DraftContract(
        state="approved",
        inventory=contract.inventory,
        variable_mappings=tuple(replace(m, unresolved=()) for m in contract.variable_mappings),
        assumptions=contract.assumptions,
        unresolved_questions=(),
        review_notes=new_notes,
        source_metadata_section=contract.source_metadata_section,
        blocked_reasons=(),
        approval_evidence={**asdict(record), "reviewed_at": datetime.now(timezone.utc).isoformat()},
    )


# ---------------------------------------------------------------------------
# Layer 5 – Workflow plan
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    name: str
    description: str
    inputs: tuple[str, ...]        # variable names (proposed_name)
    outputs: tuple[str, ...]
    required_approvals: tuple[str, ...]  # which assumptions must be confirmed
    implementation_note: str


@dataclass(frozen=True)
class WorkflowPlan:
    """Proposed workflow; steps are empty when the plan is blocked."""
    outcome_description: str
    contract_state: ApprovalState
    steps: tuple[WorkflowStep, ...]
    blocked_reasons: tuple[str, ...]
    missing_information: tuple[str, ...]
    warnings: tuple[str, ...]
