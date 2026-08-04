---
name: "case-review"
description: "Generate an evidence-grounded Operation Manager case review for Avaya Siebel and ServiceNow records. Accept raw IDs such as INC7386572, 1-23659220672, Activity IDs, CTASK..., CHG..., or PRJTASK... and use CaseToMD plus Gmail to assess progress, staleness, ownership, technical direction, and mitigation maturity."
---

# Case Review (Operation Manager)

Produce an executive-ready case review whose factual conclusions are traceable to retrieved evidence. Never turn a domain rule, assumption, or plausible explanation into a case fact.

This file is the canonical runtime output contract. User and technical documentation must describe the same contract.

---

## Progressive Domain Knowledge Loading

After retrieving the case, identify the products and symptoms actually present and read only the matching reference file(s):

| Product / Topic | Reference File | Read When Case Mentions |
|---|---|---|
| **AES, CTI, JTAPI, TSAPI, CSTA, DMCC** | [aes-cti-jtapi.md](references/aes-cti-jtapi.md) | AES, JTAPI, TSAPI, CSTA, DMCC, park/unpark, null address, T#### |
| **Contact Center, Oceana, AACC, POM, CMS** | [contact-center.md](references/contact-center.md) | Oceana, AACC, POM, AXP, CMS, VDN, vector, skill, campaign |
| **Recording, ACRA, WFO, WFE, Verint** | [recording-wfo.md](references/recording-wfo.md) | Recording, ACRA, WFO, WFE, Verint, WebLogic, RIS, DMSA |
| **Analytics, Oceanalytics, Kubernetes** | [analytics-kubernetes.md](references/analytics-kubernetes.md) | Analytics, Oceanalytics, K8s, Kubernetes, Kafka, pod, MSTR |
| **Security, AVAPT, NVAPT, CVE** | [security-vulnerability.md](references/security-vulnerability.md) | Security, AVAPT, NVAPT, CVE, vulnerability, pen test, cipher |
| **SIP, Voice Quality, SBC** | [sip-voice-quality.md](references/sip-voice-quality.md) | SIP, one-way audio, voice quality, codec, SBC, RTP, jitter |
| **Certificates, WebLM, Login, Outage** | [certificates-login-outage.md](references/certificates-login-outage.md) | Certificate, WebLM, login, auth, outage, SMGR, EPM down |
| **Digital Channels (Email, Social, ESL)** | [digital-channels.md](references/digital-channels.md) | Email, Social, ESL, Infinity, WeChat, WhatsApp, screen-pop |
| **IP Office (IPO, SSA, SysMonitor)** | [ip-office.md](references/ip-office.md) | IP Office, IPO, SSA, SysMonitor, IP Office Manager |
| **Log Collection & Traces** | [log-collection.md](references/log-collection.md) | getlogs, spi.log, acr.log, csta_trace, g3trace, tcpdump |

Reference guides support interpretation only. They are not proof that a condition exists in the reviewed case.

---

## Workflow

### Step 1 - Plan the Retrieval

1. Extract the primary identifier. Supported record types are **INC, SR, Activity, CTASK, CHG, or PRJTASK**.
2. Plan the first two calls: CaseToMD for the official record, then Gmail for off-system context.
3. After retrieval, scan for related record IDs, PEA IDs, customer identifiers, and named owners.
4. Select domain references only after case symptoms and components are known.
5. Reserve a final evidence-coverage and format review before producing the answer.

### Step 2 - Retrieve Required Sources

#### CaseToMD

1. Call `get_case_markdown(report_id: "<Case ID>")` and **pass the raw ID without normalization**.
2. The expected response contains `success`, `case_id`, `title`, `source`, `filename`, and `markdown`.
3. Treat `markdown` as the official case-record source, not as proof that every embedded hypothesis is correct.
4. If the CaseToMD tool is missing, the call fails, or `success` is false, identify the CaseToMD failure and stop. Do not fabricate a review.

#### Gmail

1. Call `gmail_search(query: "<raw Case ID>")`.
2. Read relevant messages with `gmail_read`, prioritizing commitments, unassignable dispatch alerts, and technical threads containing concrete results.
3. Additional searches must remain case-bounded. Combine a related ID, customer term, or owner with the primary case context; do not run broad person-only searches.
4. If the **Gmail tool is missing or the search call fails**, identify Gmail as the unavailable required server and stop.
5. If the **Gmail search succeeds but returns no relevant messages**, continue with CaseToMD evidence and state: `Gmail: no additional relevant evidence found`.
6. User-supplied documents may supplement these sources. Label them by filename and date; do not present a parsed shell, extraction artifact, or unsupported inference as a live case record.

