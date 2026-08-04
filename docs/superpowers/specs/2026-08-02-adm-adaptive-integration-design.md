# Adaptive ADM Integration Design

**Date:** 2026-08-02
**Status:** Approved concept; written specification awaiting final review

> **Supersession/refinement note:** The report-placement details in this specification are superseded by [2026-08-04-executive-technical-dedup-design.md](2026-08-04-executive-technical-dedup-design.md). The ADM activation and evidence-boundary rules below remain applicable.

## Context

Avaya Diagnostic Methodology (ADM) requires thorough coverage of Details/Findings, Problem Clarification, Cause, and Solution. A fixed four-section appendix would make technical emails and management reports repetitive and mechanical. ADM must instead operate as an internal analysis framework whose content is naturally integrated into the existing output.

The current layered-disclosure report contract is the presentation baseline: one concise Executive Summary, technical reasoning and validation in Technical & Incident Assessment, no generated Risk Flags or Targeted Recommendations, and a final reverse-mapped Evidence Appendix.

## Goals

1. Activate deeper ADM analysis only when the user explicitly requests `ADM`.
2. Require coverage of all four ADM dimensions without requiring four fixed visible headings.
3. Adapt placement, headings, depth, and ordering to the requested output type and case complexity.
4. Preserve careful epistemic language: confirmed facts, working hypotheses, ruled-out paths, and pending validation must remain distinct.
5. Preserve the Evidence Appendix as the final audit layer for case-review outputs.
6. Keep standard non-ADM output on the current layered contract with standard technical depth.

## Non-Goals

- Do not append a rigid four-heading ADM block after every email.
- Do not expose an internal ADM checklist in the final response.
- Do not restore Risk Flags, Targeted Recommendations, manager directives, or risk scoring.
- Do not present suspected causes as confirmed root cause.
- Do not create owners, dates, remediation results, or log evidence that were not provided.
- Do not change CaseToMD or Gmail MCP implementations.

## Trigger

ADM mode activates when the user explicitly requests `ADM` or `Avaya Diagnostic Methodology`, case-insensitively.

Examples:

- “Review SR 1-234... in ADM format.”
- “Draft an ADM technical update.”
- “Use Avaya Diagnostic Methodology.”

Product names, case content, or the presence of diagnostic logs alone do not activate ADM mode.

## Internal ADM Coverage Model

When ADM mode is active, the agent performs an internal coverage pass across four dimensions:

| ADM dimension | Required analytical coverage |
|---|---|
| Details/Findings | Environment, topology, versions, problem context, impact, symptoms, reproduction conditions, chronology, logs, errors, tests, configuration, prior work, and source gaps |
| Problem Clarification | A concise statement of the actual core problem, separated from secondary symptoms, assumptions, and business impact |
| Cause | Confirmed causal evidence, suspected mechanisms, competing hypotheses, ruled-out paths and why, missing evidence, and the current investigative path |
| Solution | Fixes or workarounds already performed, observed results, mitigation maturity, unresolved gaps, planned validation, and the technical path being taken toward resolution |

All four dimensions must be covered somewhere in the final output when evidence permits. Unsupported content remains `unknown` or explicitly pending validation.

## Adaptive Rendering

ADM changes analytical depth, not the mandatory visible outline.

### Case Review

Integrate ADM coverage into the existing sections:

- **Executive Summary:** The Executive Summary remains one 6-8 sentence paragraph with conclusion-level incident, impact, response, a one-sentence RCA state or conclusion, mitigation, status, and next checkpoint. Future prevention is excluded from Executive Summary. An evidence-stated preventive next action may appear only as an existing checkpoint or current planned work, never as an agent recommendation or implemented control.
- **Technical & Incident Assessment:**
  - open with Problem Clarification;
  - integrate relevant Details/Findings;
  - express Cause through the existing RCA state and narrative;
  - express Solution through mitigation/resolution status and the current technical path;
  - include Existing prevention controls only under the relevant problem. Existing prevention controls require evidence confirming implementation.
- **Preventive work boundary:** Planned or committed preventive work remains an evidence-stated checkpoint or planned work, not a recommendation or an implemented control.
- **Progress Summary:** include diagnostic milestones, tests, ruled-out paths, and mitigation results.
- **Ownership & Next Step:** include only evidence-stated owners, commitments, validation work, and dates.
- **Timeline:** preserve substantive diagnostic chronology in ascending date/time order (oldest first); place undated entries last.
- **Appendix A — Evidence Register:** remain the final section and reverse-map all ADM-derived factual claims.

