---
name: "case-review"
description: "Generate an Operation Manager case review for Avaya Siebel SR or ServiceNow INC cases. Input a case ID (e.g. INC7386572, 1-23659220672, CHG..., CTASK..., PRJTASK...) to fetch the latest case status via the CaseToMD MCP tool and produce a management-oriented review: progress timeline, staleness/stall detection, owner accountability, risk flags, technical direction sanity validation, and next-step actions. Use when a manager asks to review/status-check/assess an Avaya case, wants a case summary or health check, needs to know 'where is this case stuck' or 'who owns the next step', or wants a digestible management brief from a raw Siebel/ServiceNow case."
---

# Case Review (Operation Manager)

Produce management-oriented reviews of Avaya Siebel SR / ServiceNow INC cases by fetching the latest case state through the CaseToMD MCP tool and analyzing it for progress, stalls, ownership, technical direction validity, and risk.

This is a comprehensive management brief: status, trajectory, ownership, technical direction validity, risk, and what should happen next.

---

## Progressive Domain Knowledge Loading

When reviewing a case, identify the Avaya products and components mentioned in the case description or notes, and **read the corresponding reference file(s)** from `references/` to apply domain-specific troubleshooting rules and sanity checks:

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

---

## Workflow

### Step 1 — Fetch the case

Call the `get_case_markdown` MCP tool with the case ID the user provided:

```
get_case_markdown(report_id: "<the case ID>")
```

- The tool auto-detects type (SR / INC / Activity / CTASK / CHG / PRJTASK) — pass the raw ID, do NOT normalize.
- Returns JSON: `{success, case_id, title, source, filename, markdown}`.
- **If `success` is false**: report the error to the user and stop. Do not fabricate a review.
- **If the CaseToMD MCP tool is unavailable** (not configured): tell the user to configure the CaseToMD MCP server at `https://192.168.67.160:8000/mcp`.
- The `markdown` field contains the full formatted case — this is your primary evidence.

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
- **Activity / History & Email entries** — these form the unified timeline.

### Step 4 — Analyze for management signals & technical direction validity

Apply these checks to the parsed case, loaded domain reference files, and email evidence:

1. **Staleness** — compute days since `Last Updated` vs today. Flag:
   - > 7 days, status not Closed/Resolved → ⚠️ STALE
   - > 30 days → 🔴 CRITICAL STALL
2. **Activity trend** — are recent activities (last 2-3) substantive updates or just status pings / "will follow up"? Vague updates with no new technical content signal a stuck case.
3. **Ownership clarity** — who is the current Assignee? Is there a named owner for the next action, or is it bouncing between teams? Identify the last person who took a concrete action and who the stated next-action owner is.
4. **Escalation status** — any open Product Escalation (PEA) / Management Escalation / cross-team handoff? Note its status and whether it is blocking.
5. **Customer impact language** — quote the customer's own impact statement if present.
6. **Repeated reopen / same-issue pattern** — does the case reference prior SRs with the same problem?
7. **Next step explicitness** — is there a clearly stated next action + owner + timeline?
8. **Technical Direction & Avaya Platform Sanity Audit**:
   Cross-check the engineer's proposed root cause, technical hypotheses, and escalation paths against the loaded product reference files:
   - **Trunk Number Loss / Park-Unpark / `T####` Placeholders**: Check if engineers are investigating CM `display system-features` SA9114 / SA9124 attributes. Flag if engineers are incorrectly blaming JTAPI SDK `null` returns (which are spec-compliant per Javadoc) or opening unsupported PEAs instead of enabling SA9114/SA9124 platform attributes.
   - **UCID Extraction**: Ensure UCID is extracted from `LucentV5CallInfo.getUCID()`. Flag if engineers use `getOriginalCallInfo().getUCID()` which returns all zeros during EC_PARK.
   - **Recording / ACRA Boundaries**: Verify if engineers check `CSTA_CALL_CLEARED` vs `CSTA_CONNECTION_CLEARED` event boundary correlation in CSTA traces.
   - **Certificates & Web-Tier Changes**: Confirm if browser cache clearing, JKS keystore update, and full service restarts were performed after cert changes before declaring failure.
   - **Vector Wait Time**: If vector race conditions or call dropping occurs, check if `wait-time` in vector is set to 0 (minimum safe value is 1 second).