### Step 3 - Build the Evidence Ledger

Create an internal ledger before analysis. Give every case-specific item a sequential identifier and record:

- **Evidence ID:** E1..EN
- **Source:** CaseToMD activity, Gmail subject/message, user-supplied document, or raw log/trace
- **Date:** source timestamp, or `not stated`
- **Verbatim evidence / data:** exact quote, error, measurement, or faithfully transcribed fact
- **Supports:** the exact body section and conclusion or field this item supports

Apply two separate orderings:

1. **Evidentiary authority:** direct logs/measurements and official record facts; then concrete first-party email or supplied records; then management summaries; then domain-reference interpretation.
2. **Management display priority:** customer impact, current blocker, ownership, ETA, escalation, and material technical progress.

Management display priority controls what the manager sees first. It must never override evidentiary authority.

### Chronological output order

- Any rendered list or table that contains dates or timestamps — including Progress Summary, Timeline, Appendix A, ADM chronology, and dated log excerpts — must be sorted by normalized date/time in ascending order (oldest first).
- For equal timestamps, preserve the ledger/source order. Place `not stated` or otherwise undated entries after all dated entries.
- Assign rendered `E1..EN` identifiers after this chronological sort so appendix row numbering follows display order.
- This is a presentation rule only: `Last substantive progress age` still uses the newest dated evidence internally for freshness and stall calculations.

If sources disagree, preserve both evidence items, describe an **unresolved source conflict**, and answer `unknown` for the disputed conclusion unless stronger evidence resolves it.

**Do not discard status pings before analysis.** Retain them to detect activity without substantive progress, but omit them from the displayed timeline unless the ping creates a commitment, owner, deadline, or escalation.

### Step 4 - Analyze Only What the Evidence Supports

#### Freshness and activity

Calculate two clocks:

- **Case record freshness:** days since the official record's `Last Updated` timestamp.
- **Last substantive progress age:** days since the newest dated evidence showing a technical finding, completed test, configuration change, decision, escalation movement, mitigation result, or customer-impact change.

Apply staleness only to open work:

- **Closed/Resolved:** report record age if useful, but do not flag STALE or CRITICAL STALL solely because the record is old.
- Open and last substantive progress age > 7 days: `STALE`.
- Open and last substantive progress age > 30 days: `CRITICAL STALL`.
- A newer Gmail update than the official record is evidence of case-record synchronization risk, not permission to silently replace the official status.

#### Ownership, impact, and escalation

- Identify the current assignee, last concrete action taker, stated next action, next-action owner, and due date.
- Use `unassigned`, `not stated`, or `unknown` when evidence does not provide a value. Never invent an owner or ETA.
- Quote customer-impact wording verbatim when it exists.
- Identify related/reopened records and open product or management escalations, including the evidence-backed blocker and ETA state.

#### Technical direction and log sufficiency

Run a domain sanity check only when matching case evidence activates it:

- Park/unpark or trunk-identity evidence may activate SA9114/SA9124 and JTAPI checks.
- UCID evidence may activate `LucentV5CallInfo.getUCID()` validation.
- Recording evidence may activate `CSTA_CALL_CLEARED` versus `CSTA_CONNECTION_CLEARED` checks.
- Certificate/web-tier evidence may activate cache, keystore, trust-chain, and restart checks.
- Vector timing evidence may activate the non-zero `wait-time` check.

Treat these as conditional diagnostic baselines, not universal causes. A reference rule can support a technical interpretation only when case-specific evidence matches its trigger.

For logs, distinguish `requested`, `collected`, `attached`, and `analyzed`. Do not flag a log as missing merely because the retrieved summary does not mention it.

Use the vendor handoff matrix only after the failing component is evidenced:

- CM/AES core defect: BBE PEA
- POM/AEP product code: CPE PEA
- Verint/RIS/WebLogic/ACR: Verint ticket
- Nuance MRCP/ASR/TTS: Nuance ticket
- Customer infrastructure: Customer/MSP

#### Problem, RCA, and mitigation

- Use a single-issue assessment for one fault.
- Use a multi-problem assessment when there are distinct failure modes or related records requiring separate conclusions.
- Keep telemetry calculations inside the relevant problem description and show the source inputs.
- Use RCA states: `Under Investigation`, `Suspected`, `Identified`, or `Validated`. Do not label a root cause Identified/Validated without supporting evidence.
- Use exactly one mitigation maturity state:
  - **Proposed**
  - **Lab Validated**
  - **Production Deployed**
  - **Production Outcome Confirmed**
  - **None Active**
