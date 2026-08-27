---
name: "qa"
description: "Select, score, validate, and summarize monthly Avaya case-quality assessments using evidence-backed Diagnostic & Solution, Service & Communication, and Plus standards."
---

# Case Review QA

Use this skill when the user explicitly asks to perform monthly QA, score case quality, validate QA data, calculate QA statistics, or provides a table with the QA rubric columns.

QA is a management assessment layer. It does not replace the evidence-gated case review and its scores do not prove RCA, mitigation, production recovery, or customer outcome.

## Operating modes

- **Validate supplied QA:** preserve the supplied cases and assess schema, bounds, totals, and summaries. Do not silently rescore management judgments.
- **Perform QA from a workload report:** select cases using the monthly rules below, collect complete case evidence, assign scores, and produce the requested table or workbook.

## Monthly case selection

1. Use `Closed Date` to determine the requested month and include only completed/closed cases.
2. Exclude canceled or administratively non-reviewable tickets. This includes `Status = Cancelled` and closure/status reasons such as `NO RESPONSE`, `CUSTOMER CANCELLED`, `NO LONGER REQUIRED`, `DUPLICATE TICKET`, `LACKS DATA TO DIAGNOSE`, or an equivalent closure without a reviewable technical assessment. A displayed status of `Completed` does not override an ineligible closure reason; for example, `1-23694701942` is ineligible because it closed for `NO RESPONSE`.
3. Select the two most recently closed eligible cases for each engineer. Do not cherry-pick cases based on expected score.
4. Exclude alarm cases. Treat a case as an alarm case when its primary purpose is alarm handling or alarm clearance, even if the workload row is mislabeled `Non-Alarm`. A non-alarm case may mention alarms as supporting evidence when its primary customer problem is different.
5. If an engineer has fewer than two eligible non-alarm cases, do not substitute alarm cases, canceled/non-reviewable cases, or cases from another month. Report the coverage gap.
6. Use lowercase source usernames: `Assigned To Login` for `Name` and `Manager Login` for `Manager`. Do not derive a username from a display name; use `unknown` when the source login is unavailable.

## Required output fields

Each entry contains:

- `Name`: lowercase engineer username
- `Manager`: lowercase manager username
- `Case ID`
- `Product`: source-supported product, otherwise blank or `not stated` according to the output format
- `Diagnostic & Solution`: integer from 0 through 5
- `Service & Communication`: integer from 0 through 3
- `Plus`: integer from 0 through 5
- `score`: calculated as the sum of the three dimensions; maximum 13
- `Problem`: concise statement of the primary customer problem
- `efforts`: evidence-backed technical and service actions performed by the engineer
- `comments`: concise management assessment; mandatory when `Diagnostic & Solution < 5`, `Service & Communication < 3`, or `Plus > 0`

For spreadsheet output, preserve this exact column order:

```text
Name | Manager | Case ID | Product | Diagnostic & Solution (0-5) | Service & Communication (0-3) | Plus (0-5) | score | Problem | efforts | comments
```

## Scoring standards

The normal fully solved case is `5 + 3 + 0 = 8`. Plus points are exceptional; they are not needed for a strong routine case.

### Diagnostic & Solution (0-5)

- **5:** Evidence supports the cause, working-as-designed conclusion, or technical boundary, and the engineer provides an actionable solution or verified fix. Strong evidence includes traces/logs, good-versus-bad comparison, KB/PSN matching, lab reproduction, source-code analysis, or an end-to-end technical proof.
- **4:** Analysis is technically useful and substantially correct, but the solution is unconfirmed/declined, the evidence chain is incomplete, or the response does not fully address the customer's concern.
- **3:** A plausible diagnosis or useful recovery action is documented, but causal evidence or durable validation is limited.
- **2:** The record shows only a basic check, workaround, reboot, or recovery confirmation without explaining the mechanism.
- **1:** Only a minimal technical action or closure statement is attributable to the engineer.
- **0:** No relevant technical contribution is supported.

Do not award diagnostic credit merely for assignment, escalation, case closure, alarm clearance, or a replacement being available.

### Service & Communication (0-3)

- **3:** Timely ownership, clear customer/BP communication, useful progress updates, coordination where needed, and an understandable closure outcome.
- **2:** Service is acceptable but communication is delayed, reactive, incomplete, or the case remains open longer than the technical work justifies.
- **1:** Minimal customer-facing communication or ownership is visible.
- **0:** No meaningful service or communication contribution is supported.

### Plus (0-5)

Award one point for each distinct, evidenced contribution beyond what is already expected for a `5/3` case. Examples include:

- resolving a complex issue under material time or customer pressure;
- exceptional ownership that moves a stalled case forward;
- substantive cross-product or cross-team cooperation;
- resolving an additional customer concern beyond the original problem;
- reproducing the issue in a lab or identifying a product/code defect;
- comprehensive end-to-end analysis proving a non-Avaya boundary;
- restoring a critical service or resolving an issue prior shifts/teams could not resolve.

Do not double-count the same action under multiple Plus reasons. Speed, severity, escalation, White Glove status, or customer pressure alone does not earn a point. State every awarded reason in `comments`.

## Evidence and writing rules

