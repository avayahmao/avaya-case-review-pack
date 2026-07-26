---
name: "case-review"
description: "Generate an Operation Manager case review for Avaya Siebel SR or ServiceNow INC cases. Input a case ID (e.g. INC7386572, 1-23659220672, CHG..., CTASK..., PRJTASK...) to fetch the latest case status via the CaseToMD MCP tool and produce a management-oriented review: progress timeline, staleness/stall detection, owner accountability, risk flags, technical direction sanity validation, and next-step actions. Use when a manager asks to review/status-check/assess an Avaya case, wants a case summary or health check, needs to know 'where is this case stuck' or 'who owns the next step', or wants a digestible management brief from a raw Siebel/ServiceNow case."
---

# Case Review (Operation Manager)

Produce management-oriented reviews of Avaya Siebel SR / ServiceNow INC cases by fetching the latest case state through the CaseToMD MCP tool and analyzing it for progress, stalls, ownership, technical direction validity, and risk.

This is a management brief: status, trajectory, ownership, technical direction validity, risk, and what should happen next.

## Workflow

### Step 1 — Fetch the case

Call the `get_case_markdown` MCP tool with the case ID the user provided:

```
get_case_markdown(report_id: "<the case ID>")
```

- The tool auto-detects type (SR / INC / Activity / CTASK / CHG / PRJTASK) — pass the raw ID, do NOT normalize.
- Returns JSON: `{success, case_id, title, source, filename, markdown}`.
- **If `success` is false**: report the error to the user and stop. Do not fabricate a review.
- **If the CaseToMD MCP tool is unavailable** (not configured): tell the user to configure the CaseToMD MCP server. The endpoint is `https://192.168.67.160:8000/mcp` (self-signed cert). Do not silently fall back to guessing case content.
- The `markdown` field contains the full formatted case — this is your primary evidence. Everything in the review must trace back to it.

### Step 2 — Search Gmail for latest email context (Default Step)

Always search Gmail for supplementary email communications related to the case:

1. Call `gmail_search` with the case ID (e.g. `query: "<Case ID>"`).
2. If related task IDs (e.g., `TASK0614855`), customer names, or sub-tickets appear in the case markdown, also search for those terms if initial search is sparse.
3. For key relevant messages returned (e.g., executive updates, unassignable activity alerts, customer email threads, or internal engineer discussions), call `gmail_read` to retrieve full message contents.
4. Extract critical off-system management signals:
   - **Executive Notices / SDM updates**: recent management briefings or customer commitments.
   - **OCD / Auto-router alerts**: e.g., activities marked "UNASSIGNABLE" due to missing skills or schedules.
   - **Technical thread discussions**: workarounds or root-cause details shared via email.
5. If Gmail is unavailable or returns no results, proceed with the case markdown evidence and note "Gmail: No additional email threads found".

### Step 3 — Parse the case markdown & email context

Extract these fields from the markdown and email findings:

- **Case ID, Title, Status, Priority, Assignee** (top of doc)
- **Created date, Last Updated date** (Case Information)
- **Customer / Account / Site / Contact** (Customer Information)
- **Description** (the problem statement)
- **Activity / History & Email entries** — these form the unified timeline. Each entry has a timestamp, author/sender, activity/email type, and content summary.

### Step 4 — Analyze for management signals & technical direction validity

Apply these checks to the parsed case and email evidence:

1. **Staleness** — compute days since `Last Updated` vs today. Flag:
   - > 7 days, status not Closed/Resolved → ⚠️ STALE
   - > 30 days → 🔴 CRITICAL STALL
