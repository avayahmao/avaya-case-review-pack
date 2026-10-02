#!/usr/bin/env python3
"""Deterministic presentation routing and rendering for case reviews."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


class PresentationError(ValueError):
    """Raised when structured review data cannot be rendered safely."""


PROOF_STATES = {
    "OBSERVED",
    "CONFIRMED MECHANISM",
    "SUSPECTED",
    "CONTRADICTED",
    "NOT TESTED",
    "PRODUCTION DEPLOYED",
    "OUTCOME CONFIRMED",
    "NOT OBSERVED",
    "NOT COLLECTED",
    "NOT APPLICABLE",
    "UNKNOWN",
}
TECHNICAL_FIELDS = (
    ("scope", "Scope"),
    ("environment", "Environment"),
    ("symptom", "Symptom"),
    ("trigger_conditions", "Trigger / conditions"),
    ("observed_signals", "Observed signals"),
    ("confirmed_mechanism", "Confirmed mechanism"),
    ("suspected_or_unproven", "Suspected or unproven"),
    ("ruled_out", "Ruled out"),
    ("change_or_mitigation", "Change / mitigation"),
    ("verification", "Verification"),
    ("production_outcome", "Production outcome"),
    ("evidence_gaps", "Evidence gaps"),
)
STANDARD_TECHNICAL_FIELDS = (
    ("scope", "Scope"),
    ("symptom", "Symptom"),
    ("confirmed_mechanism", "Confirmed mechanism"),
    ("suspected_or_unproven", "Suspected or unproven"),
    ("verification", "Verification"),
    ("evidence_gaps", "Evidence gaps"),
)
VISUAL_STATE_CLASSES = {
    "OBSERVED": "observed",
    "BLOCKER": "blocker",
    "SUSPECTED": "hypothesis",
    "CONFIRMED MECHANISM": "confirmed",
    "PRODUCTION DEPLOYED": "mitigation",
    "OUTCOME CONFIRMED": "confirmed",
    "PENDING": "pending",
    "UNKNOWN": "pending",
}
CURRENT_PRESENTATION_FIELDS = (
    "official_status",
    "rca_state",
    "mitigation_state",
    "primary_problem",
    "confirmed_finding",
    "unproven_or_contradicted",
    "production_outcome",
    "current_blocker",
    "next_action",
    "next_action_owner",
    "next_due",
)
TECHNICAL_ADVICE_FIELDS = {
    "immediate_diagnostics": ("action", "basis"),
    "potential_solutions": ("action", "condition", "basis"),
    "long_term_steps": ("action", "basis"),
}
PROBLEM_LINEAGE_FIELDS = (
    "original_objective",
    "intended_action",
    "blocker",
    "working_hypotheses",
    "corrected_finding",
    "implemented_action",
    "outcome",
    "secondary_problems",
)


def describe_presentation_schema() -> dict[str, Any]:
    """Return the complete agent-facing presentation contract."""

    return {
        "required_when_full_review_markdown_absent": [
            "technical_spec",
            "problem_lineage",
            "technical_advice",
            "milestones",
            "timeline",
            "evidence_register",
            "visual_context",
        ],
        "technical_spec": {
            "required_fields": [key for key, _label in TECHNICAL_FIELDS],
            "item_fields": ["state", "value", "evidence"],
            "states": sorted(PROOF_STATES),
        },
        "problem_lineage": {
            "fields": list(PROBLEM_LINEAGE_FIELDS),
            "list_fields": ["working_hypotheses", "secondary_problems"],
        },
        "technical_advice": {
            "item_lists": {
                key: {
                    "item_fields": list(fields),
                    "empty_list": "render an explicit unknown evidence gap",
                }
                for key, fields in TECHNICAL_ADVICE_FIELDS.items()
            },
            "boundary": (
                "all items are recommendations, separate from the evidence-stated "
                "Action Plan in current.next_action; potential solutions are "
                "conditional, never confirmed or implemented facts"
            ),
        },
        "milestones": {
            "item_fields": ["date", "change"],
            "optional_fields": ["label", "evidence"],
            "maximum_rendered_in_standard": 5,
        },
        "timeline": {
            "item_fields": ["date", "by", "source", "change"],
            "optional_fields": ["evidence"],
        },
        "evidence_register": {
            "minimum_items": 1,
            "item_fields": ["ref", "date", "source", "evidence", "supports"],
        },
        "visual_context": {
            "selection_priority": [
                "recurrences",
                "hypotheses",
                "components_and_handoffs",
                "transitions",
                "ownership_stall",
            ],
            "variants": {
                "recurrences": {
                    "minimum_items": 2,
                    "item_fields": ["date", "symptom", "change", "outcome"],
                    "optional_fields": ["evidence"],
                },
                "hypotheses": {
                    "minimum_items": 2,
                    "item_fields": ["claim", "state", "evidence", "validation"],
                    "states": sorted(PROOF_STATES),
                },
                "components_and_handoffs": {
                    "minimum_components": 3,
                    "component_fields": ["name", "finding", "state"],
                    "handoff_fields": ["from", "to", "label"],
                },
                "transitions": {
                    "minimum_items_for_secondary_visual": 3,
                    "item_fields": ["label", "state"],
                    "optional_fields": ["date", "detail", "evidence"],
                    "states": sorted(VISUAL_STATE_CLASSES),
                },
                "ownership_stall": {
                    "requires_flag": True,
                    "item_fields": ["owner", "action", "deadline", "status"],
                },
            },
        },
        "or": "a non-empty full_review_markdown string",
    }


def _inline(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


_ISO_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])")


def _date_sort_key(value: Any) -> datetime | None:
    """Return a comparable UTC date for normalized ISO values only."""

    text = _inline(value)
    if not _ISO_DATE_PREFIX.match(text):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _chronological_items(items: list[Any]) -> list[Any]:
    """Sort dated presentation rows oldest-first and keep undated rows last."""

    prepared = []
    for index, item in enumerate(items):
        date_key = _date_sort_key(item.get("date")) if isinstance(item, dict) else None
        prepared.append((index, item, date_key))
    return [
        item
        for _index, item, date_key in sorted(
            prepared,
            key=lambda row: (
                row[2] is None,
                row[2] or datetime.max.replace(tzinfo=timezone.utc),
                row[0],
            ),
        )
    ]


def _cell(value: Any) -> str:
    return _inline(value).replace("|", "\\|")


def _truncate(value: Any, limit: int) -> str:
    text = _inline(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _has_material_delta(delta: dict[str, Any] | None) -> bool:
    if not isinstance(delta, dict):
        return False
    return any(
        bool(delta.get(key))
        for key in ("state_changes", "ownership_changes", "new_evidence")
    )


def select_mode(
    request_text: str,
    review_count: int,
    delta: dict[str, Any] | None = None,
) -> str:
    request = request_text.casefold()
    full_markers = (
        "full review",
        "full report",
        "完整报告",
        "完整 review",
        "evidence register",
    )
    technical_markers = (
        "dry technical",
        "technical spec",
        "technical specification",
        "技术规格",
        "技术评审",
    )
    flow_markers = (
        "flow chart",
        "flowchart",
        "investigation progress",
        "流程图",
        "调查进展图",
    )
    compact_markers = (
        "compact review",
        "compact case card",
        "brief review",
        "精简评审",
        "简要评审",
    )
    standard_markers = (
        "standard review",
        "standard case review",
        "标准评审",
    )
    if any(marker in request for marker in full_markers):
        return "full"
    if any(marker in request for marker in technical_markers):
        return "technical"
    if any(marker in request for marker in flow_markers):
        return "flow"
    if any(marker in request for marker in standard_markers):
        return "standard"
    if any(marker in request for marker in compact_markers):
        return "compact"
    if review_count > 1:
        return "follow-up" if _has_material_delta(delta) else "standard"
    return "standard"


def render_executive_summary(snapshot: dict[str, Any]) -> str:
    """Open every successful view with the same short management summary."""

    current = snapshot["current"]
    return "\n".join(
        [
            f"# Case Review - {snapshot['case_id']}",
            "",
            "## Executive Summary",
            "",
            (
                f"**Status:** {_inline(current['official_status'])}. "
                f"**Reported issue:** {_truncate(current['primary_problem'], 180)}  "
            ),
            f"**Impact:** {_inline(current.get('impact') or 'unknown')}  ",
            f"**Critical finding:** {_inline(current['confirmed_finding'])}  ",
            f"**Production outcome:** {_inline(current['production_outcome'])}",
        ]
    )


def _technical_advice_items(
    snapshot: dict[str, Any], key: str
) -> list[dict[str, str]]:
    """Validate authored advice while allowing older saved snapshots to render."""

    advice = snapshot.get("technical_advice", {})
    if not isinstance(advice, dict):
        raise PresentationError("technical_advice must be an object")
    if "technical_advice" in snapshot and key not in advice:
        raise PresentationError(f"technical_advice.{key} is required")
    raw = advice.get(key, [])
    if not isinstance(raw, list):
        raise PresentationError(f"technical_advice.{key} must be a list")
    required = TECHNICAL_ADVICE_FIELDS[key]
    items: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PresentationError(
                f"technical_advice.{key}[{index}] must be an object"
            )
        normalized: dict[str, str] = {}
        for field in required:
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise PresentationError(
                    f"technical_advice.{key}[{index}].{field} must be non-empty"
                )
            normalized[field] = _inline(value)
        items.append(normalized)
    return items


def render_action_plan(snapshot: dict[str, Any]) -> str:
    """Show only the next checkpoint recorded in the case evidence."""

    current = snapshot["current"]
    return "\n".join(
        [
            "### Action Plan",
            "",
            f"- **Required Action / Next Step:** {_inline(current['next_action'])}",
            (
                f"- **Owner / Due:** {_inline(current['next_action_owner'])} / "
                f"{_inline(current['next_due'])}"
            ),
        ]
    )


def render_technical_advice(snapshot: dict[str, Any]) -> str:
    """Keep proposed technical work separate from recorded case commitments."""

    diagnostics = _technical_advice_items(snapshot, "immediate_diagnostics")
    solutions = _technical_advice_items(snapshot, "potential_solutions")
    long_term = _technical_advice_items(snapshot, "long_term_steps")
    lines = [
        "## Technical Advice",
        "",
        "These are proposed steps based on the available evidence; they are not completed work or recorded commitments.",
        "",
        "### Immediate diagnostic steps",
        "",
    ]
    if diagnostics:
        lines.extend(
            f"- **Recommended diagnostic:** {item['action']} **Basis:** {item['basis']}"
            for item in diagnostics
        )
    else:
        lines.append("- unknown — no additional case-specific diagnostic step is supported yet.")
    lines.extend(["", "### Potential solutions (conditional)", ""])
    if solutions:
        lines.extend(
            f"- If {item['condition'].rstrip('.')}, consider this solution: "
            f"{item['action'].rstrip('.')}. **Basis:** {item['basis']}"
            for item in solutions
        )
    else:
        lines.append("- unknown — no case-specific solution is supported yet.")
    lines.extend(["", "### Long-term next steps", ""])
    if long_term:
        lines.extend(
            f"- **Recommended follow-up:** {item['action']} **Basis:** {item['basis']}"
            for item in long_term
        )
    else:
        lines.append("- unknown — no long-term case-specific action is supported yet.")
    return "\n".join(lines)


def render_case_card(
    snapshot: dict[str, Any], record_path: str, heading: str = "## Case Card"
) -> str:
    current = snapshot["current"]
    lines = [
        heading,
        "",
        (
            f"**Status:** {_inline(current['official_status'])} | "
            f"**RCA:** {_inline(current['rca_state'])} | "
            f"**Mitigation:** {_inline(current['mitigation_state'])}"
        ),
        "",
        f"- **Reported Problem / Symptom:** {_inline(current['primary_problem'])}",
        (
            "- **Current State:** "
            f"{_inline(current.get('current_progress') or 'unknown')}"
        ),
        f"- **Confirmed finding:** {_inline(current['confirmed_finding'])}",
        (
            "- **Unproven or contradicted:** "
            f"{_inline(current['unproven_or_contradicted'])}"
        ),
        f"- **Production outcome:** {_inline(current['production_outcome'])}",
        f"- **Current blocker:** {_inline(current['current_blocker'])}",
        f"- **Record:** [record.md]({record_path})",
        "",
        render_action_plan(snapshot),
    ]
    return "\n".join(lines)


def _changed_field_summary(delta: dict[str, Any]) -> str:
    labels: list[str] = []
    for key in ("state_changes", "ownership_changes"):
        for item in delta.get(key, []):
            label = _inline(item).split(":", 1)[0].strip().replace("_", " ")
            if label and label not in labels:
                labels.append(label)
    if not labels:
        return "No material state or ownership change."
    visible = labels[:6]
    summary = ", ".join(visible)
    if len(labels) > len(visible):
        summary += f", +{len(labels) - len(visible)} more"
    return summary + " updated."


def _new_evidence_items(delta: dict[str, Any]) -> list[str]:
    return [_inline(item) for item in delta.get("new_evidence", []) if _inline(item)]


def render_follow_up(
    snapshot: dict[str, Any], delta: dict[str, Any], record_path: str
) -> str:
    current = snapshot["current"]
    changed = _changed_field_summary(delta)
    new_evidence = _new_evidence_items(delta)
    unchanged_items = delta.get("unchanged_blockers", [])
    unchanged = (
        _truncate("; ".join(_inline(item) for item in unchanged_items), 220)
        if unchanged_items
        else "None."
    )
    lines = [
        f"# Case Follow-up - {snapshot['case_id']}",
        "",
        f"- **Changed since last review:** {changed}",
    ]
    if new_evidence:
        lines.append("- **New decisive evidence:**")
        lines.extend(f"  - {item}" for item in new_evidence[:3])
        if len(new_evidence) > 3:
            lines.append(f"  - +{len(new_evidence) - 3} more in the record")
    else:
        lines.append("- **New decisive evidence:** None.")
    lines.extend(
        [
            f"- **Unchanged blocker:** {unchanged}",
            f"- **Primary problem:** {_truncate(current['primary_problem'], 280)}",
            (
                f"- **Current state:** Status {_inline(current['official_status'])}; "
                f"RCA {_inline(current['rca_state'])}; "
                f"Mitigation {_inline(current['mitigation_state'])}."
            ),
            f"- **Confirmed:** {_truncate(current['confirmed_finding'], 280)}",
            f"- **Production outcome:** {_truncate(current['production_outcome'], 240)}",
            f"- **Current blocker:** {_truncate(current['current_blocker'], 240)}",
            f"- **Next checkpoint:** {_truncate(current['next_action'], 260)}",
            f"- **Next owner:** {_truncate(current['next_action_owner'], 180)}",
            f"- **Due / ETA:** {_truncate(current['next_due'], 180)}",
            f"- **Record:** [record.md]({record_path})",
        ]
    )
    return "\n".join(lines)


def _technical_table_lines(
    snapshot: dict[str, Any],
    fields: tuple[tuple[str, str], ...] = TECHNICAL_FIELDS,
) -> list[str]:
    technical = snapshot.get("technical_spec")
    if not isinstance(technical, dict):
        raise PresentationError("technical_spec must be an object")
    lines = [
        "| Field | Proof state | Value | Evidence basis |",
        "|---|---|---|---|",
    ]
    for key, label in fields:
        item = technical.get(key)
        if not isinstance(item, dict):
            raise PresentationError(f"technical_spec.{key} is required")
        state = item.get("state")
        if state not in PROOF_STATES:
            raise PresentationError(f"unsupported proof state: {state}")
        for required in ("value", "evidence"):
            if not _inline(item.get(required, "")):
                raise PresentationError(
                    f"technical_spec.{key}.{required} must be non-empty"
                )
        lines.append(
            f"| {label} | {state} | {_cell(item['value'])} | "
            f"{_cell(item['evidence'])} |"
        )
    return lines


def render_technical_spec(snapshot: dict[str, Any], record_path: str) -> str:
    lines = [
        render_case_card(snapshot, record_path),
        "",
        render_technical_advice(snapshot),
        "",
        "## Technical Specification",
        "",
    ]
    lines.extend(_technical_table_lines(snapshot))
    return "\n".join(lines)


def render_standard(
    snapshot: dict[str, Any],
    record_path: str,
    visual: str,
    delta: dict[str, Any] | None = None,
    show_delta: bool = False,
) -> str:
    lines: list[str] = []
    case_card = render_case_card(
        snapshot,
        record_path,
        heading="## Current Case Card" if show_delta and _has_material_delta(delta) else "## Case Card",
    )
    if show_delta and _has_material_delta(delta):
        new_evidence = _new_evidence_items(delta or {})
        unchanged_items = (delta or {}).get("unchanged_blockers", [])
        delta_lines = [
            "## Changed Since Last Review",
            "",
            f"- **Changed since last review:** {_changed_field_summary(delta or {})}",
            (
                "- **New decisive evidence:** "
                + ("; ".join(new_evidence[:3]) if new_evidence else "None.")
            ),
            (
                "- **Unchanged blocker:** "
                + (
                    "; ".join(_inline(item) for item in unchanged_items)
                    if unchanged_items
                    else "None."
                )
            ),
        ]
        lines.append("\n".join(delta_lines))
    lines.append(case_card)
    lines.append(render_technical_advice(snapshot))
    lines.append(render_progress_flow_section(snapshot))
    if visual not in ("none", "progress-flow"):
        section = render_visual_section(snapshot, visual)
        if section:
            lines.append(section)
    lines.append(render_causal_assessment(snapshot))
    technical_lines = ["## Key Technical Specification", ""]
    technical_lines.extend(
        _technical_table_lines(snapshot, STANDARD_TECHNICAL_FIELDS)
    )
    lines.append("\n".join(technical_lines))
    milestones = _chronological_items(snapshot.get("milestones", []))
    if milestones:
        milestone_lines = ["## Progress Milestones", ""]
        milestone_lines.extend(
            f"- **{_inline(item['date'])}:** {_inline(item['change'])}"
            for item in milestones[:5]
        )
        lines.append("\n".join(milestone_lines))
    lines.append("\n".join(_timeline_lines(snapshot)))
    lines.append("\n".join(_evidence_register_lines(snapshot)))
    return "\n\n".join(lines)


def _lineage_value(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(_inline(item) for item in value) or "unknown"
    return _inline(value) or "unknown"


def render_causal_assessment(snapshot: dict[str, Any]) -> str:
    lineage = snapshot.get("problem_lineage")
    technical = snapshot.get("technical_spec")
    if not isinstance(lineage, dict) or not isinstance(technical, dict):
        raise PresentationError("problem_lineage and technical_spec are required")

    def technical_value(key: str) -> tuple[str, str]:
        item = technical.get(key)
        if not isinstance(item, dict):
            raise PresentationError(f"technical_spec.{key} is required")
        return _inline(item.get("value", "")), (
            f"{_inline(item.get('state', 'UNKNOWN'))}: "
            f"{_inline(item.get('evidence', 'unknown'))}"
        )

    confirmed, confirmed_boundary = technical_value("confirmed_mechanism")
    change, change_boundary = technical_value("change_or_mitigation")
    production, production_boundary = technical_value("production_outcome")
    verification, verification_boundary = technical_value("verification")
    gaps, gaps_boundary = technical_value("evidence_gaps")
    rows = (
        (
            "Observed failure / objective",
            _lineage_value(lineage.get("original_objective")),
            "Observed case objective or symptom; not a cause statement.",
        ),
        ("Confirmed mechanism", confirmed, confirmed_boundary),
        (
            "Suspected causal paths",
            _lineage_value(lineage.get("working_hypotheses")),
            "Hypotheses only until the listed validation closes the causal gap.",
        ),
        (
            "Corrected finding",
            _lineage_value(lineage.get("corrected_finding")),
            "Explains the corrected understanding; it is not root-cause proof by itself.",
        ),
        (
            "Implemented action",
            _lineage_value(lineage.get("implemented_action")) or change,
            change_boundary,
        ),
        (
            "Proven outcome",
            _lineage_value(lineage.get("outcome")) or production,
            production_boundary,
        ),
        (
            "Remaining causal validation",
            f"{verification}; {gaps}",
            f"{verification_boundary}; {gaps_boundary}",
        ),
    )
    lines = [
        "## Causal Assessment",
        "",
        "This separates observed sequence, confirmed mechanism, and working hypotheses; chronology is not causal proof.",
        "",
        "| Stage | Evidence-backed assessment | Proof boundary |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {label} | {_cell(value)} | {_cell(boundary)} |"
        for label, value, boundary in rows
    )
    return "\n".join(lines)


def _timeline_lines(snapshot: dict[str, Any]) -> list[str]:
    timeline = snapshot.get("timeline")
    if not isinstance(timeline, list):
        raise PresentationError("timeline must be a list")
    if not timeline:
        return [
            "## Timeline",
            "",
            "unknown — no evidence-backed timeline event is available for display.",
        ]
    lines = [
        "## Timeline",
        "",
        "| Date | By | Source | What changed |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {_cell(item['date'])} | {_cell(item['by'])} | "
        f"{_cell(item['source'])} | {_cell(item['change'])} |"
        for item in _chronological_items(timeline)
    )
    return lines


def _evidence_register_lines(
    snapshot: dict[str, Any], heading: str = "## Evidence Register"
) -> list[str]:
    evidence = snapshot.get("evidence_register")
    if not isinstance(evidence, list) or not evidence:
        raise PresentationError("evidence_register must contain evidence")
    lines = [
        heading,
        "",
        "| Ref | Date | Source | Verbatim evidence / data | Supports |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {_cell(item['ref'])} | {_cell(item['date'])} | "
        f"{_cell(item['source'])} | {_cell(item['evidence'])} | "
        f"{_cell(item['supports'])} |"
        for item in _chronological_items(evidence)
    )
    return lines


def render_full(snapshot: dict[str, Any], record_path: str) -> str:
    lineage = snapshot.get("problem_lineage")
    if not isinstance(lineage, dict):
        raise PresentationError("problem_lineage must be an object")
    lines = [
        render_case_card(snapshot, record_path, heading="## Current Case Card"),
        "",
        render_technical_advice(snapshot),
        "",
        render_progress_flow_section(snapshot),
        "",
        render_causal_assessment(snapshot),
        "",
        "## Problem Lineage",
        "",
        "| Dimension | Value |",
        "|---|---|",
    ]
    lineage_labels = {
        "original_objective": "Original objective",
        "intended_action": "Intended action",
        "blocker": "Blocker",
        "working_hypotheses": "Working hypotheses",
        "corrected_finding": "Corrected finding",
        "implemented_action": "Implemented action",
        "outcome": "Outcome",
        "secondary_problems": "Secondary problems",
    }
    for key in PROBLEM_LINEAGE_FIELDS:
        label = lineage_labels[key]
        lines.append(f"| {label} | {_cell(_lineage_value(lineage.get(key)))} |")
    lines.extend(["", "## Technical Specification", ""])
    lines.extend(_technical_table_lines(snapshot))
    milestones = _chronological_items(snapshot.get("milestones", []))
    if milestones:
        lines.extend(["", "## Progress Milestones", ""])
        lines.extend(
            f"- **{_inline(item['date'])}:** {_inline(item['change'])}"
            for item in milestones
        )
    lines.append("")
    lines.extend(_timeline_lines(snapshot))
    evidence = snapshot.get("evidence_register")
    if not isinstance(evidence, list) or not evidence:
        raise PresentationError("evidence_register must contain evidence")
    lines.extend(
        [
            "",
            "## Appendix A — Evidence Register",
            "",
            "| Ref | Date | Source | Verbatim evidence / data | Supports |",
            "|---|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {_cell(item['ref'])} | {_cell(item['date'])} | "
        f"{_cell(item['source'])} | {_cell(item['evidence'])} | "
        f"{_cell(item['supports'])} |"
        for item in _chronological_items(evidence)
    )
    return "\n".join(lines)


def _mermaid_label(value: Any) -> str:
    return (
        _inline(value)
        .replace("\\", "/")
        .replace('"', "'")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_progress_flow_section(snapshot: dict[str, Any]) -> str:
    visual = snapshot.get("visual_context")
    transitions = visual.get("transitions") if isinstance(visual, dict) else None
    if isinstance(transitions, list):
        # Keep the authored investigation sequence when any step lacks a date.
        # Sorting just the dated subset would move an undated middle step to the end.
        transitions = (
            _chronological_items(transitions)
            if all(
                isinstance(item, dict) and _date_sort_key(item.get("date")) is not None
                for item in transitions
            )
            else list(transitions)
        )
    if not isinstance(transitions, list) or len(transitions) < 2:
        milestones = _chronological_items(snapshot.get("milestones", []))
        if isinstance(milestones, list) and len(milestones) >= 2:
            transitions = [
                {
                    "label": f"{_inline(item['date'])}: {_inline(item['change'])}",
                    "state": "OBSERVED",
                    "date": item["date"],
                }
                for item in milestones
            ]
        else:
            lineage = snapshot.get("problem_lineage")
            if not isinstance(lineage, dict):
                raise PresentationError("progress flow requires problem lineage")
            hypotheses = _lineage_value(lineage.get("working_hypotheses"))
            candidates = (
                (lineage.get("original_objective"), "OBSERVED"),
                (lineage.get("blocker"), "BLOCKER"),
                (hypotheses, "SUSPECTED"),
                (lineage.get("corrected_finding"), "CONFIRMED MECHANISM"),
                (lineage.get("implemented_action"), "PRODUCTION DEPLOYED"),
                (lineage.get("outcome"), "PENDING"),
            )
            transitions = [
                {"label": _inline(label), "state": state}
                for label, state in candidates
                if _inline(label) and _inline(label).casefold() not in {"unknown", "none"}
            ]
            if len(transitions) < 2:
                raise PresentationError(
                    "progress flow requires at least two transitions, milestones, or lineage states"
                )
    bounded = transitions if len(transitions) <= 7 else transitions[:3] + transitions[-4:]
    fully_dated = all(
        isinstance(item, dict) and _date_sort_key(item.get("date")) is not None
        for item in bounded
    )
    lines = [
        "## Investigation Progress",
        "",
        (
            "Dated investigation states are chronological; arrows do not prove causation."
            if fully_dated
            else "Investigation states follow the documented sequence; undated steps have unknown timing, and arrows do not prove causation."
        ),
        "",
        "```mermaid",
        "flowchart TD",
    ]
    for index, item in enumerate(bounded, start=1):
        if not isinstance(item, dict) or not _inline(item.get("label", "")):
            raise PresentationError("each transition requires a label")
        lines.append(f'    N{index}["{_mermaid_label(item["label"])}"]')
    for index in range(1, len(bounded)):
        lines.append(f"    N{index} -->|next documented step| N{index + 1}")
    lines.extend(
        [
            "    classDef observed fill:#dbeafe,stroke:#2563eb,color:#0f172a;",
            "    classDef blocker fill:#fee2e2,stroke:#dc2626,color:#0f172a;",
            "    classDef hypothesis fill:#fef3c7,stroke:#d97706,color:#0f172a;",
            "    classDef confirmed fill:#dcfce7,stroke:#15803d,color:#0f172a;",
            "    classDef mitigation fill:#ede9fe,stroke:#7c3aed,color:#0f172a;",
            "    classDef pending fill:#e5e7eb,stroke:#6b7280,color:#0f172a;",
        ]
    )
    for index, item in enumerate(bounded, start=1):
        state = _inline(item.get("state", "UNKNOWN")).upper()
        lines.append(f"    class N{index} {VISUAL_STATE_CLASSES.get(state, 'pending')};")
    lines.append("```")
    return "\n".join(lines)


def render_progress_flow(snapshot: dict[str, Any], record_path: str) -> str:
    return "\n\n".join(
        [
            f"# Investigation Progress - {snapshot['case_id']}",
            render_progress_flow_section(snapshot),
            f"**Record:** [record.md]({record_path})",
        ]
    )


def select_visual(snapshot: dict[str, Any]) -> str:
    context = snapshot.get("visual_context")
    if not isinstance(context, dict):
        return "none"
    recurrences = context.get("recurrences")
    if isinstance(recurrences, list) and len(recurrences) >= 2:
        return "event-comparison"
    hypotheses = context.get("hypotheses")
    if isinstance(hypotheses, list) and len(hypotheses) >= 2:
        return "claim-evidence-matrix"
    components = context.get("components")
    handoffs = context.get("handoffs")
    if (
        isinstance(components, list)
        and len(components) >= 3
        and isinstance(handoffs, list)
        and handoffs
    ):
        return "component-swimlane"
    transitions = context.get("transitions")
    if isinstance(transitions, list) and len(transitions) >= 3:
        return "progress-flow"
    ownership = context.get("ownership")
    if context.get("ownership_stall") is True and isinstance(ownership, list) and ownership:
        return "ownership-table"
    return "none"


def render_event_comparison(snapshot: dict[str, Any]) -> str:
    context = snapshot.get("visual_context", {})
    recurrences = _chronological_items(context.get("recurrences", []))
    lines = [
        "## Event Comparison",
        "",
        "| Date | Symptom | Change or action | Outcome |",
        "|---|---|---|---|",
    ]
    for item in recurrences[:5]:
        lines.append(
            f"| {_cell(item['date'])} | {_cell(item['symptom'])} | "
            f"{_cell(item['change'])} | {_cell(item['outcome'])} |"
        )
    return "\n".join(lines)


def render_claim_evidence_matrix(snapshot: dict[str, Any]) -> str:
    context = snapshot.get("visual_context", {})
    hypotheses = context.get("hypotheses", [])
    lines = [
        "## Claim–Evidence Matrix",
        "",
        "| Claim | Proof state | Evidence | Validation needed |",
        "|---|---|---|---|",
    ]
    for item in hypotheses[:5]:
        state = item.get("state")
        if state not in PROOF_STATES:
            raise PresentationError(f"unsupported proof state: {state}")
        lines.append(
            f"| {_cell(item['claim'])} | {state} | {_cell(item['evidence'])} | "
            f"{_cell(item['validation'])} |"
        )
    return "\n".join(lines)


def render_component_swimlane(snapshot: dict[str, Any]) -> str:
    context = snapshot.get("visual_context", {})
    components = context.get("components", [])[:5]
    handoffs = context.get("handoffs", [])
    name_to_id: dict[str, str] = {}
    lines = ["## Component Swimlane", "", "```mermaid", "flowchart LR"]
    for index, item in enumerate(components, start=1):
        name = _inline(item.get("name", ""))
        finding = _inline(item.get("finding", ""))
        if not name or not finding:
            raise PresentationError("each component requires name and finding")
        node_id = f"C{index}"
        name_to_id[name] = node_id
        lines.extend(
            [
                f'    subgraph L{index}["{_mermaid_label(name)}"]',
                f'        {node_id}["{_mermaid_label(finding)}"]',
                "    end",
            ]
        )
    for handoff in handoffs:
        source = name_to_id.get(_inline(handoff.get("from", "")))
        target = name_to_id.get(_inline(handoff.get("to", "")))
        label = _inline(handoff.get("label", ""))
        if source and target and label:
            lines.append(
                f"    {source} -->|{_mermaid_label(label)}| {target}"
            )
    lines.extend(
        [
            "    classDef observed fill:#dbeafe,stroke:#2563eb,color:#0f172a;",
            "    classDef blocker fill:#fee2e2,stroke:#dc2626,color:#0f172a;",
            "    classDef hypothesis fill:#fef3c7,stroke:#d97706,color:#0f172a;",
            "    classDef confirmed fill:#dcfce7,stroke:#15803d,color:#0f172a;",
            "    classDef mitigation fill:#ede9fe,stroke:#7c3aed,color:#0f172a;",
            "    classDef pending fill:#e5e7eb,stroke:#6b7280,color:#0f172a;",
        ]
    )
    for index, item in enumerate(components, start=1):
        state = _inline(item.get("state", "UNKNOWN")).upper()
        lines.append(f"    class C{index} {VISUAL_STATE_CLASSES.get(state, 'pending')};")
    lines.append("```")
    return "\n".join(lines)


def render_ownership_table(snapshot: dict[str, Any]) -> str:
    context = snapshot.get("visual_context", {})
    ownership = context.get("ownership", [])
    lines = [
        "## Ownership Checkpoint",
        "",
        "| Owner | Action | Deadline | Status |",
        "|---|---|---|---|",
    ]
    for item in ownership[:5]:
        lines.append(
            f"| {_cell(item['owner'])} | {_cell(item['action'])} | "
            f"{_cell(item['deadline'])} | {_cell(item['status'])} |"
        )
    return "\n".join(lines)


def render_visual_section(snapshot: dict[str, Any], visual: str) -> str:
    if visual == "progress-flow":
        return render_progress_flow_section(snapshot)
    if visual == "event-comparison":
        return render_event_comparison(snapshot)
    if visual == "claim-evidence-matrix":
        return render_claim_evidence_matrix(snapshot)
    if visual == "component-swimlane":
        return render_component_swimlane(snapshot)
    if visual == "ownership-table":
        return render_ownership_table(snapshot)
    return ""


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if not isinstance(snapshot, dict) or not _inline(snapshot.get("case_id", "")):
        raise PresentationError("snapshot.case_id is required")
    current = snapshot.get("current")
    if not isinstance(current, dict):
        raise PresentationError("snapshot.current must be an object")
    for field in CURRENT_PRESENTATION_FIELDS:
        if not _inline(current.get(field, "")):
            raise PresentationError(f"snapshot.current.{field} is required")
    for field in ("impact", "current_progress"):
        if field in current and not _inline(current[field]):
            raise PresentationError(f"snapshot.current.{field} must be non-empty")
    render_full(snapshot, "")
    visual = select_visual(snapshot)
    if visual != "none":
        render_visual_section(snapshot, visual)


def render_review(
    *,
    request_text: str,
    snapshot: dict[str, Any],
    review_count: int,
    delta: dict[str, Any] | None,
    record_path: str,
) -> dict[str, Any]:
    validate_snapshot(snapshot)
    mode = select_mode(request_text, review_count, delta)
    visual = select_visual(snapshot)
    if mode == "flow":
        visual = "progress-flow"
        body = "\n\n".join(
            [
                render_case_card(snapshot, record_path),
                render_technical_advice(snapshot),
                render_progress_flow_section(snapshot),
            ]
        )
    elif mode == "full":
        visual = "none"
        body = render_full(snapshot, record_path)
    elif mode == "technical":
        visual = "none"
        body = render_technical_spec(snapshot, record_path)
    elif mode == "compact":
        body = "\n\n".join(
            [render_case_card(snapshot, record_path), render_technical_advice(snapshot)]
        )
        section = render_visual_section(snapshot, visual)
        if section:
            body += "\n\n" + section
    elif mode == "follow-up":
        body = render_standard(
            snapshot,
            record_path,
            visual,
            delta,
            show_delta=True,
        )
    else:
        body = render_standard(
            snapshot,
            record_path,
            visual,
            delta,
            show_delta=review_count > 1,
        )
    return {
        "mode": mode,
        "visual": visual,
        "markdown": render_executive_summary(snapshot) + "\n\n" + body,
    }
