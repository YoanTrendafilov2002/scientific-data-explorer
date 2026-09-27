"""Layers 2 and 3: Structural and scientific recognition.

All rules are deterministic pattern-matching; no LLM involvement.
LLM-assisted recognition would be added behind the RecognitionBackend
interface (not implemented here) and must never bypass the approval gate.

Rules applied in order:
  1. Identify timestamp candidates (ISO-8601, UTC indicators, 'time'/'date'/'ts'
     in column name).
  2. Identify identifier / key candidates.
  3. Identify QC flag candidates.
  4. Identify numeric measurement candidates.
  5. Classify everything else as metadata or unknown.

Scientific recognition:
  - Every mapping cites the evidence that drove it.
  - unit is "unknown" when no pattern matches.
  - unresolved questions are raised for: unknown units on measurement fields,
    ambiguous timestamps (non-UTC), no timestamp found, unknown instrument.
"""
from __future__ import annotations

import re
from typing import Any

from src.discovery.models import (
    EvidenceItem,
    FieldProfile,
    SourceInventory,
    VariableMapping,
)


# ---------------------------------------------------------------------------
# Regex patterns (deterministic; no values are executed)
# ---------------------------------------------------------------------------

_ISO_TS_PAT = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?",
)
_UTC_INDICATOR = re.compile(r"Z$|[+-]\d{2}:\d{2}$|\+00:00$|UTC", re.IGNORECASE)
_EPOCH_PAT = re.compile(r"^\d{9,13}$")  # Unix seconds or ms

# Field name fragments → candidate roles
_NAME_TS = re.compile(r"(?:^|[^a-z0-9])(?:time|date|ts|timestamp|observed|datetime)(?:$|[^a-z0-9])", re.IGNORECASE)
_NAME_ID = re.compile(r"_id$|^id$|^station|^site|^sensor|^device|^detector|^instrument|^run_id", re.IGNORECASE)
# Case-sensitive boundary avoids treating fluid/lipid/acid as identifiers.
_CAMEL_ID = re.compile(r"[a-z0-9](?:Id|ID)$")


def _timestamp_name(name: str) -> bool:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return bool(_NAME_TS.search(separated))


_NAME_QC = re.compile(r"^qc|_qc$|flag|quality|status", re.IGNORECASE)
_NAME_UNIT_DEGC = re.compile(r"temp|temperature", re.IGNORECASE)
_NAME_UNIT_K = re.compile(r"kelvin|_k$", re.IGNORECASE)
_NAME_UNIT_HPA = re.compile(r"pressure|slp|mslp|hpa|barom", re.IGNORECASE)
_NAME_UNIT_PERCENT = re.compile(r"relative_humid|rh$|humidity", re.IGNORECASE)
_NAME_UNIT_MGL = re.compile(r"^do_|dissolved", re.IGNORECASE)
_NAME_UNIT_PH = re.compile(r"^ph$|^ph_", re.IGNORECASE)
_NAME_COUNT = re.compile(r"count|channel|channel_\d+|^n_|^num_|^cnt", re.IGNORECASE)

_KNOWN_QC_VOCAB = {"GOOD", "SUSPECT", "BAD", "PASS", "FAIL", "OK", "0", "1", "2", "3",
                   "4", "5", "6", "7", "8", "9", "A", "C", "I", "M", "P", "R", "U"}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def recognize_structure(inventory: SourceInventory) -> list[VariableMapping]:
    """Layer 2: Identify structural roles (timestamps, keys, measurements, QC)."""
    return _map_fields(inventory.fields, scientific=False)


def recognize_science(inventory: SourceInventory) -> list[VariableMapping]:
    """Layer 3: Add scientific classifications, units, and evidence."""
    return _map_fields(inventory.fields, scientific=True)


# ---------------------------------------------------------------------------
# Core mapping logic
# ---------------------------------------------------------------------------

def _map_fields(fields: tuple[FieldProfile, ...], *, scientific: bool) -> list[VariableMapping]:
    mappings = []
    for fp in fields:
        mapping = _map_one(fp, scientific=scientific)
        mappings.append(mapping)
    return mappings


def _dominant_type(fp: FieldProfile) -> str:
    """Return the most common observed Python type name, or 'unknown'."""
    if not fp.observed_types:
        return "unknown"
    return max(fp.observed_types, key=fp.observed_types.__getitem__)