- A lab test, one repaired record, a scheduled rollout, or an engineer's success report without post-change production evidence **must not be described as production resolution**.

### Layered Executive and Technical Content

The **Executive Summary** owns conclusion-level information, while **Technical & Incident Assessment** owns the explanation. The summary states the conclusion; the technical assessment explains why that conclusion is justified by the evidence.

#### Executive Summary contract

- Write one natural-language paragraph of 6-8 sentences with no subheadings, bullets, field labels, or citation markers.
- Cover the following conclusion-level information in this order, combining adjacent points when needed to stay within 6-8 sentences: the incident with its evidenced time and location; affected scope; business or customer impact; key response; a one-sentence technical conclusion stating the RCA state or supported cause; mitigation maturity and production outcome; current status; and the next evidenced checkpoint with owner and ETA.
- Use lowercase `unknown` for an unsupported detail. Do not substitute a plausible assumption or silently omit a required conclusion-level point.
- Exclude raw logs, detailed troubleshooting, configuration detail, extended cause analysis, and prevention content. `Future prevention` does not belong in the Executive Summary.

#### Technical & Incident Assessment contract

- Start with problem clarification, then explain the evidence and reasoning needed to support or qualify the summary conclusion.
- Every paragraph must add at least one of the following: environment or affected-component detail; a finding or interpreted log excerpt; causal reasoning or an RCA-state explanation; a ruled-out alternative, unresolved gap, or missing validation; solution, workaround, implementation, or verification detail; or **Existing prevention controls** already stated, committed, or implemented in the evidence.
- Remove any paragraph that only paraphrases an Executive Summary sentence. Do not repeat the full incident, impact, response, status, owner, or ETA unless the technical explanation requires a specific distinction.
- Existing prevention controls appear only in the technical assessment under the relevant problem and only when the evidence already states, commits, or implements them. Omit them when absent; never generate a prevention recommendation.

#### Adaptive ADM depth

- ADM mode activates only when the user explicitly requests `ADM` or `Avaya Diagnostic Methodology`, matched case-insensitively.
- ADM mode increases the depth of `Technical & Incident Assessment` only; it must not lengthen the Executive Summary or create a second ADM block.
- When evidence permits, cover **Details/Findings**, **Problem Clarification**, **Cause**, and **Solution** as analytical dimensions inside the chosen technical structure. Adapt the prose to the case; it is not required to display four mechanical ADM headings.

#### Generation order

1. Complete the evidence ledger, RCA state, mitigation maturity, production-outcome assessment, and case classification.
2. Draft the Technical & Incident Assessment from problem clarification through evidence, reasoning, solution or validation, and unresolved gaps.
3. Extract only the conclusion-level information needed for the Executive Summary.
4. Deduplicate in both directions: remove technical detail from the summary and remove technical paragraphs that add no explanation beyond the summary.

### Step 5 - Enforce the Evidence Gate

Every factual answer must pass the internal evidence gate before rendering:

- Build dynamic appendix rows **E1..EN**, where N is the number of verifiable case-specific evidence items. There is no minimum of three.
- Each row must contain `Source`, `Date`, `Verbatim evidence / data`, and `Supports`.
- Every factual body claim must map internally to at least one appendix row.
- The `Supports` column performs reverse mapping from evidence to the exact body section and conclusion or field.
- The rendered body must contain no Evidence IDs, footnotes, source suffixes, or citation brackets.
- Answer only the portion supported by evidence. For an unsupported field or disputed conclusion, write `unknown`.
- If no verifiable case-specific evidence exists, **output exactly `unknown`** and stop. Do not emit the report template.
- **Do not split, duplicate, or invent evidence** to increase the evidence count.
- Domain references may explain evidence but do not count as case-specific evidence by themselves.
- `Appendix A — Evidence Register` is the final section of every rendered review.

### Step 6 - Reflection and Coverage Review

Before rendering:

