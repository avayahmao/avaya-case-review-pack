---
name: "qa"
description: "Select, score, validate, and summarize monthly Avaya case-quality assessments using evidence-backed Diagnostic & Solution, Service & Communication, and item-based Technical Plus standards."
---

# Case Review QA

Use this skill when the user explicitly asks to perform monthly QA, score case quality, validate QA data, calculate QA statistics, or provides a table with the QA rubric columns.

QA is a management assessment layer. It does not replace the evidence-gated case review and its scores do not prove RCA, mitigation, production recovery, or customer outcome.

Alarm tickets are out of scope for this skill. Route explicit alarm QA or alarm-ticket audit requests to the separate `alarm-audit` skill.

## Operating modes

- **Validate supplied QA:** preserve the supplied cases and assess schema, reviewability, bounds, totals, comments, and summaries. When the user asks only to validate supplied scores, do not collect case evidence or silently rescore management judgments.
- **Assign or rescore supplied cases:** collect fresh complete case evidence for every primary Case ID before assigning any score. Produce QA output only; do not generate a case-review report or durable case record unless the user also asks for one.
- **Perform QA from a workload report:** select cases using the monthly rules below, collect fresh complete case evidence, assign scores, and produce the requested table or workbook.

## Reviewability gate

Classify every candidate as `Reviewable` or `Not Reviewable` before scoring.

- **Reviewable:** substantive technical or service work is attributable to the named engineer and the available evidence is sufficient to judge that work. An unknown customer outcome does not make the work unreviewable.
- **Not Reviewable:** use one of these factual reason categories: `No substantive engineer activity`, `Duplicate / administrative / standby`, `Cancelled before assessable work`, or `Insufficient attributable evidence`.
- `Not Reviewable` requires a concise, factual `Reviewability Reason`. Leave all three dimensions and `score` blank and exclude the row from every score average, minimum, maximum, ranking, and score distribution.
- Customer or BP nonresponse alone is not a reason for `Not Reviewable` when substantive attributable work exists. Third-party involvement alone is also not a reason: boundary isolation, evidence collection, and a correct handoff may remain reviewable.
- Use `Insufficient attributable evidence` only after required source collection completes. A tool, authentication, pagination, or other collection failure is `Context collection incomplete`, not a judgment that the case itself is unreviewable.
- Do not use numeric zero as a substitute for `Not Reviewable`. A reviewable case may receive a zero in a dimension only when the evidence supports that score.

## Monthly case selection

1. Use `Closed Date` to determine the requested month and include only completed/closed cases.
2. Apply the reviewability gate to candidates in newest-first order. Do not classify a case from its closure label alone: `NO RESPONSE`, customer cancellation, or third-party involvement may still leave substantive attributable work to assess, while a displayed status of `Completed` does not make an administrative or evidence-empty case reviewable.
3. Select the two most recently closed `Reviewable` cases for each engineer. Do not cherry-pick cases based on expected score. Retain evaluated `Not Reviewable` candidates with their reasons for coverage reporting, but do not let them consume the two-case quota.
4. Exclude alarm cases. Treat a case as an alarm case when its primary purpose is alarm handling or alarm clearance, even if the workload row is mislabeled `Non-Alarm`. A non-alarm case may mention alarms as supporting evidence when its primary customer problem is different.
5. If an engineer has fewer than two reviewable non-alarm cases, do not substitute alarm cases, `Not Reviewable` cases, or cases from another month. Report the coverage gap.
6. Use lowercase source usernames: `Assigned To Login` for `Name`, `Manager Login` for `Manager`, and the source auditor login for `Auditor` when supplied. Do not derive a username from a display name; use `unknown` when a required `Name` or `Manager` login is unavailable, and leave an unavailable optional `Auditor` blank.

## Required output fields

Each entry contains:

- `Name`: lowercase engineer username
- `Manager`: lowercase manager username
- `Case ID`
- `Product`: source-supported product, otherwise blank or `not stated` according to the output format
- `Auditor`: lowercase source auditor username when supplied; otherwise blank
- `Reviewability`: exactly `Reviewable` or `Not Reviewable`
- `Reviewability Reason`: blank for `Reviewable`; required and factual for `Not Reviewable`
- `Diagnostic & Solution`: integer from 0 through 5 for `Reviewable`; blank for `Not Reviewable`
- `Service & Communication`: integer from 0 through 3 for `Reviewable`; blank for `Not Reviewable`
- `Plus` / `Technical Plus`: integer from 0 through 5 for `Reviewable`, calculated from demonstrated item allocations; blank for `Not Reviewable`
- `score`: calculated as the sum of the three dimensions for `Reviewable`, maximum 13; blank for `Not Reviewable`
- `Problem`: a short, simple-English phrase stating the customer request or symptom; do not repeat the product as a routine prefix
- `efforts`: concise evidence-backed sentences stating the attributable action, key finding, and result or validation limit
- `comments`: concise criterion-based management judgment; mandatory when `Diagnostic & Solution < 5`, `Service & Communication < 3`, or `Plus > 0`

For spreadsheet output, preserve this exact column order:

```text
Name | Manager | Case ID | Product | Auditor | Reviewability | Reviewability Reason | Diagnostic & Solution (0-5) | Service & Communication (0-3) | Plus (0-5) | score | Problem | efforts | comments
```

## Input normalization and wording

- Normalize source-login fields to lowercase, trim repeated or leading/trailing whitespace, correct obvious spelling and encoding errors, and normalize textual not-applicable markers to `N/A`; score cells remain blank for `Not Reviewable`.
- Keep one logical case per row. Quote embedded line breaks and delimiters correctly when using CSV/TSV so they cannot split or shift fields.
- Write `Problem` as a concise English phrase, normally about 3-12 words. Start with the request or symptom, not a product-name label or report sentence. The `Product` column already carries the product. Good examples: `New SIP trunk returned 403`, `Lost SAL login access`, and `Scheduled remote backups failed`. Mention a product or component only when it is needed to understand the issue, not as a repeated prefix. Do not embed a diagnosis or assumed cause.
- Write `efforts` in simple English using the useful parts of `action -> finding -> result/validation`. Use one to three short direct sentences. Start with the work or case-specific fact, not the evidence source. Do not emit field labels such as `Reviewed:`, `Observed:`, `Action:`, or `Validation:`. Do not use source-led templates such as `Case history and matched emails show`, `ServiceNow record shows`, or similar wording. Source completeness belongs to the evidence workflow, not the management row. Do not turn requested, planned, or unavailable evidence into completed work.
- Write `comments` as a short natural management judgment. Use the exact signed notation below for every deduction and Plus award, but place those machine-checkable tokens after the plain-English judgment, preferably in parentheses. When material, include a short `RCA:` or `Outcome:` state supported by the evidence.
- Never preserve vague judgments such as `sounds good`, `fair enough`, `job done`, `convinced conclusion`, or similar wording. Replace them with the specific criterion met, evidence gap, service behavior, or validated outcome.

## Example-led calibration

When the supplied workload or QA workbook includes scored examples, use them as the local benchmark for both scoring and writing before completing new rows.

- Compare like cases and compare each dimension separately. A total-score gap does not establish that every dimension is too strict. Inspect Diagnostic, Service, and Plus distributions independently and review the below-full cases that create the gap.
- Use examples and cross-auditor distributions as calibration evidence, not as a target average. Do not raise a score merely to match another auditor's mean, median, full-score rate, or ranking.
- Retain the evidence gate. A permissive example cannot turn assignment, routing, a restart alone, missing notes, another engineer's work, or an unsupported customer statement into a complete technical solution.
- Calibrate Diagnostic consistently:
  - `5` when the named engineer completed the evidenced technical objective, or established a supported product/technical boundary with a clear correct next owner or action. Do not deduct merely because a downstream team performs the next step after the engineer completed the assigned boundary objective.
  - `4` for strong, substantially complete work with one material proof, attribution, recovery, cause, or durability gap. Treat an unknown production outcome as a material gap only when the actual case objective requires that outcome.
  - `3` for a targeted check, useful recovery action, or correct handoff with limited mechanism or no established final result.
  - `1-2` when only a basic action, evidence request, restart, routing, or closure statement is attributable and no useful diagnosis/result is established.
- Calibrate Service and Plus on their own evidence. Do not use Service or Plus to compensate for a Diagnostic distribution difference. Keep Plus exceptional and item-based.
- Preserve `Not Reviewable` and `Context collection incomplete` states during calibration unless new complete evidence changes the reviewability facts.

