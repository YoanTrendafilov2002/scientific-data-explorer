"""Source-neutral scientific discovery and contract planning layer.

Layer 1 – Source discovery    (inventory.py)
Layer 2 – Structural recognition (recognition.py)
Layer 3 – Scientific recognition  (recognition.py)
Layer 4 – Contract review         (contract_builder.py)
Layer 5 – Workflow planning        (workflow_planner.py)

No layer automatically promotes a draft to approved. Explicit user confirmation
via an ApprovalRecord is required before workflow planning can produce executable steps.
"""
from src.discovery.models import (
    ApprovalRecord,
    ApprovalState,
    BlockedReason,
    ConnectorInfo,
    ContractNotApprovedError,
    DraftContract,
    EvidenceItem,
    FieldProfile,
    SourceInventory,
    VariableMapping,
    WorkflowPlan,
    WorkflowStep,
    apply_approval,
)
from src.discovery.inventory import discover_source
from src.discovery.recognition import recognize_structure, recognize_science
from src.discovery.contract_builder import build_draft_contract
from src.discovery.workflow_planner import plan_workflow

__all__ = [
    "ApprovalRecord",
    "ApprovalState",
    "BlockedReason",
    "ConnectorInfo",
    "ContractNotApprovedError",
    "DraftContract",
    "EvidenceItem",
    "FieldProfile",
    "SourceInventory",
    "VariableMapping",
    "WorkflowPlan",
    "WorkflowStep",
    "apply_approval",
    "discover_source",
    "recognize_structure",
    "recognize_science",
    "build_draft_contract",
    "plan_workflow",
]