def _sample_values(fp: FieldProfile) -> list[str]:
    """Return example values as raw strings (stripped of repr quotes)."""
    result = []
    for ex in fp.examples:
        s = str(ex)
        # Strip leading/trailing repr quotes if present
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            s = s[1:-1]
        result.append(s)
    return result


def _looks_numeric(dom_type: str, samples: list[str]) -> bool:
    """Return True when a string-typed field has samples that parse as numbers.

    CSV readers always yield str; this lets us detect numeric fields even when
    the Python type is 'str'.
    """
    if dom_type != "str" or not samples:
        return False
    parsed = 0
    for s in samples:
        try:
            float(s)
            parsed += 1
        except (ValueError, TypeError):
            pass
    return parsed == len(samples) and len(samples) > 0


def _map_one(fp: FieldProfile, *, scientific: bool) -> VariableMapping:
    name = fp.name
    dom_type = _dominant_type(fp)
    samples = _sample_values(fp)

    evidence: list[EvidenceItem] = []
    unresolved: list[str] = []
    classification = "METADATA"
    proposed_unit = "1"
    processing_level = "L0"
    dependencies: list[str] = []

    # --- Timestamp detection ---
    is_ts, ts_utc, ts_epoch = _detect_timestamp(name, dom_type, samples)
    if is_ts:
        classification = "COORDINATE"
        proposed_unit = "UTC" if ts_utc else "unknown"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' matches timestamp name pattern",
            confidence=0.7,
        ))
        if samples:
            evidence.append(EvidenceItem(
                source="example_values",
                observation=f"Example values look like timestamps: {samples[:2]}",
                confidence=0.85 if ts_utc else 0.5,
            ))
        if not ts_utc:
            if ts_epoch:
                unresolved.append(
                    f"Field '{name}': epoch integer detected; timezone and epoch origin "
                    "(Unix seconds vs. milliseconds) are unconfirmed."
                )
            else:
                unresolved.append(
                    f"Field '{name}': timestamp lacks explicit UTC indicator; "
                    "confirm time zone before use."
                )

    # --- Identifier / key detection ---
    elif _NAME_ID.search(name) or _CAMEL_ID.search(name):
        classification = "METADATA"
        proposed_unit = "1"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' matches identifier naming convention",
            confidence=0.75,
        ))

    # --- QC flag detection ---
    elif _NAME_QC.search(name):
        classification = "QUALITY_CONTROL"
        proposed_unit = "1"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' matches QC/flag naming convention",
            confidence=0.8,
        ))
        if samples and scientific:
            observed_vocab = set(samples)
            known = observed_vocab & _KNOWN_QC_VOCAB
            unknown = observed_vocab - _KNOWN_QC_VOCAB
            if known:
                evidence.append(EvidenceItem(
                    source="example_values",
                    observation=f"Observed QC values include recognized codes: {sorted(known)}",
                    confidence=0.9,
                ))
            if unknown:
                unresolved.append(
                    f"Field '{name}': unknown QC vocabulary {sorted(unknown)}; "
                    "confirm allowed codes and their meanings."
                )

    # --- Numeric measurement detection ---
    # Covers native int/float and string fields whose samples parse as numbers (CSV always yields str)
    elif dom_type in ("float", "int") or _looks_numeric(dom_type, samples):
        classification, proposed_unit, processing_level, extra_evidence, extra_unresolved = (
            _classify_measurement(name, dom_type, samples, scientific=scientific)
        )
        evidence.extend(extra_evidence)
        unresolved.extend(extra_unresolved)
        if not evidence:
            evidence.append(EvidenceItem(
                source="observed_type",
                observation=f"Field '{name}' has dominant type '{dom_type}'",
                confidence=0.5,
            ))

    # --- String / other ---
    else:
        classification = "METADATA"
        proposed_unit = "1"
        evidence.append(EvidenceItem(
            source="observed_type",
            observation=f"Field '{name}' has dominant type '{dom_type}'; treated as metadata",
            confidence=0.4,
        ))

    if not evidence:
        evidence.append(EvidenceItem(
            source="fallback",
            observation=f"Field '{name}' could not be automatically classified",
            confidence=0.1,
        ))

    return VariableMapping(
        source_field=name,
        proposed_name=name,
        classification=classification,
        proposed_unit=proposed_unit,
        processing_level=processing_level,
        evidence=tuple(evidence),
        unresolved=tuple(unresolved),
        dependencies=tuple(dependencies),
    )


