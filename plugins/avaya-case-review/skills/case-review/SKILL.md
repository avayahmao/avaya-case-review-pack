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
2. Retrieve CaseToMD first. Do not start Gmail collection until every Case note has been processed and the record-ID query set has been frozen.
3. Do not analyze evidence, draft conclusions, or generate any review content until the complete-context gate passes.
4. Select domain references only after case symptoms and components are known.
5. Reserve a final context-coverage, evidence-coverage, and format review before producing the answer.

### Step 2 - Retrieve Required Sources

#### CaseToMD

1. Call `get_case_markdown(report_id: "<Case ID>")` and **pass the raw ID without normalization**.
2. The expected response contains `success`, `case_id`, `title`, `source`, `filename`, and `markdown`.
3. Treat `markdown` as the official case-record source, not as proof that every embedded hypothesis is correct.
4. If the CaseToMD tool is missing, the call fails, or `success` is false, identify the CaseToMD failure and stop. Do not fabricate a review.

### Complete Context Before Analysis

Before generating any review content, process **every discrete Case note** returned by CaseToMD, including routine status pings; freeze the primary raw Case ID plus every supported related record ID explicitly present in those notes; enumerate every Gmail thread for every frozen ID; and read every message in every unique matched thread. Relevance ranking may affect display only after this gate passes; it must never determine what is retrieved, read, or processed.

#### Case notes and frozen query scope

1. Identify every discrete note or activity block from the structured boundaries in the CaseToMD Markdown. Count each note in `case_notes_discovered`, process it into the internal source ledger, and count it in `case_notes_processed` before making any Gmail call.
2. Status-only notes are processed and counted even when they will not appear in the rendered Timeline or Evidence Appendix.
3. Extract and deduplicate the primary raw Case ID plus every supported INC, SR, Activity, CTASK, CHG, PRJTASK, PEA, escalation, or related-record ID explicitly present in the Case notes, then **freeze the record-ID query set**.
4. Do not add customer-name-only, product-name-only, owner-only, participant-only, broad date-only, or **Gmail-discovered IDs** to the frozen query set.
5. Ambiguous note boundaries, a truncation indicator, or a note-parsing failure makes context collection incomplete.

#### Gmail

1. On the first frozen-ID query, call `gmail_list_threads(query: "<record ID>", snapshot_before: "", page_token: "", max_results: 100)` and retain the server-returned `snapshot_before`. Reuse that one shared snapshot for every later list and read call in the run.
2. For every frozen record ID, call `gmail_list_threads` repeatedly, passing each real `next_page_token` unchanged as the next `page_token`, until `next_page_token` is absent and `complete=true`. Record each successful page in `query_pages_completed`, and increment `record_id_queries_completed` only after that ID's full chain ends with `complete=true`; page size is a transport control, not a result limit.
3. Track tokens within each query chain. A missing completion field or a malformed, **repeated or regressing** page token or cursor is a **protocol failure**; never infer completion and never impose an arbitrary thread limit.
4. Deduplicate the union by `thread_id` while retaining match provenance: every record-ID query that returned each thread. Record the canonical deduplicated count as `unique_threads_discovered`; `gmail_threads_discovered` and `gmail_threads_enumerated` are collection-detail aliases that must resolve to the same deduplicated set before reads begin.
5. For every unique thread, call `gmail_read_thread_page(thread_id: "<thread ID>", snapshot_before: "<shared snapshot>", cursor: "")`, then pass each real `next_cursor` unchanged until `next_cursor` is absent and `complete=true`. Read every message in the thread at or before the shared snapshot, even when an individual message does not contain the searched ID.
6. Track cursors per thread and reject missing, malformed, repeated, or regressing values. If a listed thread **disappears or becomes unreadable** before completion, the gate fails.
7. Deduplicate by `message_id`, retain thread/query provenance, derive canonical `messages_expected` from each stable thread message count and `message_chunks_expected` from each message's stable chunk count, and reassemble every message body from all ordered chunks. Verify the reassembled normalized UTF-8 body against the advertised `body_bytes` and SHA-256 `body_sha256`; increment canonical `messages_completed` and `message_chunks_completed` only after successful completion. The `gmail_messages_expected`, `gmail_messages_read`, `body_chunks_expected`, and `body_chunks_read` collection-detail aliases must mirror those canonical counters exactly.
8. Require the ordered message count and `manifest_sha256` to remain identical on every page for a thread. Any changed manifest, count mismatch, chunk gap, byte mismatch, or hash mismatch blocks the review.
9. **Attachment metadata** such as filename and MIME type may be recorded, but attachment payloads are out of scope and are not fetched; unread attachment content does not block completeness.
10. Messages received after `snapshot_before` are intentionally excluded from the current run. Messages received at or before the shared snapshot are all in scope.
11. A **zero-result query** is complete only when its successful response has no next page token and `complete=true`. If every frozen-ID query has zero results and all query pagination chains completed, continue with the fully processed CaseToMD evidence and state: `Gmail: no additional relevant evidence found`. This is the complete-context form of the existing branch where **Gmail search succeeds but returns no relevant messages**.
12. If the **Gmail tool is missing or the search call fails**, including authentication, timeout, quota, application, pagination, cursor, or read failure, identify Gmail as the unavailable required server and block the review.
13. User-supplied documents may supplement these sources after the complete-context gate passes. Label them by filename and date; do not present a parsed shell, extraction artifact, or unsupported inference as a live case record.

