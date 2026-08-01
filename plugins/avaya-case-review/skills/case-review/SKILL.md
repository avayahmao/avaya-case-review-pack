---
name: "case-review"
description: "Generate an evidence-grounded Operation Manager case review for Avaya Siebel and ServiceNow records. Accept raw IDs such as INC7386572, 1-23659220672, Activity IDs, CTASK..., CHG..., or PRJTASK... and use CaseToMD plus Gmail to assess progress, staleness, ownership, risk, technical direction, mitigation maturity, and next actions."
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

- **Evidence ID:** Evidence 1..N
- **Source:** CaseToMD activity, Gmail subject/message, user-supplied document, or raw log/trace
- **Date:** source timestamp, or `not stated`
- **Verbatim evidence / data:** exact quote, error, measurement, or faithfully transcribed fact
- **Supports:** the single factual claim this item supports

Apply two separate orderings:

1. **Evidentiary authority:** direct logs/measurements and official record facts; then concrete first-party email or supplied records; then management summaries; then domain-reference interpretation.
2. **Management display priority:** customer impact, current blocker, ownership, ETA, escalation, and material technical progress.

Management display priority controls what the manager sees first. It must never override evidentiary authority.

If sources disagree, preserve both evidence items, describe an **unresolved source conflict**, and answer `不知道` for the disputed conclusion unless stronger evidence resolves it.

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
- Use `unassigned`, `not stated`, or `不知道` when evidence does not provide a value. Never invent an owner or ETA.
- Quote customer-impact wording verbatim when it exists.
- Identify related/reopened records and open product or management escalations, including the evidence-backed blocker and ETA state.

#### Technical direction and log sufficiency

Run a domain sanity check only when matching case evidence activates it:

- Park/unpark or trunk-identity evidence may activate SA9114/SA9124 and JTAPI checks.
- UCID evidence may activate `LucentV5CallInfo.getUCID()` validation.
- Recording evidence may activate `CSTA_CALL_CLEARED` versus `CSTA_CONNECTION_CLEARED` checks.
- Certificate/web-tier evidence may activate cache, keystore, trust-chain, and restart checks.
- Vector timing evidence may activate the non-zero `wait-time` check.

Treat these as conditional diagnostic baselines, not universal causes. A reference rule can support a recommendation or hypothesis only when case-specific evidence matches its trigger.

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

### Step 5 - Enforce the Evidence Gate

Every factual answer must contain a dynamic evidence section:

- Output **Evidence 1..N**, where N is the number of verifiable case-specific evidence items. There is no minimum of three.
- Each item must contain `Source`, `Date`, `Verbatim evidence / data`, and `Supports`.
- Cite the evidence identifier beside every verdict, risk flag, RCA statement, mitigation state, ownership statement, and recommendation.
- Answer only the portion supported by evidence. For an unsupported field or disputed conclusion, write `不知道`.
- If no verifiable case-specific evidence exists, **output exactly `不知道`** and stop. Do not emit the report template.
- **Do not split, duplicate, or invent evidence** to increase the evidence count.
- Domain references may explain evidence but do not count as case-specific evidence by themselves.

### Step 6 - Reflection and Coverage Review

Before rendering:

1. Map every factual claim to at least one Evidence ID.
2. Confirm dates, IDs, names, quotes, calculations, owners, and ETA values against the ledger.
3. Confirm unresolved conflicts remain visible and are not silently resolved.
4. Confirm mitigation maturity does not overstate lab or planned work as production success.
5. Confirm every risk has a supported action, and every action cites evidence.
6. Confirm owners are evidence-backed or explicitly `unassigned`.
7. Confirm **all action items must live exclusively** in `Targeted Recommendations`; do not duplicate them elsewhere.
8. Confirm the zero-evidence response is exactly `不知道`.

### Step 7 - Produce the Review

After the evidence gate passes, use this common structure:

```markdown
# Case Review - <Case ID>
**Title:** <evidence-backed title or 不知道>
**Status:** <status or 不知道> | **Priority:** <priority or 不知道> | **Assignee:** <assignee or 不知道>
**Source:** <actual source system and record type>
**Case record freshness:** <N days / date unavailable>
**Last substantive progress age:** <N days / no substantive progress evidenced>
**Customer:** <account/site/contact or 不知道>

## Evidence

### Evidence 1
- **Source:** <CaseToMD activity / Gmail subject / document / raw log>
- **Date:** <timestamp or not stated>
- **Verbatim evidence / data:** <exact quote, error, or measurement>
- **Supports:** <one factual claim>

<Repeat sequentially through Evidence N; emit only real evidence items.>

## Verdict
<On track, At Risk, or Stalled; cite Evidence IDs.>
Overall health: Healthy / At Risk / Stalled / 不知道

## Technical & Incident Assessment
<Choose exactly one structure: multi-problem Problem Statement OR single-issue Incident & RCA Summary.>

## Progress Summary
<Three to five substantive milestones, newest first, each citing Evidence IDs.>

## Timeline
| Date | By | Source | What changed | Evidence |
|---|---|---|---|---|
<Substantive entries only. Status pings remain part of the activity-trend analysis.>

## Risk Flags
<Only evidence-backed flags; cite Evidence IDs. Write "None evidenced" when applicable.>

## Ownership & Next Step
- **Current assignee:** <name / unassigned / 不知道> [Evidence N]
- **Last concrete action:** <actor, action, date / 不知道> [Evidence N]
- **Stated next action:** <action / not stated / 不知道> [Evidence N]
- **Next-action owner:** <name/role / unassigned / 不知道> [Evidence N]
- **Next SLA/update due:** <date / not stated / 不知道> [Evidence N]

## Targeted Recommendations

### 1. Manager & Escalation Actions
1. **[Problem/Record] [Priority] Action:** <description> | **Owner:** <name/role or unassigned> | **Evidence:** <Evidence IDs>

### 2. Technical & Diagnostic Actions
1. **[Problem/Record] [Priority] Action:** <description> | **Owner:** <name/role or unassigned> | **Evidence:** <Evidence IDs>
```

For the conditional technical section:

- **Multi-problem:** use `Problem Statement`, then `Problem 1 - <Record ID>`, `Problem 2 - <Record ID>`, and include symptom, evidence-backed RCA state/finding, affected components, and mitigation maturity.
- **Single issue:** use `Incident & RCA Summary` with symptom, affected components, RCA state/finding, mitigation maturity, and supporting Evidence IDs.

Do not render both conditional structures. Do not create a standalone telemetry section.

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
- All action items must live exclusively in `Targeted Recommendations`.
- The manager should understand the verdict, evidence basis, owner, ETA state, risk, RCA state, and mitigation maturity without rereading the raw case.