2. **Activity trend** — are recent activities (last 2-3) substantive updates or just status pings / "will follow up"? A run of vague updates with no new technical content signals a stuck case.
3. **Ownership clarity** — who is the current Assignee? Is there a named owner for the next action, or is it bouncing between teams? Identify the last person who took a concrete action and who the stated next-action owner is. Look out for OCD "UNASSIGNABLE" activity alerts in Gmail.
4. **Escalation status** — any open Product Escalation (PEA) / Management Escalation / cross-team handoff? Note its status (Done / On Hold / Open) and whether it is blocking.
5. **Customer impact language** — scan the description and recent notes for severity words ("severely impacting", "no impact", "production down"). Quote the customer's own impact statement if present.
6. **Repeated reopen / same-issue pattern** — does the case reference prior SRs with the same problem (e.g. "same as SR1-...")? This indicates a recurring/unresolved defect.
7. **Next step explicitness** — is there a clearly stated next action + owner + timeline? Missing/vague next steps = action item for the manager.
8. **Technical Direction & Avaya Platform Sanity Validation**:
   Cross-check the engineer's proposed root cause, technical hypotheses, and escalation paths against core Avaya UC/CC platform domain knowledge to ensure the investigation is not going down a dead end:
   - **Trunk Number Loss / Park-Unpark / `T####` Placeholders**: If the case notes discuss missing CLI, `T####` trunk IDs, or number loss after park/unpark/transfer, check if engineers are investigating CM `display system-features` SA9114 / SA9124 attributes. Flag if engineers are incorrectly blaming JTAPI SDK `null` returns (which are spec-compliant per Javadoc) or opening unsupported PEAs instead of enabling SA9114/SA9124 platform attributes.
   - **ACRA / Recording Session Boundaries**: If recording over-records or fails to clear session after transfer/complete, verify if engineers are checking the `CSTA_CALL_CLEARED` vs `CSTA_CONNECTION_CLEARED` boundary handling in CSTA event correlation instead of making generic application-level assumptions.
   - **Escalation & Vendor Handoff Target Validity**: Verify if the case/PEA is routed to the correct vendor/component:
     - CM / AES core bugs → BBE PEA
     - POM / AEP product code → CPE PEA
     - Verint / RIS / WebLogic / ACR code → Verint Ticket
     - Nuance MRCP / ASR / TTS → Nuance Ticket
     - Flag as `🔴 MISDIRECTED ESCALATION` if a ticket/PEA was opened against the wrong vendor or product group (e.g., opening an AES PEA for a Verint WebLogic issue).
   - **Certificates & Web-Tier Changes**: If a certificate change was performed, confirm if browser cache clearing and full JKS / service restarts were performed before declaring failure.
   - **Vector Wait Time**: If vector race conditions or call dropping occurs, check if `wait-time` in vector is set to 0 (minimum safe value is 1 second).

### Step 5 — Produce the review report

Output in exactly this structure:

```markdown
# Case Review — <Case ID>
**Title:** <one-line>
**Status:** <status> | **Priority:** <priority> | **Assignee:** <assignee>
**Source:** <Avaya Siebel SR / ServiceNow INC> | **Last Updated:** <date> (<N> days ago)
**Customer:** <account / site> — <contact>

## Verdict
<One or two sentences: is this case on track, at risk, or stalled? Lead with the bottom line.>
Overall health: 🟢 Healthy / 🟡 At Risk / 🔴 Stalled

## Progress Summary
<Bullet list of the 3-5 most important milestones/updates from the timeline (including Gmail email findings), newest first. Each = date + what changed. Omit routine pings.>

## Timeline (full)
| Date | By | Type | What happened |
|------|----|------|---------------|
<all activity and email entries, newest first — keep "what happened" to one line each>

## Risk Flags
<Each flag as a bullet with the evidence. Only include flags that actually apply.>
- ⚠️ STALE — no update for N days (since <date>)
- 🔴 Open escalation with no ETA — <PEA id>, status <...>
- ⚠️ Recurring issue — references prior SR <id>
- ⚠️ Unassignable Task / Dispatch Failure — <task id> marked unassignable
- ⚠️ Vague next step — no named owner / timeline
- ⚠️ TECHNICAL DIRECTION RISK — <Specific technical misdirection, e.g., "Engineer requesting JTAPI PEA for park CLI loss instead of enabling SA9114/SA9124">
- 🔴 MISDIRECTED ESCALATION — <Wrong vendor or team assigned, e.g., "AES PEA opened for Verint WebLogic issue">

## Ownership & Next Step
- **Current assignee:** <name>
- **Last concrete action by:** <name> on <date>
- **Stated next step:** <quote or paraphrase from latest note or email; "none stated" if absent>
- **Next-step owner:** <name or "unassigned">
- **Next update due:** <date or "not specified">

## Recommended Manager Actions
<2-4 specific, actionable items the manager should do. Tie each to an identified flag.>
1. ...
2. ...
```

## Guidelines

- **Evidence over opinion.** Every risk flag and verdict must cite a specific date, activity entry, email, or quoted phrase. Never invent details.
- **Search Gmail by default.** Always run `gmail_search` for the case ID to incorporate off-system emails, executive notices, and OCD unassignable task alerts into the review.
- **Validate Technical Directions.** Leverage Avaya domain principles (SA9114/SA9124, vendor escalation routes, CSTA event boundaries) to detect misdirected troubleshooting efforts.
- **Quote the customer's impact wording verbatim** when discussing impact.
- **Timeline is exhaustive but terse.** Include all activities and key emails in the table.
- **Verdict first.** A manager reading the top 3 lines should know whether to worry.
- **Currency**: compute "days ago" relative to today's date.
