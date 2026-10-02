# Case Review Output Modes

Use this contract only after Complete Context Before Analysis and the evidence gate pass. Presentation mode never changes source scope, evidence authority, RCA state, or mitigation classification.

Every successful structured mode starts with `# Case Review - <ID>` and a four-line `## Executive Summary`. The first line combines official Status with a concise Reported issue from `current.primary_problem`; the remaining lines label Impact, Critical finding, and Production outcome. `current.impact` and `current.confirmed_finding` are each one concise, plain-language statement; exact technical progress and uncertainty belong in `current.current_progress`. Use `unknown` where evidence is missing and keep unresolved conflicts visible. Mention NotebookLM validation only when an actual case-specific result is available and substantiated by the case evidence; when absent, omit it entirely. NotebookLM is optional, never a collection prerequisite.

After the summary, show `## Case Card` (or `## Current Case Card` in `follow-up` and `full`). It contains `Reported Problem / Symptom` from `current.primary_problem` and `Current State` from `current.current_progress`, plus separate RCA, mitigation, and production-outcome boundaries. `Current State` names the progress made, relevant trace or log results, and what still needs validation. The card's `### Action Plan` contains only `Required Action / Next Step` from the documented `current.next_action`, with its evidenced owner and due date; use `not stated` when no next commitment is documented. The separate `## Technical Advice` section has `### Immediate diagnostic steps`, `### Potential solutions (conditional)`, and `### Long-term next steps`. These are recommendations, not existing commitments, past work, or confirmed causes. Each step gives its case evidence or precise evidence gap as `basis`; potential solutions also state the condition that must hold before the solution applies. Empty groups display an honest gap rather than invented advice.

## Mode Router

Apply explicit user intent before automatic defaults:

1. `full` — requests containing `full review`, `full report`, or `Evidence Register`.
2. `technical` — requests containing `dry technical`, `technical spec`, or `technical specification`.
3. `flow` — requests containing `flow chart`, `flowchart`, or `investigation progress`.
4. `standard` — an explicit standard request, a first successful plain review, or a later plain review with no material delta.
5. `compact` — an explicit compact or brief request only.
6. `follow-up` — no explicit mode, prior successful history, and a material state, ownership, or evidence change.

Do not ask the user to choose a format for an ordinary review. Route it automatically.

## Mode Contracts

### `standard`

- Return an investigation-complete view: Executive Summary, Case Card with recorded Action Plan, separate Technical Advice, Investigation Progress flow, optional secondary diagnostic visual, Causal Assessment, six key Technical Specification fields, substantive milestones, Timeline, complete dynamic Evidence Register, and durable-record link.
- The six key fields are Scope, Symptom, Confirmed mechanism, Suspected or unproven, Verification, and Evidence gaps.
- The progress flow is always present. Prefer evidence-labeled `visual_context.transitions`; for migrated snapshots without transitions, derive nodes from milestones or problem lineage. When every transition has a date, sort oldest first. When any transition lacks a date, preserve the authored sequence and caption that precise timing is unknown. Arrows show displayed sequence, never causal proof.
- A second evidence-backed diagnostic visual may follow the progress flow when recurrence, competing hypotheses, component handoff, or ownership evidence meets its threshold.
- The Causal Assessment must distinguish observed failure, confirmed mechanism, suspected causal paths, corrected finding, implemented action, proven outcome, and remaining causal validation.
- Keep complete visual columns and evidence-backed values. Never shorten away an impact conflict, recovery or post-change validation gap, next-action owner, due date / ETA, timeline row, or evidence row.
- Put the helper-computed delta immediately after the Executive Summary when an explicit standard view is requested for a materially changed follow-up.
- Render every evidence-backed substantive Timeline row and every dynamic Evidence Register row. Never pad milestones when fewer than three are supported.

### `compact`

- Return a concise Executive Summary, Case Card with recorded Action Plan, separate Technical Advice, and record link. Keep the problem, progress, impact, proof boundaries, next documented action, and conditional advice visible.
- Render no Timeline or Evidence Register.
- Keep the card concise without dropping a required field or advice group.
- Add one adaptive visual only when the structured visual context meets a router threshold.

### `follow-up`

- Use this automatic mode only when the stored comparison reports a material state, ownership, or evidence change.
- Put `Changed since last review` and `Unchanged blocker` after the Executive Summary and before Current Case Card.
- Use the helper-computed delta; never reconstruct differences from memory.
- After the delta, render the same investigation-complete core as `standard`; do not discard flow, causal assessment, Timeline, or Evidence Register merely because history exists.

### `technical`

After the Executive Summary, Case Card, and Technical Advice, render the Technical Specification with exactly this table schema: `Field | Proof state | Value | Evidence basis`:

1. Scope
2. Environment
3. Symptom
4. Trigger / conditions
5. Observed signals
6. Confirmed mechanism
7. Suspected or unproven
8. Ruled out
9. Change / mitigation
10. Verification
11. Production outcome
12. Evidence gaps

Use only these proof states: `OBSERVED`, `CONFIRMED MECHANISM`, `SUSPECTED`, `CONTRADICTED`, `NOT TESTED`, `PRODUCTION DEPLOYED`, `OUTCOME CONFIRMED`, `NOT OBSERVED`, `NOT COLLECTED`, `NOT APPLICABLE`, and `UNKNOWN`. Never use numeric confidence percentages. `NOT OBSERVED`, `NOT COLLECTED`, `UNKNOWN`, and `NOT APPLICABLE` are not interchangeable.

