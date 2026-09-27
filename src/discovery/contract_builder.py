"""Layer 4: Build a DraftContract from a SourceInventory and variable mappings.

A DraftContract is always created in state 'draft' or 'needs_review' or 'blocked'.
It can never be created in state 'approved' directly — approval requires an
explicit ApprovalRecord passed to apply_approval() in models.py.
"""
from __future__ import annotations

from src.discovery.models import (
    BlockedReason,
    DraftContract,
    SourceInventory,
    VariableMapping,
)


# ---------------------------------------------------------------------------
# Blocking conditions
# ---------------------------------------------------------------------------

def _collect_blocks(
    mappings: list[VariableMapping],
) -> list[BlockedReason]:
    blocks: list[BlockedReason] = []

    # Any measurement with unit == "unknown" blocks approval
    for m in mappings:
        if m.classification in ("DIRECT_MEASUREMENT", "CALIBRATED_MEASUREMENT",
                                "SCIENTIFIC_INTERMEDIATE", "DERIVED_PRODUCT"):
            if m.proposed_unit == "unknown":
                blocks.append(BlockedReason(
                    code="AMBIGUOUS_UNIT",
                    field=m.source_field,
                    detail=(
                        f"Field '{m.source_field}' is a measurement but its unit is unknown. "
                        "Declare units explicitly before approving."
                    ),
                ))

    return blocks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_draft_contract(
    inventory: SourceInventory,
    mappings: list[VariableMapping],
    *,
    source_provider: str | None = None,
    source_documentation: str | None = None,
    source_instrument: str | None = None,
    additional_assumptions: list[str] | None = None,
) -> DraftContract:
    """Produce a DraftContract from an inventory and proposed mappings.

    Parameters
    ----------
    inventory:
        Result of discover_source().
    mappings:
        Result of recognize_science() or recognize_structure().
    source_provider, source_documentation, source_instrument:
        Optional provenance metadata from the caller (never inferred from data).
    additional_assumptions:
        Any additional human-stated assumptions to record.
    """
    blocks = _collect_blocks(mappings)
    all_unresolved: list[str] = []
    for m in mappings:
        all_unresolved.extend(m.unresolved)

    # NO_TIMESTAMP is a question, not a hard block — non-temporal datasets are valid.
    coordinates = [m for m in mappings if m.classification == "COORDINATE"]
    if not coordinates:
        all_unresolved.append(
            "No temporal coordinate field was identified. "
            "Confirm whether this dataset requires a timestamp, and if so which field it is."
        )
    if additional_assumptions is None:
        additional_assumptions = []

    # Build source metadata section
    source_meta: dict = {}
    if source_provider:
        source_meta["provider"] = source_provider
    if source_documentation:
        source_meta["documentation"] = source_documentation
    if source_instrument is not None:
        source_meta["instrument"] = source_instrument
    else:
        source_meta["instrument"] = None
        # An instrument is optional for catalogues, simulations and other sources.
        # Its absence never licenses inference of sensor physics.
    source_meta["connector"] = {
        "format": inventory.connector.format,
        "path": inventory.connector.path,
        "table": inventory.connector.table,
        "sampling_complete": inventory.connector.sampling_complete,
    }

    # Assumptions
    assumptions: list[str] = [
        "Source values are read verbatim; no coercion or unit conversion is applied here.",
        "A passing structural read does not imply scientific validity.",
    ]
    assumptions.extend(additional_assumptions)

    # Review notes
    n_fields = len(mappings)
    n_measure = sum(1 for m in mappings if m.classification == "DIRECT_MEASUREMENT")
    n_unresolved = len(all_unresolved)
    n_blocks = len(blocks)
    notes_lines = [
        f"Source: {inventory.connector.format} at {inventory.connector.path}",
        f"Fields discovered: {n_fields}",
        f"Measurement fields: {n_measure}",
        f"Unresolved questions: {n_unresolved}",
        f"Blocking conditions: {n_blocks}",
    ]
    if inventory.warnings:
        notes_lines.append("Warnings: " + "; ".join(inventory.warnings))

    if blocks:
        state = "blocked"
    elif all_unresolved:
        state = "needs_review"
    else:
        state = "draft"

    return DraftContract(
        state=state,
        inventory=inventory,
        variable_mappings=tuple(mappings),
        assumptions=tuple(assumptions),
        unresolved_questions=tuple(all_unresolved),
        review_notes="\n".join(notes_lines),
        source_metadata_section=source_meta,
        blocked_reasons=tuple(blocks),
    )
