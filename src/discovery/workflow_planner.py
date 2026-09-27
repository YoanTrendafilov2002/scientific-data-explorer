"""Layer 5: Workflow planning.

A workflow plan can only be generated from an approved DraftContract.
Attempting to plan from an unapproved contract raises ContractNotApprovedError.

The planner does NOT generate executable code in this iteration.
It produces a WorkflowPlan describing the proposed steps, required information,
and any remaining blockers. Code generation is a future layer.

Confirming a step's required_approvals is a separate act from approving the
source contract.  Until every step's required_approvals are explicitly confirmed
via step_confirmations, those steps appear in missing_information and the plan's
blocked_reasons will be non-empty.
"""
from __future__ import annotations
import re

from src.discovery.models import (
    ContractNotApprovedError,
    DraftContract,
    VariableMapping,
    WorkflowPlan,
    WorkflowStep,
)


def plan_workflow(
    contract: DraftContract,
    outcome_description: str,
    step_confirmations: dict[str, dict[str, str]] | None = None,
) -> WorkflowPlan:
    """Produce a WorkflowPlan for the stated outcome.

    Parameters
    ----------
    contract:
        Must have state == "approved".  All other states raise
        ContractNotApprovedError.
    outcome_description:
        Free-text description of what the user wants to compute.
        This is the ONLY source of intent; it is not interpreted from data.
    step_confirmations:
        Optional dict mapping each step required_approval string to a
        non-empty affirmative answer.  Until all required_approvals for a
        step are confirmed here, that step surfaces in missing_information
        and the plan's blocked_reasons will be non-empty.
        Example: {"Aggregation method (mean/sum/other) confirmed": "arithmetic mean"}

    Returns
    -------
    WorkflowPlan
        blocked_reasons is non-empty when any step's required_approvals are
        not yet confirmed.
    """
    if contract.state != "approved":
        raise ContractNotApprovedError(
            f"Cannot plan a workflow: contract state is '{contract.state}'. "
            "Resolve all unresolved questions and obtain an ApprovalRecord first."
        )

    blocked: list[str] = []
    missing: list[str] = []
    warnings: list[str] = []
    steps: list[WorkflowStep] = []

    mappings = contract.variable_mappings
    coordinates = [m for m in mappings if m.classification == "COORDINATE"]
    measurements = [m for m in mappings if m.classification in (
        "DIRECT_MEASUREMENT", "CALIBRATED_MEASUREMENT")]
    qc_fields = [m for m in mappings if m.classification == "QUALITY_CONTROL"]

    outcome_lower = outcome_description.lower()
    wants_temporal = bool(re.search(r"\b(daily|hourly|monthly|yearly|weekly|time[- ]based)\b", outcome_lower))
    wants_agg = bool(re.search(r"\b(daily|hourly|monthly|mean|average|summary|aggregate|total|sum)\b", outcome_lower))
    wants_export = bool(re.search(r"\b(export|copy)\b", outcome_lower))
    unchanged = bool(re.search(r"\b(unchanged|verbatim|without filtering|do not filter)\b", outcome_lower))
    if unchanged:
        wants_agg = False
        wants_temporal = False
    # Only temporal workflows need a temporal coordinate.
    if wants_temporal and not coordinates:
        blocked.append(
            "No temporal coordinate identified; cannot plan a time-based workflow."
        )

    # Check for unknown units (should not happen post-approval, but defensive)
    unknown_unit_fields = [m for m in measurements if m.proposed_unit == "unknown"]
    if unknown_unit_fields and wants_agg:
        blocked.append(
            f"Fields with unknown units remain: "
            f"{[m.source_field for m in unknown_unit_fields]}"
        )

    if blocked:
        return WorkflowPlan(
            outcome_description=outcome_description,
            contract_state=contract.state,
            steps=(),
            blocked_reasons=tuple(blocked),
            missing_information=tuple(missing),
            warnings=tuple(warnings),
        )

    # --- Propose workflow steps based on what is available ---
    outcome_lower = outcome_description.lower()

    step_counter = [0]

    def next_id() -> str:
        step_counter[0] += 1
        return f"S{step_counter[0]:03d}"

    # Step: read and validate source
    steps.append(WorkflowStep(
        step_id=next_id(),
        name="read_and_validate_source",
        description=(
            "Read all records using the identified connector. "
            "Verify required fields are present and non-null where mandatory."
        ),
        inputs=tuple(m.source_field for m in mappings),
        outputs=("validated_records",),
        required_approvals=("Source format and connector confirmed",),
        implementation_note=(
            f"Use DataReader with format='{contract.inventory.connector.format}'"
        ),
    ))

    # Step: apply QC filter if QC fields exist and outcome mentions valid/quality
    wants_qc = any(kw in outcome_lower for kw in
                   ("valid", "quality", "good", "approved", "qc", "flag"))
    wants_qc = wants_qc and not unchanged
    if wants_qc:
        qc_names = tuple(m.source_field for m in qc_fields)
        if qc_fields:
            steps.append(WorkflowStep(
                step_id=next_id(),
                name="apply_qc_filter",
                description=(
                    "Retain only records whose QC field values are in the "
                    "approved-for-publication vocabulary. "
                    "Allowed values must be declared in the contract, not inferred."
                ),
                inputs=("validated_records",) + qc_names,
                outputs=("qc_passed_records",),
                required_approvals=(
                    "QC vocabulary and publication eligibility criteria confirmed",
                ),
                implementation_note=(
                    "Filter requires explicit list of accepted QC values from approver."
                ),
            ))
        else:
            missing.append(
                "Outcome requests quality filtering but no QC field was identified. "
                "Declare the QC field name and vocabulary."
            )

    # Step: aggregate / summarise if outcome mentions summary/daily/mean/aggregate
    if wants_agg and measurements:
        coord_names = tuple(m.source_field for m in coordinates)
        meas_names = tuple(m.source_field for m in measurements)
        steps.append(WorkflowStep(
            step_id=next_id(),
            name="temporal_aggregation" if wants_temporal else "aggregate_records",
            description=(
                "Group records using explicitly reviewed grouping keys and compute the "
                "requested aggregate (mean, sum, count, etc.). "
                "Aggregation method and period must be confirmed; "
                "equal weighting is not assumed."
            ),
            inputs=("qc_passed_records" if wants_qc and qc_fields else "validated_records",)
                   + (coord_names if wants_temporal else ()) + meas_names,
            outputs=("aggregated_product",),
            required_approvals=(
                "Aggregation method (mean/sum/other) confirmed",
                "Aggregation period (daily/hourly/other) confirmed" if wants_temporal else "Grouping keys (or all records) confirmed",
                "Equal sample weighting confirmed or alternative stated",
            ),
            implementation_note=(
                "Aggregation period, method, and weighting require explicit "
                "confirmation before this step can be implemented."
            ),
        ))
    elif wants_agg and not measurements:
        missing.append(
            "Outcome requests aggregation but no measurement fields were identified."
        )

    if wants_export:
        steps.append(WorkflowStep(
            step_id=next_id(), name="export_records",
            description="Export the selected records without implicit unit conversion or quality filtering.",
            inputs=("aggregated_product" if wants_agg and measurements else
                    "qc_passed_records" if wants_qc and qc_fields else "validated_records",),
            outputs=("exported_records",),
            required_approvals=("Output format, destination and overwrite policy confirmed",),
            implementation_note="Planning only: no destination is written by discovery.",
        ))
    if len(steps) == 1 and not wants_qc and not wants_agg:
        warnings.append(
            "Outcome description did not match any recognized workflow pattern. "
            "Only a read-and-validate step was planned."
        )

    if missing:
        warnings.append(
            "Some requested steps could not be fully planned; "
            "see missing_information for details."
        )

    # Check that every step's required_approvals have been explicitly confirmed.
    # A required_approval that is present but answered with a rejection phrase
    # also counts as unconfirmed.
    from src.discovery.models import _answer_is_rejection  # avoid circular at module level
    confirmations = step_confirmations or {}
    unconfirmed_step_decisions: list[str] = []
    for step in steps:
        for req in step.required_approvals:
            confirmation = confirmations.get(req, {})
            valid = isinstance(confirmation, dict)
            answer = confirmation.get("note", "") if valid else ""
            if (not valid or confirmation.get("decision") != "approve"
                    or not isinstance(answer, str) or not answer.strip() or _answer_is_rejection(answer)):
                unconfirmed_step_decisions.append(
                    f"Step '{step.name}' requires confirmation: {req}"
                )

    plan_blocked: list[str] = list(blocked) + list(missing)
    if unconfirmed_step_decisions:
        plan_blocked.extend(unconfirmed_step_decisions)
        missing.extend(unconfirmed_step_decisions)

    return WorkflowPlan(
        outcome_description=outcome_description,
        contract_state=contract.state,
        steps=tuple(steps),
        blocked_reasons=tuple(plan_blocked),
        missing_information=tuple(missing),
        warnings=tuple(warnings),
    )