#### Context Coverage Ledger

Maintain this internal **Context Coverage Ledger** for the collection run:

```text
case_notes_discovered
case_notes_processed
record_ids_planned
record_id_queries_completed
query_pages_completed
unique_threads_discovered
threads_read_complete
messages_expected
messages_completed
message_chunks_expected
message_chunks_completed
body_hashes_verified
snapshot_before
gmail_threads_discovered
gmail_threads_enumerated
gmail_threads_read_complete
gmail_messages_expected
gmail_messages_read
body_chunks_expected
body_chunks_read
manifest_hashes_stable
```

The complete-context gate passes only when all of these checks succeed:

- `case_notes_discovered == case_notes_processed`.
- `record_ids_planned == record_id_queries_completed`, and all query pagination chains ended with `complete=true`; `query_pages_completed` contains every successfully traversed page.
- `unique_threads_discovered == threads_read_complete`.
- `messages_expected == messages_completed`.
- `message_chunks_expected == message_chunks_completed`.
- `body_hashes_verified == messages_completed`.
- Confirm that all thread manifest hashes were stable; equivalently, `manifest_hashes_stable == threads_read_complete`.
- The collection-detail aliases must also satisfy `gmail_threads_discovered == gmail_threads_enumerated == unique_threads_discovered` and `gmail_threads_read_complete == threads_read_complete`.
- The message and chunk aliases must satisfy `gmail_messages_expected == messages_expected`, `gmail_messages_read == messages_completed`, `body_chunks_expected == message_chunks_expected`, and `body_chunks_read == message_chunks_completed`.
- Therefore `gmail_threads_discovered == gmail_threads_read_complete`, `gmail_messages_expected == gmail_messages_read`, `body_chunks_expected == body_chunks_read`, `body_hashes_verified == gmail_messages_read`, and `manifest_hashes_stable == gmail_threads_read_complete` must also hold.
- `snapshot_before` is non-empty and identical on every Gmail list and read call.

Duplicate thread or message discovery is expected and must be deduplicated before these equalities; duplication never permits a source item to be skipped. No analysis or report drafting may begin until every equality and completion flag passes.

If any source, pagination chain, cursor chain, count, body verification, manifest, or completion flag is incomplete, respond with `Context collection incomplete — review not generated.` using exactly this block:

```text
Context collection incomplete — review not generated.

Case notes: <processed>/<discovered>
Record-ID queries: <completed>/<planned>
Gmail threads: <completed>/<discovered>
Gmail messages: <completed>/<expected>
Blocker: <exact sanitized failure>
```

This blocking output must not output Executive Summary, Technical & Incident Assessment, Progress Summary, Root cause, ownership conclusion, or Evidence Appendix content. **Partial results** from the failed run may be used only for the four sanitized counts; they must not support a partial RCA or any other conclusion. A retry starts from the same raw Case ID with a new `snapshot_before` and **discards the partial corpus** rather than reusing it.

### Step 3 - Build the Evidence Ledger

