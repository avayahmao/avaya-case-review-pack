# Executive Summary and Technical Assessment Deduplication Design

**Date:** 2026-08-04

**Status:** Approved for implementation planning

## Problem

The current report asks both `Executive Summary` and `Technical & Incident Assessment` to cover the incident, affected scope, actions taken, root cause, mitigation, and status. The sections therefore repeat the same facts at different lengths without a reliable boundary between management conclusions and technical reasoning.

The report must remain useful to both VP/Manager readers and technical managers. It must also preserve the evidence gate, the final Evidence Appendix, adaptive ADM depth, and the rule that the report does not generate risk judgments or unsupported recommendations.

## Design Goals

1. Give management and technical readers a complete 6-8 sentence overview without requiring them to read the technical analysis first.
2. Make `Technical & Incident Assessment` explain the reasoning behind the summary instead of restating it.
3. Preserve single-issue and multi-problem report forms.
4. Integrate ADM coverage naturally into the technical section without appending a second, repetitive ADM report.
5. Keep all factual statements evidence-gated and reverse-mapped through the final Evidence Appendix.

## Non-Goals

- Do not restore `Risk Flags`, `Targeted Recommendations`, manager directives, or risk scores.
- Do not add inline Evidence IDs or citations to the report body.
- Do not change CaseToMD, Gmail MCP, Edge broker, or evidence-source authority rules.
- Do not generate new prevention recommendations. Only prevention controls already stated, committed, or implemented in evidence may be reported.

## Selected Approach: Layered Disclosure

`Executive Summary` owns conclusion-level information: what happened, why it matters, what was done, the headline technical conclusion, current outcome, and the next evidenced checkpoint.

`Technical & Incident Assessment` owns technical explanation: the environment, precise problem, findings, logs, causal mechanism, ruled-out paths, unresolved gaps, solution details, mitigation maturity, and validation scope.

The guiding boundary is:

> Executive Summary states the conclusion. Technical & Incident Assessment explains why that conclusion is justified.

## Section Ownership

| Information | Executive Summary | Technical & Incident Assessment |
|---|---|---|
| Event, time, location, affected scope | State once, concisely | Do not restate unless a detail is technically necessary |
| Business impact | One conclusion-level sentence | Do not repeat; technical consequences may be explained when necessary |
| Actions taken | Key response and outcome only | Exact actions, system locations, parameters, logs, and validation |
| Root cause | At most one sentence plus RCA state | Mechanism, evidence, uncertainty, ruled-out paths, and investigative direction |
| Mitigation | Current maturity and production outcome | Implementation details and validation scope |
| Next step | Next evidenced checkpoint, owner, and ETA | Missing technical evidence or validation path |
| Future prevention | Excluded | Existing evidence-backed prevention controls only; omit when absent |

## Executive Summary Contract

The section contains one natural-language paragraph of 6-8 sentences. It has no internal subheadings such as `Core Incident Details`, `Impact and Response`, or `Next Steps`.

The paragraph follows this order:

1. Event, date/time, and location.
2. Affected systems, assets, users, or teams.
3. Evidenced business or customer impact.
4. Key containment, diagnostic, or corrective response and its outcome.
5. One-sentence technical conclusion with the RCA state.
6. Mitigation maturity and confirmed production outcome.
7. Current case or incident status.
8. Next evidence-backed checkpoint, owner, and ETA when stated.

Required facts that are not supported by evidence use lowercase `unknown`. The paragraph must not contain raw log excerpts, detailed troubleshooting sequences, configuration parameters, extended cause analysis, or future-prevention content.

## Technical & Incident Assessment Contract

The technical section starts with problem clarification rather than another incident summary. Its content must add at least one of the following beyond the Executive Summary:

- environment or affected-component detail;
- a technical finding or interpreted log excerpt;
- causal reasoning or an RCA-state explanation;
- a ruled-out path, unresolved hypothesis, or missing validation;
- solution, workaround, implementation, or verification detail;
- evidence-backed prevention controls already present in the record.

If a paragraph only paraphrases an Executive Summary sentence without adding one of these elements, it is removed during reflection.

### Single-Issue Form

```markdown
## Technical & Incident Assessment

### Incident & RCA Summary
<Clarify the actual technical problem, then cover findings, cause analysis,
solution/mitigation details, validation scope, and unresolved technical gaps.>

<Existing prevention controls, only when evidenced.>
```