ADM increases the depth of Technical & Incident Assessment only; it does not append another set of ADM sections or make the Executive Summary longer. No top-level headings named `Details/Findings`, `Problem Clarification`, `Cause`, or `Solution` are required. The agent may use a contextual subheading when it improves readability, but it must not output a mechanical four-part form.

### Technical Email

Keep the email natural and concise:

1. brief issue summary and current state;
2. key findings and only the logs needed to support them;
3. technical assessment that distinguishes facts, hypotheses, and pending validation;
4. evidence-stated next steps, responsible team, and required validation when known.

ADM depth should appear through richer content inside those natural email sections. Do not append a second four-section ADM report after the email or duplicate ADM content outside the natural email structure.

If the requested response combines a management review and a technical email, avoid duplicate content. The email should summarize the result; the case-review body carries the fuller ADM analysis and the Evidence Appendix remains last.

## Cause Contract

The Cause coverage must use evidence-status language:

- **Confirmed:** use only when evidence demonstrates causation.
- **Suspected:** explain the technical mechanism and the evidence supporting it.
- **Ruled Out:** state what was tested or observed and why it weakens that path.
- **Unknown / Under Investigation:** explain the missing evidence and current investigation path.
- **Correlation only:** state the relationship without implying causation.

Even in detailed ADM mode, verbosity must not increase certainty.

## Solution Contract

Solution coverage is descriptive rather than prescriptive:

- document fixes, workarounds, configuration changes, rollbacks, or tests already performed;
- distinguish Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, and None Active;
- state the validation or investigative path already underway;
- state evidence-backed technical next steps when they are part of the case or requested ADM investigation;
- do not generate a separate recommendation list or manager directive.

Unknown solution state must still explain what is blocking resolution and what evidence is needed next.

## Evidence Contract

- Every factual ADM claim maps internally to at least one evidence row.
- The body remains citation-free.
- The final Evidence Appendix uses `Ref | Date | Source | Verbatim evidence / data | Supports`.
- Rendered ADM chronology and dated evidence rows are ordered by date/time ascending; undated rows follow dated rows.
- `Supports` may map a row to an ADM concept and rendered conclusion, such as `Cause — Suspected retry race` or `Solution — Lab Validated`.
- Domain references may support interpretation but do not prove case-specific facts.
- If no verifiable case-specific evidence exists, output exactly `unknown`.

## Depth and Readability

An explicit ADM request asks for high diagnostic depth, but the response should remain usable:

- consolidate repeated environment facts;
- quote only decisive log lines and preserve timestamps/errors;
- put lengthy raw logs in attachments or the source record rather than duplicating them;
- scale detail to case complexity;
- use tables only when they improve comparison or chronology;
- prefer natural professional language over checklist prose.

## Error and Edge Cases

- **ADM requested with sparse evidence:** provide the supported context, identify gaps, and mark Cause/Solution unknown without speculation.
- **Conflicting sources:** preserve the conflict, avoid resolving it without stronger evidence, and map both claims in the appendix.
- **No email requested:** apply ADM depth to the case review without inventing an email.
- **Email-only request:** integrate ADM naturally into the email; do not require the case-review template.
- **Required MCP unavailable:** stop and identify the missing server.
- **Lab success only:** do not imply production resolution.
- **No ADM request:** use the current layered contract with standard technical depth and no extra ADM depth requirement.

## Documentation and Test Impact

Implementation must update:

- `plugins/avaya-case-review/skills/case-review/SKILL.md`
- `README.md` and `README.html`
- Manager Onboarding Guide Markdown and HTML
- Technical Design Document Markdown and HTML
- Release Notes as an Unreleased change
- contract tests and ADM regression scenarios

Required regression checks:

1. Explicit `ADM` request activates all four internal coverage dimensions.
2. Non-ADM requests remain unchanged.
3. No test requires four fixed rendered ADM headings.
4. Case-review ADM content maps into existing sections.
5. Email ADM content follows a natural email structure.
6. Cause status distinguishes Confirmed, Suspected, Ruled Out, Unknown, and correlation.
7. Solution preserves mitigation maturity and does not recreate a recommendation section.
8. Evidence Appendix remains last for case-review output.
9. Zero evidence still produces exactly `unknown`.
10. Markdown and HTML documentation remain semantically aligned.

## Acceptance Criteria

The design is complete when:

- ADM acts as an adaptive reasoning overlay rather than a rigid template;
- all four ADM dimensions are internally covered when requested;
- existing report/email structures remain natural and readable;
- Cause and Solution preserve evidence boundaries;
- standard output is unchanged when ADM is absent;
- current documentation describes the same conditional behavior;
- regression tests fail against the pre-ADM contract and pass after implementation;
- all validators and `git diff --check` pass.