After the complete-context gate passes, create the case-specific evidence ledger before analysis. Process the complete corpus, then use relevance only to decide what substantiated content is displayed. Give every case-specific item a sequential identifier and record:

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
- No dedicated `Future prevention` field, recommendation, or prevention narrative belongs in the Executive Summary. Exclude raw logs, detailed troubleshooting, configuration detail, and extended cause analysis.
- An evidence-stated next action or checkpoint may appear in the Executive Summary and `Ownership & Next Step`, even when preventive in purpose, but describe it only as an existing commitment or current planned work with its evidenced owner and ETA—never as an agent recommendation or implemented control.

#### Technical & Incident Assessment contract

- Start with problem clarification, then explain the evidence and reasoning needed to support or qualify the summary conclusion.
- Every paragraph must add at least one of the following: environment or affected-component detail; a finding or interpreted log excerpt; causal reasoning or an RCA-state explanation; a ruled-out alternative, unresolved gap, or missing validation; solution, workaround, implementation, or verification detail; or **Existing prevention controls** already implemented and evidenced.
- Remove any paragraph that only paraphrases an Executive Summary sentence. Do not repeat the full incident, impact, response, status, owner, or ETA unless the technical explanation requires a specific distinction.
- Existing prevention controls appear only in the technical assessment under the relevant problem and only when evidence shows they are implemented. Planned or committed preventive work that is not implemented must not be labeled an Existing prevention control; describe it only as planned or committed work or as the next committed checkpoint. Omit controls when absent and never generate a prevention recommendation.

#### Adaptive ADM depth

- ADM mode activates only when the user explicitly requests `ADM` or `Avaya Diagnostic Methodology`, matched case-insensitively.
- ADM mode increases the depth of `Technical & Incident Assessment` only; it must not lengthen the Executive Summary or create a second ADM block.
- When evidence permits, cover **Details/Findings**, **Problem Clarification**, **Cause**, and **Solution** as analytical dimensions inside the chosen technical structure. Adapt the prose to the case; it is not required to display four mechanical ADM headings.
- For each of the four ADM dimensions, provide evidence-supported content when available; when a dimension is relevant but the evidence cannot support a conclusion, state an explicit unresolved evidence or investigation gap. Omit genuinely inapplicable dimensions and never add rigid filler or invention.

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

1. Revalidate `case_notes_discovered == case_notes_processed` and `record_ids_planned == record_id_queries_completed`, with every query pagination chain ending in `complete=true`.
2. Revalidate the canonical equalities `unique_threads_discovered == threads_read_complete`, `messages_expected == messages_completed`, and `message_chunks_expected == message_chunks_completed`.
3. Revalidate `body_hashes_verified == messages_completed`, confirm all thread manifest hashes were stable, verify every Gmail/thread/message/chunk alias still equals its canonical counter, and confirm one identical non-empty `snapshot_before` across all Gmail calls.
4. If any coverage check fails during reflection, discard the draft and emit only the prescribed context-collection blocking output.
5. Map every factual body claim to at least one appendix row.
6. Confirm dates, IDs, names, quotes, calculations, owners, and ETA values against the ledger.
7. Confirm unresolved conflicts remain visible and are not silently resolved.
8. Confirm mitigation maturity does not overstate lab or planned work as production success.
9. Confirm owners are evidence-backed or explicitly `unassigned`.
10. Confirm `Ownership & Next Step` only restates actions, owners, and dates already present in evidence, including preventive commitments; it must never generate a new recommendation or label planned work as an implemented control.
11. Confirm the rendered body contains no Evidence ID or citation suffix.
12. Confirm the appendix is last and reverse-maps every evidence row through `Supports`.
13. Confirm the zero-evidence response is exactly `unknown`.
14. Confirm every rendered list or table containing dates or timestamps is in ascending date/time order, with undated entries last.
15. Confirm the Executive Summary is one 6-8 sentence paragraph with no subheadings, dedicated prevention field, recommendation, or prevention narrative; an evidence-stated preventive checkpoint may appear only as an existing commitment or current planned work.
16. Confirm its root-cause statement uses at most one sentence as the one-sentence technical conclusion; keep detailed cause analysis only in Technical & Incident Assessment.
17. Remove any technical paragraph that merely paraphrases the summary without adding a finding, mechanism, validation result, or unresolved gap.
18. When explicit ADM mode applies, verify: For each of the four ADM dimensions, include evidence-supported content or, when relevant evidence is unavailable, an explicit unresolved evidence or investigation gap; omit inapplicable dimensions, never add rigid filler or invention, and do not create a second outline or ADM block.
19. Confirm the displayed Progress Summary count follows the available substantive evidence: include up to five milestones, render one when only one exists, and do not pad or repeat evidence.