### Multi-Problem Form

```markdown
## Technical & Incident Assessment

### Problem 1 - <record or concise problem name>
<Problem clarification, findings, cause, solution/validation, and gaps.>

### Problem 2 - <record or concise problem name>
<Problem clarification, findings, cause, solution/validation, and gaps.>

<Existing prevention controls under the relevant problem, only when evidenced.>
```

The single-issue and multi-problem forms are mutually exclusive. Technical content may use natural paragraphs, short lists, or useful subheadings; it is not required to display four mechanical ADM headings.

## Adaptive ADM Behavior

When ADM is requested, it increases the depth of `Technical & Incident Assessment` only. It does not change the Executive Summary length and does not append another set of ADM sections after the report.

ADM dimensions map into the technical narrative as follows:

| ADM dimension | Integrated technical content |
|---|---|
| Details/Findings | Environment, context, symptoms, relevant logs, and discovered facts |
| Problem Clarification | Concise statement of the actual core technical problem |
| Cause | Mechanism, evidence, ruled-out paths, suspected cause, and investigation state |
| Solution | Fix, workaround, completed action, validation result, and next technical step |

All four dimensions must be covered when evidence permits, but their presentation remains adaptive to case complexity.

## Generation Flow

1. Build and normalize the case-specific evidence ledger.
2. Complete source-conflict analysis, RCA state, mitigation maturity, and single-versus-multi-problem classification.
3. Draft `Technical & Incident Assessment` from the evidence ledger.
4. Extract conclusion-level facts from the completed technical assessment and evidence ledger into the Executive Summary.
5. Run the deduplication reflection: remove technical paragraphs that merely restate the summary, and remove summary details that belong only in technical analysis.
6. Render remaining report sections and the final Evidence Appendix.

This order makes the technical reasoning the source for the headline conclusion instead of generating two independent narratives from the same raw evidence.

## Evidence and Unknown Handling

- Every factual statement in both sections must map internally to one or more appendix rows.
- An appendix row may support both a summary conclusion and its detailed technical explanation.
- The body remains free of Evidence IDs; `Supports` performs the reverse mapping.
- Missing required summary facts use lowercase `unknown`.
- The technical section explains the investigation state or missing evidence when that adds useful context; it does not repeat `unknown` without explanation.
- If no verifiable case-specific evidence exists, output exactly `unknown` and stop without rendering the report template.

## Documentation Impact

Implementation must keep these sources aligned:

- `plugins/avaya-case-review/skills/case-review/SKILL.md`
- `README.md` and `README.html`
- `docs/MANAGER_ONBOARDING_GUIDE.md` and `.html`
- `docs/TECHNICAL_DESIGN_DOCUMENT.md` and `.html`
- `docs/RELEASE_NOTES.md` and `.html`
- `docs/PRESENTATION.html` when it describes the report layout
- contract tests and scenario fixtures

## Verification Strategy

Contract tests must verify:

1. `Executive Summary` contains one paragraph and no former internal subheadings.
2. The summary contract specifies 6-8 sentences and excludes future-prevention content, raw logs, and detailed diagnostics.
3. Root cause is limited to one conclusion-level summary sentence; technical causal detail belongs to the assessment.
4. Technical assessment starts with problem clarification and must add technical detail rather than paraphrase the summary.
5. Single-issue and multi-problem forms remain mutually exclusive.
6. ADM expands technical depth without adding a duplicate four-section appendix.
7. Existing prevention controls appear only in the technical section and only when evidenced.
8. The Evidence Appendix remains last and reverse-maps both summary and technical conclusions.
9. The zero-evidence result remains exactly `unknown`.
10. Existing chronology, source-conflict, mitigation-maturity, and production-confirmation safeguards remain intact.

## Acceptance Criteria

The redesign is complete when:

- a mixed management and technical audience can understand the incident from the 6-8 sentence Executive Summary;
- the technical assessment adds explanation and proof without repeating the summary narrative;
- future prevention is absent from the Executive Summary;
- ADM produces deeper technical analysis without a second report structure;
- single-issue, multi-problem, partial-evidence, conflicting-source, and zero-evidence scenarios pass;
- repository and deployed runtime skill copies are synchronized; and
- the full automated test suite passes.