- When assigning new scores, first complete the case-review evidence workflow for each selected primary Case ID, including CaseToMD and exhaustive exact-primary-ID Gmail collection. A zero-result Gmail query is complete only when the collection reports completion.
- Score only work attributable to the named engineer. Work performed by another engineer may provide case context but does not earn the selected engineer credit.
- Use `unknown` for unsupported cause or production outcome; do not convert hypotheses, routing activity, mitigation, or closure into proof.
- Keep `Problem` short and customer-centered. Put the engineer's actual analysis, coordination, solution, and validation in `efforts`.
- Use `comments` for the management judgment: completeness, communication quality, timeliness, customer acceptance, evidence gaps, and explicit Plus rationale.

### Comments writing standard

Write comments in the short, practical style used by the manager examples. Prefer one line of plain management language or short semicolon-separated phrases. A comment interprets the case quality; it does not repeat the `Problem`, rewrite `efforts`, quote logs, or retell the investigation.

- A comment is mandatory whenever `Diagnostic & Solution` is below 5, `Service & Communication` is below 3, or `Plus` is above 0. The comment must explain every applicable deduction and award. One comment may cover multiple reasons.
- A `5 / 3 / 0` row may have a blank comment, although a concise outcome statement is still useful.
- Keep the score explanation very short—normally only the decisive missing proof, communication gap, or exceptional contribution. Examples: `root cause not confirmed`, `delayed update`, `cross-product coordination`, or `solution confirmed`.
- Use consistent signed notation at the start of each scoring explanation:
  - `Diagnostic & Solution -N: <reason>`, where `N = 5 - Diagnostic & Solution`.
  - `Service & Communication -N: <reason>`, where `N = 3 - Service & Communication`.
  - `Plus +1: <reason>` once for each awarded Plus point. For Plus 2, write two distinct `Plus +1:` reasons rather than one combined `+2` reason.
- Do not write `reduced by one`, `minus one`, `(+1)`, or another notation variant. Use the signed forms above consistently.
- Use the same direct tone as the examples: `solved quickly`, `solid TS`, `solution confirmed`, `working as designed`, or `BP did not confirm`. Add only the short signed reason needed to audit a deduction or Plus point.
- Avoid polished report prose, long chronology, repeated evidence, or detailed causal explanation in `comments`; those belong in `efforts`.
- Lead with the most important judgment: confirmed result, evidence strength, customer outcome, or principal gap.
- Explain why the row differs from the normal `5 / 3 / 0 = 8`. For a lower score, identify the specific diagnostic or communication limitation. For a higher score, identify each exceptional contribution.
- Map Plus points explicitly and audibly using one `Plus +1:` segment per evidenced contribution.
- State validation limits directly: `BP did not confirm the outcome`, `customer declined the requested evidence`, or `recovery was observed but RCA remains unproven`.
- Mention speed only when it is meaningful in context. `Solved quickly` alone is not a sufficient comment or Plus rationale.
- Keep criticism factual and non-accusatory. Describe the observable delay or gap rather than judging the person.
- Do not claim RCA, customer acceptance, production recovery, or cross-team contribution unless the evidence supports it.

Useful comment patterns include:

- `Diagnostic & Solution -1: root cause not confirmed`
- `Diagnostic & Solution -1: BP did not confirm the trace-based solution`
- `Service & Communication -1: took one month to close; Plus +1: addressed an additional concern`
- `Plus +1: reproduced in lab and identified product defect`
- `Plus +1: comprehensive analysis proved issue was outside Avaya`
- `Service & Communication -1: email-only communication delayed progress`

For supplied historical QA, preserve the original comment unless the user asks for rewriting. A blank comment is invalid when any mandatory-comment condition applies. Flag unclear, contradictory, or unsupported comments as data-quality issues.

## Data consistency

- Always calculate `score = Diagnostic & Solution + Service & Communication + Plus`.
- Reject out-of-range dimensions and conflicting supplied totals; do not silently preserve invalid examples.
- Reject a row with a blank comment when `Diagnostic & Solution < 5`, `Service & Communication < 3`, or `Plus > 0`. A non-empty comment must explicitly justify each applicable minus or Plus score.
- Reject comments that do not use the exact signed notation or whose signed values do not reconcile to the score dimensions. Each Plus point requires its own `Plus +1:` reason.
- Blank dimension cells mean the row is unscored, not zero. A row with blank dimensions and score `0` is incomplete and must be flagged rather than included in averages.
- If `comments` awards `+1` but `Plus` is `0`, flag the row for correction even when the numeric total is otherwise arithmetically valid.
- A row showing `5 / 5 / 2` with score `10` is invalid because Service & Communication cannot exceed 3. It becomes `5 / 3 / 2 = 10` only after the value is explicitly corrected.
- A row showing `5 / 3 / 0` with score `9` and a documented `+1` is inconsistent: either Plus must be 1 or the score must be 8.

## Workflow

1. Determine whether the user supplied fixed QA rows or asked the skill to select cases from a workload report.
2. Apply the relevant selection and evidence rules, then normalize the column names.
3. Validate every entry and calculate its score.
4. Report the overall count, average, minimum, maximum, and dimension averages.
5. Report grouped summaries by engineer and manager, retaining source username relationships.
6. Render the complete entry table with `Problem`, `efforts`, and `comments`.

For validation or summary of an existing QA file, use:

```text
python <plugin-directory>/skills/case-review/scripts/qa.py report --input <qa.csv|qa.json|qa.md>
```

The parser accepts JSON arrays, CSV, and GitHub-style Markdown tables using the example column names. Use `validate` when the user asks for data-quality checking only, and `score` for one entry. Preserve `Problem` and `efforts` in the final table even when the numeric validator is used separately.

Do not assign a pass/fail threshold, ranking, performance-management action, or recommendation unless the user supplies that policy explicitly.
