#!/usr/bin/env python3
"""Deterministic presentation routing and rendering for case reviews."""

from __future__ import annotations

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


def _inline(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


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


def render_case_card(snapshot: dict[str, Any], record_path: str) -> str:
    current = snapshot["current"]
    checkpoint = (
        f"{current['next_action']} — {current['next_action_owner']} — "
        f"{current['next_due']}"
    )
    lines = [
        f"# Case Card - {snapshot['case_id']}",
        "",
        (
            f"**Status:** {_inline(current['official_status'])} | "
            f"**RCA:** {_inline(current['rca_state'])} | "
            f"**Mitigation:** {_inline(current['mitigation_state'])}"
        ),
        "",
        f"- **Primary problem:** {_inline(current['primary_problem'])}",
        f"- **Confirmed:** {_inline(current['confirmed_finding'])}",
        (
            "- **Unproven or contradicted:** "
            f"{_inline(current['unproven_or_contradicted'])}"
        ),
        f"- **Production outcome:** {_inline(current['production_outcome'])}",
        f"- **Current blocker:** {_inline(current['current_blocker'])}",
        f"- **Next checkpoint:** {_inline(checkpoint)}",
        f"- **Record:** [record.md]({record_path})",
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
    lines = [f"# Technical Specification - {snapshot['case_id']}", ""]
    lines.extend(_technical_table_lines(snapshot))
    lines.extend(["", f"**Record:** [record.md]({record_path})"])
    return "\n".join(lines)


def render_standard(
    snapshot: dict[str, Any],
    record_path: str,
    visual: str,
    delta: dict[str, Any] | None = None,
    show_delta: bool = False,
) -> str:
    lines: list[str] = []
    case_card = render_case_card(snapshot, record_path)
    if show_delta and _has_material_delta(delta):
        new_evidence = _new_evidence_items(delta or {})
        unchanged_items = (delta or {}).get("unchanged_blockers", [])
        delta_lines = [
            f"# Case Review Update - {snapshot['case_id']}",
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
        case_card = case_card.replace(
            f"# Case Card - {snapshot['case_id']}",
            "## Current Case Card",
            1,
        )
    lines.append(case_card)
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
    milestones = snapshot.get("milestones", [])
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
    lines = [
        "## Timeline",
        "",
        "| Date | By | Source | What changed |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {_cell(item['date'])} | {_cell(item['by'])} | "
        f"{_cell(item['source'])} | {_cell(item['change'])} |"
        for item in timeline
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
        for item in evidence
    )
    return lines


def render_full(snapshot: dict[str, Any], record_path: str) -> str:
    current = snapshot["current"]
    lineage = snapshot.get("problem_lineage")
    if not isinstance(lineage, dict):
        raise PresentationError("problem_lineage must be an object")
    lines = [
        f"# Full Case Review - {snapshot['case_id']}",
        "",
        (
            f"**Status:** {_inline(current['official_status'])} | "
            f"**RCA:** {_inline(current['rca_state'])} | "
            f"**Mitigation:** {_inline(current['mitigation_state'])}"
        ),
        f"**Record:** [record.md]({record_path})",
        "",
        "## Current Case Card",
        "",
        f"- **Primary problem:** {_inline(current['primary_problem'])}",
        f"- **Confirmed:** {_inline(current['confirmed_finding'])}",
        (
            "- **Unproven or contradicted:** "
            f"{_inline(current['unproven_or_contradicted'])}"
        ),
        f"- **Production outcome:** {_inline(current['production_outcome'])}",
        f"- **Current blocker:** {_inline(current['current_blocker'])}",
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
    lineage_fields = (
        ("original_objective", "Original objective"),
        ("intended_action", "Intended action"),
        ("blocker", "Blocker"),
        ("working_hypotheses", "Working hypotheses"),
        ("corrected_finding", "Corrected finding"),
        ("implemented_action", "Implemented action"),
        ("outcome", "Outcome"),
        ("secondary_problems", "Secondary problems"),
    )
    for key, label in lineage_fields:
        lines.append(f"| {label} | {_cell(_lineage_value(lineage.get(key)))} |")
    lines.extend(["", "## Technical Specification", ""])
    lines.extend(_technical_table_lines(snapshot))
    milestones = snapshot.get("milestones", [])
    if milestones:
        lines.extend(["", "## Progress Milestones", ""])
        lines.extend(
            f"- **{_inline(item['date'])}:** {_inline(item['change'])}"
            for item in milestones
        )
    timeline = snapshot.get("timeline")
    if not isinstance(timeline, list):
        raise PresentationError("timeline must be a list")
    lines.extend(
        [
            "",
            "## Timeline",
            "",
            "| Date | By | Source | What changed |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {_cell(item['date'])} | {_cell(item['by'])} | "
        f"{_cell(item['source'])} | {_cell(item['change'])} |"
        for item in timeline
    )
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
        for item in evidence
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
    if not isinstance(transitions, list) or len(transitions) < 2:
        milestones = snapshot.get("milestones")
        if isinstance(milestones, list) and len(milestones) >= 2:
            transitions = [
                {
                    "label": f"{_inline(item['date'])}: {_inline(item['change'])}",
                    "state": "OBSERVED",
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
    lines = [
        "## Investigation Progress",
        "",
        "Sequence of investigation states; arrows show chronology, not causal proof.",
        "",
        "```mermaid",
        "flowchart TD",
    ]
    for index, item in enumerate(bounded, start=1):
        if not isinstance(item, dict) or not _inline(item.get("label", "")):
            raise PresentationError("each transition requires a label")
        lines.append(f'    N{index}["{_mermaid_label(item["label"])}"]')
    for index in range(1, len(bounded)):
        lines.append(f"    N{index} -->|next observed state| N{index + 1}")
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
    recurrences = context.get("recurrences", [])
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
        selected = "progress-flow"
        section = render_progress_flow_section(snapshot)
        markdown = "\n\n".join(
            [
                f"# Investigation View - {snapshot['case_id']}",
                section,
                f"**Record:** [record.md]({record_path})",
            ]
        )
        return {
            "mode": mode,
            "visual": selected,
            "markdown": markdown,
        }
    if mode == "full":
        return {
            "mode": mode,
            "visual": "none",
            "markdown": render_full(snapshot, record_path),
        }
    if mode == "technical":
        return {
            "mode": mode,
            "visual": "none",
            "markdown": render_technical_spec(snapshot, record_path),
        }
    if mode == "compact":
        markdown = render_case_card(snapshot, record_path)
        section = render_visual_section(snapshot, visual)
        if section:
            markdown += "\n\n" + section
        return {
            "mode": mode,
            "visual": visual,
            "markdown": markdown,
        }
    if mode == "follow-up":
        markdown = render_standard(
            snapshot,
            record_path,
            visual,
            delta,
            show_delta=True,
        )
        return {
            "mode": mode,
            "visual": visual,
            "markdown": markdown,
        }
    markdown = render_standard(
        snapshot,
        record_path,
        visual,
        delta,
        show_delta=review_count > 1,
    )
    return {
        "mode": "standard",
        "visual": visual,
        "markdown": markdown,
    }