### `flow`

- Render the Executive Summary, Case Card, Technical Advice, Investigation Progress flow, and durable-record link. Explicit flow intent always selects `progress-flow`, even when another adaptive visual is available.
- State that arrows show displayed sequence, not causal proof. When all transitions have dates, the sequence is oldest first; with any undated transition, preserve authored order and state that precise timing is unknown.
- Limit Mermaid flows to seven nodes.
- Keep observed, blocker, hypothesis, confirmed mechanism, mitigation, and pending states visually distinct.

### `full`

- Generate the complete view from the structured snapshot only when explicitly requested.
- Present Executive Summary, Current Case Card with recorded Action Plan, separate Technical Advice, Investigation Progress flow, Causal Assessment, Problem Lineage, Technical Specification, Progress Milestones when present, Timeline, and Appendix A.
- Keep `Appendix A — Evidence Register` as the final section of this mode only.
- Keep the Executive Summary brief; never add unsupported detail to fill it.

## Secondary Diagnostic Visual Selection

Standard and follow-up already contain an Investigation Progress flow. Choose at most one additional diagnostic visual in this priority order:

1. Two or more recurrence events → `event-comparison`.
2. Two or more competing hypotheses → `claim-evidence-matrix`.
3. Three or more components plus explicit handoffs → `component-swimlane`.
4. Evidence-backed ownership stall → `ownership-table`.
5. Otherwise → `none`.

Never infer a component handoff, causal edge, recurrence, or ruled-out hypothesis merely to trigger a visual.

## Structured Review Snapshot v2

Build one `presentation` object with:

- `technical_advice` — required `immediate_diagnostics: [{action, basis}]`, `potential_solutions: [{action, condition, basis}]`, and `long_term_steps: [{action, basis}]`. Empty arrays are valid when no case-grounded advice can be given.
- `technical_spec` — all twelve fixed fields, each containing `state`, `value`, and `evidence`.
- `problem_lineage` — original objective, intended action, blocker, working hypotheses, corrected finding, implemented action, outcome, and secondary problems.
- `milestones` — substantive state transitions only, oldest first.
- `timeline` — evidence-backed Date / By / Source / What changed rows, oldest first.
- `evidence_register` — dynamic `E1..EN` rows with date, source, verbatim evidence, and reverse mapping.
- `visual_context` — only evidenced transitions, recurrences, hypotheses, components/handoffs, or ownership checkpoints. Populate `transitions` whenever at least two substantive investigation states are evidenced; migrated snapshots may use the renderer's milestones/lineage fallback. Author mixed dated/undated transitions in the intended displayed sequence because the renderer preserves that order.

Use these exact payload field names when constructing the structured object:

- `timeline` rows use `date`, `by`, `source`, and `change`.
- `evidence_register` rows use `ref`, `date`, `source`, `evidence`, and `supports`.
- `technical_spec` keys are `scope`, `environment`, `symptom`, `trigger_conditions`, `observed_signals`,
  `confirmed_mechanism`, `suspected_or_unproven`, `ruled_out`, `change_or_mitigation`, `verification`,
  `production_outcome`, and `evidence_gaps`.

The durable-record payload keeps the existing `current`, `coverage`, and `evidence_digest` fields and adds this `presentation` object. `current.impact` and `current.current_progress` are required alongside `current.primary_problem` and `current.next_action`. `finalize` and `finalize-overlay` require structured `presentation` and reject a `full_review_markdown`-only payload before any durable mutation. The legacy `update` command still accepts `full_review_markdown` for compatibility.

## Deterministic Commands

After building the UTF-8 payload:

```text
python <skill-directory>/scripts/case_record.py finalize-overlay --manifest <manifest.json> --overlay <overlay.json> --case-id <Case ID> --request "<original user request>"
```

`finalize-overlay` performs validation, the idempotent update, deterministic rendering, artifact/hash writes, and internal verification under one per-case lock. It emits only the verified canonical Markdown. Return stdout unchanged; do not manually shorten, expand, rewrite, or append a second report. A validation, rendering, write, hash, or verification failure must block completion without a partial record mutation. The backward-compatible `update`, `present --markdown-only`, and `verify-final` commands remain supported. JSON-mode `present` retains the auditable `mode` and `visual` fields.

## Non-Negotiable Acceptance

- Incomplete collection and zero evidence do not create or modify a record.
- Prior records are comparison baselines, never current evidence.
- Every successful mode begins with the evidenced Executive Summary, then presents the current problem, progress, recorded Action Plan, and separate Technical Advice before mode-specific detail.
- The next documented action stays separate from recommended diagnostic steps and conditional potential solutions. Neither guidance nor NotebookLM output alone establishes a case fact, implemented mitigation, or durable recovery.
- Default and material follow-up chat output retain the investigation flow, causal assessment, Timeline, and complete dynamic Evidence Register.
- `compact` is explicit-only. No automatic follow-up may silently remove investigative context.
- Administrative closure remains separate from RCA and production outcome.
- Learning remains explicit-request and explicit-approval only.