def _detect_timestamp(
    name: str, dom_type: str, samples: list[str]
) -> tuple[bool, bool, bool]:
    """Return (is_timestamp, is_utc, is_epoch)."""
    if not _timestamp_name(name):
        # Check samples directly even if name doesn't match
        iso_in_samples = any(_ISO_TS_PAT.match(s) for s in samples if s)
        if not iso_in_samples:
            return False, False, False

    if dom_type in ("int", "float"):
        epoch_in_samples = any(_EPOCH_PAT.match(s) for s in samples if s)
        return True, False, epoch_in_samples

    if dom_type == "str" or not dom_type:
        iso_in_samples = any(_ISO_TS_PAT.match(s) for s in samples if s)
        utc_in_samples = bool(samples) and all(_UTC_INDICATOR.search(s) for s in samples)
        if iso_in_samples or _timestamp_name(name):
            return True, utc_in_samples, False
    return False, False, False


def _classify_measurement(
    name: str, dom_type: str, samples: list[str], *, scientific: bool
) -> tuple[str, str, str, list[EvidenceItem], list[str]]:
    """Return (classification, unit, processing_level, evidence_items, unresolved)."""
    evidence: list[EvidenceItem] = []
    unresolved: list[str] = []
    classification = "DIRECT_MEASUREMENT"
    processing_level = "L0"
    proposed_unit = "unknown"

    evidence.append(EvidenceItem(
        source="observed_type",
        observation=f"Field '{name}' has dominant numeric type '{dom_type}'",
        confidence=0.6,
    ))

    # Try name-based unit assignment
    if _NAME_UNIT_DEGC.search(name):
        proposed_unit = "degC"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' suggests temperature in °C",
            confidence=0.65,
        ))
        unresolved.append(
            f"Field '{name}': unit 'degC' inferred from name only; "
            "confirm that values are degrees Celsius and not Kelvin or Fahrenheit."
        )
    elif _NAME_UNIT_K.search(name):
        proposed_unit = "K"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' suggests temperature in Kelvin",
            confidence=0.65,
        ))
        unresolved.append(
            f"Field '{name}': unit 'K' inferred from name; confirm."
        )
    elif _NAME_UNIT_HPA.search(name):
        proposed_unit = "hPa"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' suggests pressure in hPa",
            confidence=0.65,
        ))
        unresolved.append(
            f"Field '{name}': unit 'hPa' inferred from name; confirm."
        )
    elif _NAME_UNIT_PERCENT.search(name):
        proposed_unit = "%"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' suggests relative humidity (%)",
            confidence=0.65,
        ))
        unresolved.append(
            f"Field '{name}': unit '%' inferred from name; confirm."
        )
    elif _NAME_UNIT_MGL.search(name):
        proposed_unit = "mg/L"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' suggests dissolved oxygen (mg/L)",
            confidence=0.65,
        ))
        unresolved.append(
            f"Field '{name}': unit 'mg/L' inferred from name; confirm."
        )
    elif _NAME_UNIT_PH.search(name):
        proposed_unit = "pH"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' matches pH naming convention",
            confidence=0.70,
        ))
        unresolved.append(
            f"Field '{name}': unit 'pH' inferred from name; confirm scale (0–14 dimensionless)."
        )
    elif _NAME_COUNT.search(name):
        proposed_unit = "count"
        classification = "DIRECT_MEASUREMENT"
        evidence.append(EvidenceItem(
            source="column_name_pattern",
            observation=f"Name '{name}' matches count/channel naming convention",
            confidence=0.6,
        ))
        unresolved.append(
            f"Field '{name}': unit 'count' inferred; confirm what is being counted "
            "and whether a rate or normalization applies."
        )
    else:
        # Genuinely unknown unit
        unresolved.append(
            f"Field '{name}': numeric measurement with unknown unit; "
            "unit must be declared before this contract can be approved."
        )

    return classification, proposed_unit, processing_level, evidence, unresolved
