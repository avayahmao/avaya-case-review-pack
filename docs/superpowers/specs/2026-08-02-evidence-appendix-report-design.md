# Evidence Appendix Executive Report Redesign

**Date:** 2026-08-02
**Status:** Approved concept; written specification awaiting final review

## Context

The v1.4.0 report contract puts the Evidence section before the Verdict and repeats Evidence IDs throughout Verdict, Progress, Risk Flags, Ownership, Timeline, and Targeted Recommendations. VP feedback is that this interrupts the management reading path and makes the report feel like an audit record instead of an executive brief.

The redesigned report must preserve evidence discipline while making the main body clean, concise, and decision-oriented.

## Goals

1. Put the management conclusion and current case state before supporting detail.
2. Move all rendered evidence into one appendix table at the end of the report.
3. Remove all Evidence IDs and Evidence annotations from the report body.
4. Preserve a complete audit trail through reverse mapping in the appendix.
5. Remove `Risk Flags` and `Targeted Recommendations` completely so the Manager makes risk and action judgments.
6. Preserve the zero-evidence rule: when no verifiable case-specific evidence exists, output exactly `不知道`.

## Non-Goals

- Do not weaken the internal evidence ledger or allow unsupported conclusions.
- Do not add a replacement risk score, recommendation list, manager directive, or hidden action section.
- Do not turn domain reference guidance into case-specific evidence.
- Do not change CaseToMD or Gmail MCP implementations.
- Do not publish or assign a new release version as part of this design.

## Report Information Architecture

The rendered report uses this exact order:

1. **Case Header**
   - Case ID, title, status, priority, assignee, source, freshness clocks, and customer.
2. **Verdict**
   - One or two sentences stating Healthy, At Risk, Stalled, or `不知道`.
   - No Evidence IDs or source annotations.
3. **Technical & Incident Assessment**
   - Exactly one structure: multi-problem Problem Statement or single-issue Incident & RCA Summary.
   - Includes RCA state and mitigation maturity.
   - No recommendations and no inline evidence markers.
4. **Progress Summary**
   - Three to five substantive milestones, newest first.
   - Routine status pings remain excluded from display but continue to inform the substantive-progress clock.
5. **Ownership & Next Step**
   - Current assignee, last concrete action, stated next action, next-action owner, and next SLA/update due.
   - This section may only restate actions already present in evidence.
   - It must never generate a new recommendation.
6. **Timeline**
   - Substantive chronology only.
   - No Evidence column and no inline Evidence IDs.
7. **Appendix A — Evidence Register**
   - The final section in the report.
   - Contains every evidence item used by the body.

The headings `Risk Flags` and `Targeted Recommendations` must not appear anywhere in generated output.

## Evidence Appendix Contract

Use one table:

| Ref | Date | Source | Verbatim evidence / data | Supports |
|---|---|---|---|---|
| E1 | 2026-08-01 | Case activity | Exact excerpt or measured value | Verdict — At Risk; RCA — Suspected |
| E2 | 2026-08-01 | Gmail subject/message | Exact excerpt or measured value | Ownership — Next action; Progress — milestone |

Rules:

1. Evidence numbering remains dynamic: `E1..EN`.
2. Each row contains Source, Date, Verbatim evidence / data, and Supports.
3. `Supports` performs the reverse mapping. It names the body section and the exact conclusion or field supported by that row.
4. The body must contain no `[E1]`, `[Evidence 1]`, `Evidence N`, footnote, or source suffix.
5. Multiple evidence rows may support one conclusion.
6. One evidence row may support multiple conclusions when the source genuinely supports each one.
7. Evidence must not be split, duplicated, or invented to increase the count.
8. Domain references may explain a technical interpretation but do not count as case-specific evidence by themselves.

## Internal Evidence Gate

The agent still builds an internal claim-to-evidence ledger before rendering.

- Every factual body claim must map to at least one appendix row.
- Unsupported fields are rendered as `不知道`, `not stated`, or `unassigned`, as appropriate.
- When sources conflict, the relevant body field states that the conflict is unresolved; both source claims appear in the appendix.
- If no verifiable case-specific evidence exists, output exactly `不知道` and do not render the report or appendix.

The appendix changes presentation only. It does not lower the evidence standard.

## Manager-Judgment Boundary

The report may describe:

- current status and health verdict;
- observed blockers and customer impact inside the relevant narrative;
- evidence-backed RCA state and mitigation maturity;
- owners, commitments, due dates, and next steps already stated by case participants.

The report must not:

- label individual items as Risk Flags;
- rank or score risks;
- prescribe Manager or engineer actions;
- create Targeted Recommendations;
- infer an owner or deadline that is not present in evidence.

## Error and Edge-Case Handling

- **Zero evidence:** output exactly `不知道`.
- **Partial evidence:** complete supported fields and mark unsupported fields unknown.
- **Conflicting sources:** state the conflict without resolving it and include both rows in the appendix.
- **Gmail no results:** continue with CaseToMD evidence and disclose the source gap in the appendix or relevant factual narrative.
- **Required tool missing/failing:** stop and identify the unavailable server; do not fabricate a review.
- **Lab-only result:** retain `Lab Validated`; do not imply production resolution.

## Documentation and Test Impact

Implementation must update:

- `plugins/avaya-case-review/skills/case-review/SKILL.md`
- `README.md` and `README.html`
- Manager Onboarding Guide Markdown and HTML
- Technical Design Document Markdown and HTML
- Release Notes as an Unreleased change
- contract tests and regression scenario fixtures

Required regression checks:

1. Appendix is the final report section.
2. Evidence rows use the five required columns.
3. No inline Evidence ID appears in the report body template.
4. `Risk Flags` is absent from the output contract and current documentation.
5. `Targeted Recommendations` is absent from the output contract and current documentation.
6. Ownership contains only evidence-stated actions.
7. Zero evidence still produces exactly `不知道`.
8. Source conflict and lab-versus-production rules remain enforced.
9. Markdown and HTML descriptions remain semantically aligned.

## Acceptance Criteria

The redesign is complete when:

- the canonical SKILL template follows the seven-section order above;
- the report body has no scattered Evidence annotations;
- the final appendix table provides complete reverse traceability;
- Risk Flags and Targeted Recommendations are fully removed;
- all affected Markdown/HTML documentation describes the same structure;
- regression tests fail against the old layout and pass against the new layout;
- `git diff --check` and all contract validators pass.
