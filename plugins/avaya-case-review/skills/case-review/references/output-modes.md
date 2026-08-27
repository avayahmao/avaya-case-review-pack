# Case Review Output Modes

Use this contract only after Complete Context Before Analysis and the evidence gate pass. Presentation mode never changes source scope, evidence authority, RCA state, or mitigation classification.

## Mode Router

Apply explicit user intent before automatic defaults:

1. `full` — requests containing `full review`, `full report`, `完整报告`, or `Evidence Register`.
2. `technical` — requests containing `dry technical`, `technical spec`, `technical specification`, `技术规格`, or `技术评审`.
3. `flow` — requests containing `flow chart`, `flowchart`, `investigation progress`, `流程图`, or `调查进展图`.
4. `standard` — an explicit standard request, a first successful plain review, or a later plain review with no material delta.
5. `compact` — an explicit compact or brief request only.
6. `follow-up` — no explicit mode, prior successful history, and a material state, ownership, or evidence change.

Do not ask the user to choose a format for an ordinary review. Route it automatically.

## Mode Contracts

### `standard`

- Return an investigation-complete view: Case Card, Investigation Progress flow, optional secondary diagnostic visual, Causal Assessment, six key Technical Specification fields, substantive milestones, Timeline, complete dynamic Evidence Register, and durable-record link.
- The six key fields are Scope, Symptom, Confirmed mechanism, Suspected or unproven, Verification, and Evidence gaps.
- The progress flow is always present. Prefer evidence-labeled `visual_context.transitions`; for migrated snapshots without transitions, derive chronology-only nodes from milestones or problem lineage and state that arrows show chronology, not causal proof.
- A second evidence-backed diagnostic visual may follow the progress flow when recurrence, competing hypotheses, component handoff, or ownership evidence meets its threshold.
- The Causal Assessment must distinguish observed failure, confirmed mechanism, suspected causal paths, corrected finding, implemented action, proven outcome, and remaining causal validation.
- Keep complete visual columns and evidence-backed values. Never shorten away an impact conflict, recovery or post-change validation gap, next-action owner, due date / ETA, timeline row, or evidence row.
- Put the helper-computed delta first when an explicit standard view is requested for a materially changed follow-up.
- Render every evidence-backed substantive Timeline row and every dynamic Evidence Register row. Never pad milestones when fewer than three are supported.

### `compact`

- Return one Case Card with status, RCA state, mitigation state, primary problem, confirmed finding, unsupported or contradicted claim, production outcome, blocker, next checkpoint, and record link.
- Render no Executive Summary, Timeline, or Evidence Register.
- Keep the card to at most nine field lines.
- Add one adaptive visual only when the structured visual context meets a router threshold.

### `follow-up`

- Use this automatic mode only when the stored comparison reports a material state, ownership, or evidence change.
- Put `Changed since last review` and `Unchanged blocker` before current state.
- Use the helper-computed delta; never reconstruct differences from memory.
- After the delta, render the same investigation-complete core as `standard`; do not discard flow, causal assessment, Timeline, or Evidence Register merely because history exists.

### `technical`

Render exactly this schema as `Field | Proof state | Value | Evidence basis`:

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

- Render the Investigation Progress flow and the durable-record link. Explicit flow intent always selects `progress-flow`, even when another adaptive visual is available.
- State that sequence arrows show chronology, not causal proof.
- Limit Mermaid flows to seven nodes.
- Keep observed, blocker, hypothesis, confirmed mechanism, mitigation, and pending states visually distinct.

### `full`

- Generate the complete view from the structured snapshot only when explicitly requested.
- Present Current Case Card, Investigation Progress flow, Causal Assessment, Problem Lineage, Technical Specification, Progress Milestones when present, Timeline, and Appendix A.
- Keep `Appendix A — Evidence Register` as the final section of this mode only.
- Do not manufacture an Executive Summary paragraph merely to lengthen the output.

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

- `technical_spec` — all twelve fixed fields, each containing `state`, `value`, and `evidence`.
- `problem_lineage` — original objective, intended action, blocker, working hypotheses, corrected finding, implemented action, outcome, and secondary problems.
- `milestones` — substantive state transitions only, oldest first.
- `timeline` — evidence-backed Date / By / Source / What changed rows, oldest first.
- `evidence_register` — dynamic `E1..EN` rows with date, source, verbatim evidence, and reverse mapping.
- `visual_context` — only evidenced transitions, recurrences, hypotheses, components/handoffs, or ownership checkpoints. Populate `transitions` whenever at least two substantive investigation states are evidenced; migrated snapshots may use the renderer's milestones/lineage fallback.

The durable-record payload keeps the existing `current`, `coverage`, and `evidence_digest` fields and adds this `presentation` object. A structured v2 payload does not require `full_review_markdown`.

## Deterministic Commands

After building the UTF-8 payload:

```text
python <skill-directory>/scripts/case_record.py update --input <payload.json>
python <skill-directory>/scripts/case_record.py present --case-id <Case ID> --request "<original user request>" --markdown-only
python <skill-directory>/scripts/case_record.py verify-final --case-id <Case ID> --input <candidate-final.md>
```

`present --markdown-only` emits only the canonical Markdown, writes `chat-output.md`, and writes its SHA-256 to `chat-output.sha256`. Put that exact proposed final response in a UTF-8 candidate file and run `verify-final` before completion. Return the verified candidate unchanged; do not manually shorten, expand, rewrite, or append a second report. A missing artifact, invalid artifact hash, or normalized mismatch must block completion. Normalization permits line-ending and final-newline transport differences only. JSON-mode `present` retains the auditable `mode` and `visual` fields.

## Non-Negotiable Acceptance

- Incomplete collection and zero evidence do not create or modify a record.
- Prior records are comparison baselines, never current evidence.
- Default and material follow-up chat output retain the investigation flow, causal assessment, Timeline, and complete dynamic Evidence Register.
- `compact` is explicit-only. No automatic follow-up may silently remove investigative context.
- Administrative closure remains separate from RCA and production outcome.
- Learning remains explicit-request and explicit-approval only.