9. **Vendor Escalation Route Sanity**:
   Verify whether open tickets or PEAs are routed to the correct vendor/component:
   - CM / AES core bugs → **BBE PEA**
   - POM / AEP product code → **CPE PEA**
   - Verint / RIS / WebLogic / ACR code → **Verint Ticket**
   - Nuance MRCP / ASR / TTS → **Nuance Ticket**
   - Customer Infra (LDAP, SQL, Network/Firewall) → **Customer/MSP**
   - Flag as `🔴 MISDIRECTED ESCALATION` if a ticket/PEA was opened against the wrong vendor or product group.
10. **Log Sufficiency Check**:
    Cross-check whether the required diagnostic logs listed in [log-collection.md](references/log-collection.md) (e.g. `getlogs`, `csta_trace`, `g3trace`, `spi.log`, `acr.log`, `tcpdump`) have been requested or attached. Flag if key traces are missing.
11. **Technical Synthesis (RCA & Mitigation)**:
    - **Incident & Technical Summary**: Synthesize the core fault mechanism, affected products/components, and current diagnostic status.
    - **Root Cause Analysis (RCA)**: Determine if the root cause is Identified, Suspected, or Under Investigation. If under investigation, explicitly state what specific diagnostic logs/traces or tests are pending to isolate it.
    - **Mitigation Steps**: Identify any temporary workaround or interim patch applied or available to restore service. If no workaround exists, explicitly state the current operational impact and pending mitigation prerequisites.

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

## Technical & Incident Assessment

### Incidents & Technical Progress Summary
- **Symptom / Fault:** <Summary of observed technical failure or incident>
- **Affected Components:** <Avaya products/components involved, e.g. AES JTAPI, CM, Session Manager>
- **Current Technical Trajectory:** <Summary of technical diagnostic progress and current focus>

### Root Cause Analysis (RCA)
- **Status:** Identified / Suspected / 🔍 Under Investigation
- **Findings:** <Detailed root cause description, OR if under investigation: "🔍 Under Investigation (Pending: [specific logs/traces/config checks required to isolate root cause])">

### Mitigation Steps
- **Status:** Active Workaround / Pending / ⚠️ None Active
- **Details:** <Workaround steps applied or available to restore service/minimize impact, OR if none: "⚠️ None Active / Workaround Pending (Impact: [statement])">

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
- ⚠️ TECHNICAL DIRECTION RISK — <Specific technical misdirection based on domain reference checks>
- 🔴 MISDIRECTED ESCALATION — <Wrong vendor or team assigned>
- ⚠️ MISSING DIAGNOSTIC LOGS — <Missing required trace, e.g., getlogs/csta_trace>

## Ownership & Next Step
- **Current assignee:** <name>
- **Last concrete action by:** <name> on <date>
- **Stated next step:** <quote or paraphrase from latest note or email; "none stated" if absent>
- **Next-step owner:** <name or "unassigned">
- **Next update due:** <date or "not specified">

## Targeted Recommendations

### 1. Manager & Escalation Actions
<Action items for management, SDM alignment, vendor escalation, or SLA/customer communication. Include Priority & Owner.>
1. **[Priority] Action:** <Description> | **Owner:** <Name/Role>
2. ...

### 2. Technical & Diagnostic Actions
<Concrete technical items for engineers, such as CM SA9114/SA9124 verification, collecting getlogs/csta_trace, or checking vector wait-time. Include Priority & Owner.>
1. **[Priority] Action:** <Description> | **Owner:** <Name/Role>
2. ...
```

## Guidelines

- **Evidence over opinion.** Every risk flag and verdict must cite a specific date, activity entry, email, or quoted phrase. Never invent details.
- **Load Domain References.** Read the matching product reference file from `references/` whenever analyzing technical claims.
- **Search Gmail by default.** Always run `gmail_search` for the case ID to incorporate off-system emails, executive notices, and OCD unassignable task alerts into the review.
- **Validate Technical Directions.** Leverage Avaya domain principles (SA9114/SA9124, vendor escalation routes, CSTA event boundaries) to detect misdirected troubleshooting efforts.
- **Explicit Technical RCA/Mitigation Tracking.** Always provide clear RCA and Mitigation status. If unknown, explicitly note what diagnostic logs/traces are blocking RCA determination rather than giving generic placeholders.
- **Bi-Level Targeted Recommendations.** Categorize all recommendations into Manager/Escalation Actions and Technical/Diagnostic Actions with clear Owners and Priorities.
- **Quote the customer's impact wording verbatim** when discussing impact.
- **Timeline is exhaustive but terse.** Include all activities and key emails in the table.
- **Verdict first.** A manager reading the top 3 lines should know whether to worry.
- **Currency**: compute "days ago" relative to today's date.