## Scoring standards

The normal fully solved case is `5 + 3 + 0 = 8`. Plus points are exceptional; they are not needed for a strong routine case.

### Diagnostic & Solution (0-5)

- **5:** The work completely satisfies the evidenced case objective for its type. For an information request, the answer is complete, accurate, and grounded in an authoritative source. For an incident, evidence supports the technical isolation or solution, and any claimed recovery or RCA has the required validation. For a planned change, the procedure is correct, execution is attributable, and the result is validated. A working-as-designed conclusion or technical boundary also requires supporting evidence and a clear next action when one remains; a correctly completed boundary objective does not require the named engineer to perform another team's downstream work.
- **4:** Analysis and action are strong and substantially complete, but one material proof gap remains. Recovery with unresolved cause or durability is normally 4 when the rest of the investigation is strong; state the unresolved limit explicitly.
- **3:** The engineer provides a useful partial diagnosis, recovery action, or technical contribution, but evidence linkage is limited, contribution to the final solution is incomplete, or the case is handed off before the outcome is established.
- **2:** The record shows only a basic check, workaround, reboot, or recovery confirmation without explaining the mechanism.
- **1:** Only a minimal technical action or closure statement is attributable to the engineer.
- **0:** No relevant technical contribution is supported.

Tentative guesses, self-recovery, restart alone, an uncorrelated KB match, requested or planned evidence, administrative/automatic closure, or troubleshooting with no result cannot support 5. The narrow exception is a case whose actual objective was only to define the correct next diagnostic step and where that step is complete, technically justified, and clearly owned. Do not award diagnostic credit merely for assignment, escalation, case closure, alarm clearance, or a replacement being available.

### Service & Communication (0-3)

- **3:** The engineer-controlled record shows timely ownership, clear customer/BP communication, useful progress updates, correct coordination or handoff, a named next owner when work remains, and an understandable closure position.
- **2:** Service is generally acceptable but one material, documented gap exists, such as a delayed update, missed commitment, unclear next owner, or failure to create or transfer the correct follow-up.
- **1:** A major or repeated ownership/communication lapse is evidenced, or only minimal customer-facing service is attributable to the engineer.
- **0:** No meaningful service or communication contribution is supported.

Score only behavior the engineer controlled. Customer/BP nonresponse alone does not justify a deduction after timely follow-up and a clear closure notice. Correct technical-boundary isolation plus a properly owned handoff remains reviewable and may satisfy the service standard; leaving the customer to find the next owner does not.

### Technical Plus / Extra Mile (0-5) — Item-Based Additive Scoring

Calculate Technical Plus by identifying specific, evidenced technical value-add items demonstrated during the case.

- **Default per item:** `+1` for each demonstrated item.
- **Outstanding item:** `+2` or `+3` for one item only when execution of that specific item was exceptionally outstanding. State what made it outstanding; do not award multiple points merely because the case was severe or urgent.
- **Baseline core work:** `0` for ordinary speed, expected product knowledge, a standard workaround or document, routine data/configuration correction, normal cross-team contact, or any other core role competence.
- **Cumulative maximum:** add all item allocations, capped at `5`.

Technical Plus item menu:

1. **Code Defect Discovery:** identified or isolated a software bug or code defect.
2. **Infrastructure & Hypervisor Isolation:** isolated a complex outage to customer infrastructure, hypervisor, network, storage, or sizing rather than product software.
3. **Cross-Product Integration:** performed substantive troubleshooting across product/system boundaries such as CM, AES, Session Manager, AEP, or third-party components.
4. **Customer Pressure & Ownership:** handled high executive/customer pressure with strong end-to-end technical ownership. Default `+1`; reserve `+2` or `+3` for exceptionally outstanding execution of this item.
5. **Scope Extension:** solved a secondary unlogged customer concern or produced a solution under a tight SLA/time constraint beyond the original scope.
6. **Trace Package Hygiene:** produced an exceptionally well-organized and documented trace/log package for handoff or escalation.

Scoring examples:

- **0:** no extra item; examples include `solved quickly`, `fix a corruption`, or routine NAR/single-shift troubleshooting.
- **1:** one standard item, such as identifying a code defect or delivering materially faster restoration with evidenced impact beyond the ordinary expectation.
- **2:** two standard items (`+1 +1`) or one exceptionally outstanding item (`+2`).
- **3:** a multi-item/outstanding combination, such as Cross-Product Integration `+1` plus exceptionally strong Customer Pressure & Ownership `+2`.
- **4-5:** cumulative achievement across several independently evidenced items.

Do not double-count the same action under different menu items or reuse work already required for a base score. Severity, escalation, White Glove status, speed, product knowledge, a workaround, documentation, or customer pressure alone earns `0`. A reusable knowledge artifact or materially faster restoration earns Plus only when its exceptional impact is demonstrated and it maps to an existing item such as Scope Extension or Trace Package Hygiene. State the item, allocation, and concise evidence in `comments`.

## Evidence and writing rules

- When assigning new scores, first complete the case-review evidence workflow for each selected primary Case ID, including CaseToMD and exhaustive exact-primary-ID Gmail collection. A zero-result Gmail query is complete only when the collection reports completion.
- Score only work attributable to the named engineer. Work performed by another engineer may provide case context but does not earn the selected engineer credit.
- Use `unknown` for unsupported cause or production outcome; do not convert hypotheses, routing activity, mitigation, or closure into proof.
- Keep `Problem` short and customer-centered. Put the engineer's actual analysis, coordination, solution, and validation in `efforts`.
- Use `comments` for the management judgment: completeness, communication quality, timeliness, customer acceptance, evidence gaps, and explicit Plus rationale.

### Comments writing standard

Write comments in the short, practical style used by the manager examples. Prefer one or two short plain-English sentences. A comment interprets the case quality; it does not repeat the `Problem`, rewrite `efforts`, quote logs, or retell the investigation.

- A comment is mandatory whenever `Diagnostic & Solution` is below 5, `Service & Communication` is below 3, or `Plus` is above 0. The comment must explain every applicable deduction and award. One comment may cover multiple reasons.
- A `5 / 3 / 0` row may have a blank comment, although a concise outcome statement is still useful.
- Keep the score explanation very short—normally only the decisive missing proof, communication gap, or exceptional contribution. Examples: `root cause not confirmed`, `delayed update`, `cross-product coordination`, or `solution confirmed`.
- For newly generated or rewritten QA, state the natural judgment first and place each exact signed token at the end, preferably in parentheses. Historical supplied QA may retain token-first wording when the user did not request a rewrite. The required tokens are:
  - `Diagnostic & Solution -N: <reason>`, where `N = 5 - Diagnostic & Solution`.
  - `Service & Communication -N: <reason>`, where `N = 3 - Service & Communication`.
  - `Plus +N: <item> — <reason>` for each demonstrated item, where `N` is `1`, `2`, or `3`. The allocations must sum exactly to the Plus score.
- Do not write `reduced by one`, `minus one`, `(+1)`, or another notation variant. Use the signed forms above consistently.
- Use factual, criterion-based language. Do not retain a source comment merely because it sounds positive or decisive; rewrite vague shorthand into the observed quality, gap, or validation state.
- Avoid polished report prose, long chronology, repeated evidence, or detailed causal explanation in `comments`; those belong in `efforts`.
- Lead with the most important judgment: confirmed result, evidence strength, customer outcome, or principal gap.
- Explain why the row differs from the normal `5 / 3 / 0 = 8`. For a lower score, identify the specific diagnostic or communication limitation. For a higher score, identify each exceptional contribution.
- Map Technical Plus explicitly by item. Use separate signed segments for separate items; one outstanding item may use `Plus +2:` or `Plus +3:` with a short explanation of why that item was exceptional.
- State validation limits directly: `BP did not confirm the outcome`, `customer declined the requested evidence`, or `recovery was observed but RCA remains unproven`.
- Mention speed only when it is meaningful in context. `Solved quickly` alone is not a sufficient comment or Plus rationale.
- Keep criticism factual and non-accusatory. Describe the observable delay or gap rather than judging the person.
- Do not claim RCA, customer acceptance, production recovery, or cross-team contribution unless the evidence supports it.

Useful generated-comment patterns include:

- `Service recovered, but cause and durability remain unknown. (Diagnostic & Solution -1: cause and durability remain unknown)`
- `BP did not confirm the trace-based solution. (Diagnostic & Solution -1: outcome not confirmed)`
- `Closure took one month. An additional concern was also addressed. (Service & Communication -1: delayed closure) (Plus +1: Scope Extension — addressed an additional concern)`
- `The issue was reproduced in the lab and identified as a product defect. (Plus +1: Code Defect Discovery — reproduced and identified the defect)`
- `The issue was isolated outside Avaya. (Plus +1: Infrastructure & Hypervisor Isolation — isolated the customer infrastructure fault)`
- `Recovery was led end to end under executive pressure. (Plus +2: Customer Pressure & Ownership — led exceptional recovery)`
- `The response missed the agreed update interval. (Service & Communication -1: two-week response delay)`

For supplied historical QA, preserve the original comment unless the user asks for rewriting. A blank comment is invalid when any mandatory-comment condition applies. Flag unclear, contradictory, or unsupported comments as data-quality issues.

## Data consistency

- Require `Reviewability Reason` for `Not Reviewable` and keep it blank for `Reviewable`.
- For `Reviewable`, require all dimensions and calculate `score = Diagnostic & Solution + Service & Communication + Plus`.
- For `Not Reviewable`, require all dimensions and `score` to be blank and exclude the row from score statistics.
- Reject out-of-range dimensions and conflicting supplied totals; do not silently preserve invalid examples.
- Reject a row with a blank comment when `Diagnostic & Solution < 5`, `Service & Communication < 3`, or `Plus > 0`. A non-empty comment must explicitly justify each applicable minus or Plus score.
- Reject comments that do not use the exact signed notation or whose signed values do not reconcile to the score dimensions. Technical Plus allocations may be `+1`, `+2`, or `+3` per item and must sum exactly to the Plus score.
- Blank dimension cells mean the row is unscored, not zero. A `Reviewable` row with blank dimensions is incomplete. A row with blank dimensions and score `0` is invalid even when it is `Not Reviewable`; the total must be blank.
- If `comments` awards `+1` but `Plus` is `0`, flag the row for correction even when the numeric total is otherwise arithmetically valid.
- A row showing `5 / 5 / 2` with score `10` is invalid because Service & Communication cannot exceed 3. It becomes `5 / 3 / 2 = 10` only after the value is explicitly corrected.
- A row showing `5 / 3 / 0` with score `9` and a documented `+1` is inconsistent: either Plus must be 1 or the score must be 8.

## Workflow

1. Determine whether the user requested validation-only, assignment/rescoring of supplied cases, or selection from a workload report. If scored examples are supplied, benchmark their score distribution and writing style before generating new rows.
2. For assignment or rescoring, perform a fresh CaseToMD retrieval and exhaustive primary-raw-ID Gmail collection under one fresh Gmail snapshot for each case. Do not reuse a prior case-review result as the evidence corpus.
3. Apply the monthly selection rules when relevant, then apply the reviewability gate before scoring.
4. Apply the example-led calibration rules by dimension without forcing score-distribution parity.
5. Normalize every entry to the exact output schema and simple-English wording contract.
6. Validate each `Reviewable` entry and calculate its score; validate each `Not Reviewable` reason and blank score fields separately.
7. Report reviewable and not-reviewable counts separately. Calculate overall and grouped score statistics from `Reviewable` rows only.
8. Report grouped summaries by engineer and manager, retaining source username relationships and coverage shortfalls.
9. Render the complete entry table with reviewability, `Problem`, `efforts`, and `comments`.

For validation or summary of an existing QA file, use:

```text
python <plugin-directory>/skills/case-review/scripts/qa.py report --input <qa.csv|qa.tsv|qa.txt|qa.json|qa.md>
```

The parser accepts JSON arrays/envelopes, CSV, TSV/plain-text tabular input, and GitHub-style Markdown tables. TSV/text may use the canonical header or the documented 12-column legacy and 14-column current positional order; embedded delimiters or line breaks must be quoted. Use `validate` when the user asks for data-quality checking only, and `score` for one reviewable entry. Preserve `Problem` and `efforts` in the final table even when the numeric validator is used separately.

Do not assign a pass/fail threshold, ranking, performance-management action, or recommendation unless the user supplies that policy explicitly.
