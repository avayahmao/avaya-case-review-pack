---
name: "alarm-audit"
description: "Audit Avaya alarm tickets separately from ordinary case QA using Check, Cause, Chronic, and Alarm Plus scoring with evidence-backed comments and monthly summaries."
---

# Alarm Ticket Audit

Use this skill when the user explicitly asks for alarm QA, an alarm-ticket audit, monthly alarm scoring, or supplies the alarm audit columns.

Alarm Audit is separate from ordinary case QA. Do not score alarm tickets with the Diagnostic & Solution / Service & Communication / Technical Plus rubric.

## Operating modes

- **Validate supplied audit:** preserve the supplied tickets and validate fields, bounds, score totals, comments, and summaries.
- **Perform audit from a workload report:** select eligible alarm tickets, collect complete case evidence, assign audit scores, and produce the requested table or workbook.

## Monthly selection

1. Use `Closed Date` for the requested month and include only completed/closed alarm tickets.
2. Include tickets whose workload subclass is `Alarm` or whose primary purpose is alarm handling, even if the workload row is mislabeled.
3. Exclude canceled or administratively non-reviewable tickets, including `Cancelled`, `NO RESPONSE`, `CUSTOMER CANCELLED`, `NO LONGER REQUIRED`, `DUPLICATE TICKET`, `LACKS DATA TO DIAGNOSE`, or an equivalent closure without a reviewable alarm check.
4. Use the user-specified sample size. If none is supplied, select the two most recently closed eligible alarm tickets per source username.
5. Use lowercase source usernames from `Assigned To Login` and `Manager Login`; never invent usernames from display names.

## Output fields

Use this exact order:

```text
Ticket ID | Name | Manager | Account Tier | Alarm | Check | Cause | Chronic | PLUS | Score | Comments
```

- `Ticket ID`, `Name`, and `Manager` are required.
- `Account Tier` and `Alarm` must come from the source; leave blank or use `not stated` when unsupported.
- `Check`, `Cause`, and `Chronic` are integers from 0 through 1.
- `PLUS` is an integer from 0 through 2.
- `Score = Check + Cause + Chronic + PLUS`; maximum 5.
- `Comments` are required and must briefly state what was checked, when it was checked, and why any Cause, Chronic, or PLUS points were earned.

## Scoring rubric

### Check (0-1)

- **1:** The engineer accessed or otherwise checked the alarm promptly enough to establish the current alarm/service state and documented the result. `Alarm cleared upon access` earns Check 1 when the access was timely and evidenced.
- **0:** No meaningful check is documented, or the check occurred so late that it cannot establish the incident-time state. A first check two weeks later is Check 0.

Check answers: **Is there service impact now, and what is the alarm state upon access?**

### Cause (0-1)

- **1:** A case-specific possible cause, failing component, or mechanism is identified with evidence. The cause may remain provisional, but it must be more specific than the alarm name.
- **0:** The alarm merely cleared, the component recovered without explanation, or no cause/mechanism was documented.

Cause answers: **What likely produced the alarm?** Do not convert correlation into confirmed RCA.

### Chronic (0-1)

- **1:** The engineer evaluated recurrence/history and documented that the alarm is repeated/chronic, including the pattern, scope, or follow-up owner.
- **0:** The ticket is a one-time alarm, recurrence was not checked, or no chronic pattern is supported.

Chronic answers: **Is this recurring, and was recurrence meaningfully assessed?**

### Alarm Plus (0-2)

Alarm Plus rewards extra incident-prevention and operational value beyond checking the alarm:

1. **Prevention / Durable Action (+1):** implemented or clearly documented a preventive action that reduces recurrence or prevents a service incident.
2. **Communication / Documentation (+1):** promptly notified the customer/owner and produced clear evidence, recovery proof, or reusable documentation/handoff.

Award 0 for routine access, ordinary alarm clearance, generic notification, or unsupported statements. Award at most 2, one point per demonstrated item. Do not double-count the same action.

## Calibration examples

- `Check 1, Cause 0, Chronic 0, PLUS 0 = 1`: alarm cleared upon access; no cause or recurrence work.
- `Check 1, Cause 0, Chronic 0, PLUS 0 = 1`: alarm cleared upon access with proof; proof supports Check but is not automatically extra-mile documentation.
- `Check 1, Cause 1, Chronic 0, PLUS 1 = 3`: affected gateway still unreachable, possible cause documented, customer notified, and recovery later observed.
- `Check 0, Cause 0, Chronic 0, PLUS 0 = 0`: first meaningful check occurred two weeks later.

## Evidence and comments

- For a newly scored ticket, retrieve CaseToMD and exhaust the exact primary-ID Gmail collection before scoring.
- Score only actions attributable to the named engineer.
- Alarm clearance is an observation, not a root cause or preventive action.
- Use `unknown` for unsupported service impact, cause, recurrence, or durable outcome.
- Keep comments short and operational, similar to the manager examples.
- When PLUS is nonzero, document each point as `Plus +1: Prevention - <reason>` or `Plus +1: Communication/Documentation - <reason>`.
- Do not use minus notation: Alarm Audit is additive from zero, not deductive from a full-score baseline.

## Data consistency

- Reject out-of-range dimensions and conflicting supplied totals.
- Reject blank comments.
- PLUS allocations in comments must use `Plus +1:` once per point and sum exactly to PLUS.
- Do not infer a pass/fail threshold, employee ranking, or performance action unless the user supplies that policy.

## Workflow

1. Determine whether tickets are supplied or must be selected from a workload report.
2. Apply alarm-only, month, cancellation, username, and sample-size rules.
3. Complete evidence collection and score each ticket independently.
4. Validate totals and concise comments.
5. Report overall and dimension averages, plus grouped summaries by engineer and manager.
6. Render the complete audit table.

For validation or reporting of an existing alarm-audit file, use:

```text
python <plugin-directory>/skills/case-review/scripts/alarm_audit.py report --input <audit.csv|audit.json|audit.md>
```

Use `validate` for data-quality checking only and `score` for one ticket.