### Step 7 - Produce the Review

After both the complete-context gate and the evidence gate pass, use this common structure:

```markdown
# Case Review - <Case ID>
**Title:** <evidence-backed title or unknown>
**Status:** <status or unknown> | **Priority:** <priority or unknown> | **Assignee:** <assignee or unknown>
**Source:** <actual source system and record type>
**Case record freshness:** <N days / date unavailable>
**Last substantive progress age:** <N days / no substantive progress evidenced>
**Customer:** <account/site/contact or unknown>

## Executive Summary
<Write one natural-language paragraph of 6-8 sentences covering the conclusion-level incident with time and location, affected scope, impact, key response, one-sentence technical conclusion, mitigation and production outcome, current status, and the next evidenced checkpoint with owner and ETA; use lowercase unknown for unsupported details; exclude raw logs, detailed diagnostics, configuration detail, extended cause analysis, and any dedicated prevention field, recommendation, or narrative; an evidence-stated preventive next checkpoint is allowed only as an existing commitment or current planned work, never as an agent recommendation or implemented control.>

## Technical & Incident Assessment
<Start with problem clarification; add environment or affected-component detail, findings or interpreted log evidence, causal or RCA-state reasoning, solution or workaround implementation and verification, and unresolved gaps or missing validation; distinguish planned preventive work from implemented controls; do not fully restate the event, impact, response, or status from the Executive Summary.>

## Progress Summary
<Up to five substantive milestones supported by evidence, oldest first, without citation markers; render one when only one exists. Do not pad or repeat evidence.>

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

- Choose exactly one structure for the section; the multi-problem and single-issue structures are mutually exclusive.
- **Multi-problem:** use `Problem Statement`, then `Problem 1 - <Record ID>`, `Problem 2 - <Record ID>`, and so on. For each problem, cover problem clarification, evidence-backed findings, cause or RCA-state reasoning, solution and validation, mitigation maturity and production outcome, and unresolved gaps.
- **Single issue:** use `Incident & RCA Summary` and cover the same semantic sequence: problem clarification, evidence-backed findings, cause or RCA-state reasoning, solution and validation, mitigation maturity and production outcome, and unresolved gaps.
- Put **Existing prevention controls** only under the relevant problem and only when evidence confirms they are implemented. Describe evidence-stated but not-yet-implemented preventive work as planned or committed work, not as an existing control.

Do not render both conditional structures. Do not create a standalone telemetry section or a second ADM block.

---

## Non-Negotiable Rules

- Complete source context before analysis: process every Case note, exhaust every frozen record-ID query page, and read and verify every snapshot-eligible message in every unique matched Gmail thread before analysis or review generation. Relevance affects display only, never retrieval.
- Evidence over opinion; unknown over invention.
- Case-specific evidence is required for case-specific conclusions.
- Evidence numbering is dynamic, not a three-item quota.
- Progress Summary has no minimum count: render up to five evidence-supported substantive milestones, including one when only one exists, without padding or repeated evidence.
- Evidentiary authority and Management display priority are separate.
- Status pings inform stall detection even when omitted from the displayed timeline.
- Closed/Resolved records are not stale merely because they are old.
- Domain rules are conditionally activated and never substitute for case evidence.
- Production success requires post-change production evidence.
- The report must not generate risk lists, risk scores, manager directives, prevention priorities, or recommendations.
- Evidence-stated preventive next actions or checkpoints may appear in the Executive Summary and `Ownership & Next Step` only as existing commitments or current planned work, never as agent recommendations or implemented controls.
- Existing prevention controls belong only in Technical & Incident Assessment under the relevant problem and only when evidence confirms implementation; planned or committed work is not an existing control.
- The Executive Summary states the conclusion; Technical & Incident Assessment explains the evidence, mechanism, reasoning, validation, and unresolved gaps that justify or qualify it.
- The main body stays citation-free; the final appendix preserves the audit chain.
- Rendered date/time lists and tables are ordered oldest to newest; undated items follow dated items.
- The manager should understand the Executive Summary, evidence basis, owner, ETA state, RCA state, mitigation maturity, production outcome, and next checkpoint without rereading the raw case.