1. Map every factual body claim to at least one appendix row.
2. Confirm dates, IDs, names, quotes, calculations, owners, and ETA values against the ledger.
3. Confirm unresolved conflicts remain visible and are not silently resolved.
4. Confirm mitigation maturity does not overstate lab or planned work as production success.
5. Confirm owners are evidence-backed or explicitly `unassigned`.
6. Confirm `Ownership & Next Step` only restates actions, owners, and dates already present in evidence; it must never generate a new recommendation.
7. Confirm the rendered body contains no Evidence ID or citation suffix.
8. Confirm the appendix is last and reverse-maps every evidence row through `Supports`.
9. Confirm the zero-evidence response is exactly `unknown`.
10. Confirm every rendered list or table containing dates or timestamps is in ascending date/time order, with undated entries last.
11. Confirm the Executive Summary is one 6-8 sentence paragraph with no subheadings or prevention content.
12. Confirm its root-cause statement uses at most one sentence as the one-sentence technical conclusion; keep detailed cause analysis only in Technical & Incident Assessment.
13. Remove any technical paragraph that merely paraphrases the summary without adding a finding, mechanism, validation result, or unresolved gap.
14. When explicit ADM mode applies, confirm all four analytical dimensions are covered inside Technical & Incident Assessment without a second outline or ADM block.

### Step 7 - Produce the Review

After the evidence gate passes, use this common structure:

```markdown
# Case Review - <Case ID>
**Title:** <evidence-backed title or unknown>
**Status:** <status or unknown> | **Priority:** <priority or unknown> | **Assignee:** <assignee or unknown>
**Source:** <actual source system and record type>
**Case record freshness:** <N days / date unavailable>
**Last substantive progress age:** <N days / no substantive progress evidenced>
**Customer:** <account/site/contact or unknown>

## Executive Summary
<Write one natural-language paragraph of 6-8 sentences covering the conclusion-level incident with time and location, affected scope, impact, key response, one-sentence technical conclusion, mitigation and production outcome, current status, and the next evidenced checkpoint with owner and ETA; use lowercase unknown for unsupported details; exclude raw logs, detailed diagnostics, configuration detail, extended cause analysis, and prevention content.>

## Technical & Incident Assessment
<Start with problem clarification; add environment or affected-component detail, findings or interpreted log evidence, causal or RCA-state reasoning, solution or workaround implementation and verification, and unresolved gaps or missing validation; do not fully restate the event, impact, response, or status from the Executive Summary.>

## Progress Summary
<Three to five substantive milestones, oldest first, without citation markers.>

## Ownership & Next Step
- **Current assignee:** <name / unassigned / unknown>
- **Last concrete action:** <actor, action, date / unknown>
- **Stated next action:** <evidence-stated action / not stated / unknown>
- **Next-action owner:** <name/role / unassigned / unknown>
- **Next SLA/update due:** <date / not stated / unknown>

## Timeline
| Date | By | Source | What changed |
|---|---|---|---|
<Substantive entries only, in ascending date/time order. Status pings remain part of the activity-trend analysis.>

## Appendix A — Evidence Register
| Ref | Date | Source | Verbatim evidence / data | Supports |
|---|---|---|---|---|
<Evidence rows E1..EN in ascending date/time order; undated rows last>
```

For the conditional technical section:

- Choose exactly one structure for the section.
- **Multi-problem:** use `Problem Statement`, then `Problem 1 - <Record ID>`, `Problem 2 - <Record ID>`, and so on. For each problem, cover problem clarification, evidence-backed findings, cause or RCA-state reasoning, solution and validation, mitigation maturity and production outcome, and unresolved gaps.
- **Single issue:** use `Incident & RCA Summary` and cover the same semantic sequence: problem clarification, evidence-backed findings, cause or RCA-state reasoning, solution and validation, mitigation maturity and production outcome, and unresolved gaps.
- Put **Existing prevention controls** only under the relevant problem and only when evidenced as already stated, committed, or implemented.

Do not render both conditional structures. Do not create a standalone telemetry section or a second ADM block.

---

## Non-Negotiable Rules

- Evidence over opinion; unknown over invention.
- Case-specific evidence is required for case-specific conclusions.
- Evidence numbering is dynamic, not a three-item quota.
- Evidentiary authority and Management display priority are separate.
- Status pings inform stall detection even when omitted from the displayed timeline.
- Closed/Resolved records are not stale merely because they are old.
- Domain rules are conditionally activated and never substitute for case evidence.
- Production success requires post-change production evidence.
- The report must not generate risk lists, risk scores, manager directives, prevention priorities, or recommendations.
- Existing prevention controls belong only in Technical & Incident Assessment, under the relevant problem, and only when already evidenced.
- The Executive Summary states the conclusion; Technical & Incident Assessment explains the evidence, mechanism, reasoning, validation, and unresolved gaps that justify or qualify it.
- The main body stays citation-free; the final appendix preserves the audit chain.
- Rendered date/time lists and tables are ordered oldest to newest; undated items follow dated items.
- The manager should understand the Executive Summary, evidence basis, owner, ETA state, RCA state, mitigation maturity, production outcome, and next checkpoint without rereading the raw case.
