---
name: "case-review"
description: "Generate and continue an evidence-grounded Operation Manager case review for Avaya Siebel and ServiceNow records. Accept raw IDs such as INC7386572, 1-23659220672, Activity IDs, CTASK..., CHG..., or PRJTASK...; use CaseToMD plus Gmail; route deterministic standard, compact, follow-up, technical, flow, or full output; enforce final-output integrity; maintain one durable follow-up record per Case ID through closure; and, only on explicit request and approval, draft or apply sanitized closed-case learning to local domain knowledge."
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

For a matching domain, also locate an approved local learning overlay with `python <case-review-skill-directory>/scripts/case_record.py knowledge-path --domain <reference-stem>`. Read it after the packaged reference when it exists. Local learning remains diagnostic guidance and never counts as case-specific proof.

---

## Workflow

### Explicit QA Requests

When the user explicitly asks for QA scoring, case-quality assessment, QA statistics, or supplies the QA rubric columns, route to the bundled `qa` skill and `scripts/qa.py`. QA is a separate management assessment layer: its scores must not be used as evidence for RCA, mitigation maturity, production outcome, customer impact, or risk classification. Do not perform CaseToMD/Gmail collection for a QA-only request unless the user also asks for a case review. Use the QA skill's validation and rendering contract for Markdown, CSV, and JSON inputs.

When the user explicitly asks for alarm QA, an alarm-ticket audit, or supplies the `Check / Cause / Chronic / PLUS` alarm columns, route to the separate `alarm-audit` skill and `scripts/alarm_audit.py`. Never mix alarm-audit scores with the ordinary non-alarm QA rubric.

### Step 1 - Plan the Retrieval

1. Extract the primary identifier. Supported record types are **INC, SR, Activity, CTASK, CHG, or PRJTASK**.
2. Retrieve CaseToMD first. Do not start Gmail collection until every Case note has been processed and the Gmail query scope has been fixed to the primary raw Case ID only.
3. Do not analyze evidence, draft conclusions, or generate any review content until the complete-context gate passes.
4. Select domain references only after case symptoms and components are known.
5. Reserve a final context-coverage, evidence-coverage, and format review before producing the answer.
6. Do not read conclusions from an existing durable case record before completing the fresh current-run analysis. The prior record is a post-analysis comparison baseline, not evidence.

### Step 2 - Retrieve Required Sources

#### CaseToMD

1. Call `get_case_markdown(report_id: "<Case ID>")` and **pass the raw ID without normalization**.
2. The expected response contains `success`, `case_id`, `title`, `source`, `filename`, and `markdown`.
3. Treat `markdown` as the official case-record source, not as proof that every embedded hypothesis is correct.
4. If the CaseToMD tool is missing, the call fails, or `success` is false, identify the CaseToMD failure and stop. Do not fabricate a review. If this happens before the Context Coverage Ledger exists, use the separate pre-ledger blocker below; do not emit any review section.

CaseToMD pre-ledger blocker:

```text
Context collection incomplete — review not generated.

Case notes: 0/unknown
Record-ID queries: 0/unknown
Gmail threads: 0/unknown
Gmail messages: 0/unknown
Blocker: CaseToMD unavailable — <exact sanitized failure>
```

### Complete Context Before Analysis

Before generating any review content, process **every discrete Case note** returned by CaseToMD, including routine status pings; retain explicitly stated related record IDs in the Case source ledger for analysis; query Gmail using the **primary raw Case ID only**; and read every message in every unique matched thread. Relevance ranking may affect display only after this gate passes; it must never determine what is read or processed within the primary-ID-matched thread set.

#### Case notes and primary-only Gmail query scope

1. Identify every discrete note or activity block from the structured boundaries in the CaseToMD Markdown. Count each note in `case_notes_discovered`, process it into the internal source ledger, and count it in `case_notes_processed` before making any Gmail call.
2. Status-only notes are processed and counted even when they will not appear in the rendered Timeline or Evidence Appendix.
3. Extract and deduplicate supported INC, SR, Activity, CTASK, CHG, PRJTASK, PEA, escalation, or related-record IDs explicitly present in the Case notes for the source ledger and related-record analysis, but set the Gmail query plan to exactly one ID: the **primary raw Case ID**. Set `record_ids_planned` to `1`.
4. Do not add any related record ID, customer name, product name, owner, participant, broad date, or **Gmail-discovered IDs** to the Gmail query plan. Related records remain case context only.
5. Ambiguous note boundaries, a truncation indicator, or a note-parsing failure makes context collection incomplete.

#### Gmail

1. The bootstrap input for the primary Case ID query may be empty: call `gmail_list_threads(query: "<primary raw Case ID>", snapshot_before: "", page_token: "", max_results: 100)`. The first successful response **must return a non-empty `snapshot_before`**; if it is absent or empty, block collection. Save that returned value exactly.
2. For the primary Case ID only, call `gmail_list_threads` repeatedly, passing each real `next_page_token` unchanged as the next `page_token`, until `next_page_token` is absent and `complete=true`. Every later list/read call must pass that **exact same non-empty `snapshot_before`**; never send an empty value or create a new snapshot after bootstrap. Record each successful page in `query_pages_completed`, and set `record_id_queries_completed` to `1` only after the primary ID's full chain ends with `complete=true`; page size is a transport control, not a result limit.
3. Track tokens within each query chain. A missing completion field or a malformed, **repeated or regressing** page token or cursor is a **protocol failure**; never infer completion and never impose an arbitrary thread limit.
4. Deduplicate the primary-ID query results by `thread_id` and retain primary-query provenance. Record the canonical deduplicated count as `unique_threads_discovered`; `gmail_threads_discovered` and `gmail_threads_enumerated` are collection-detail aliases that must resolve to the same deduplicated set before reads begin.
5. For every unique thread, call `gmail_read_thread_page(thread_id: "<thread ID>", snapshot_before: "<shared snapshot>", cursor: "")`, then pass each real `next_cursor` unchanged until `next_cursor` is absent and `complete=true`. Read every message in the thread at or before the shared snapshot, even when an individual message does not contain the searched ID.
6. Track cursors per thread and reject missing, malformed, repeated, or regressing values. If a listed thread **disappears or becomes unreadable** before completion, the gate fails.
7. Deduplicate by `message_id`, retain thread/query provenance, derive canonical `messages_expected` from each stable thread message count and `message_chunks_expected` from each message's stable chunk count, and reassemble every message body from all ordered chunks. Verify the reassembled normalized UTF-8 body against the advertised `body_bytes` and SHA-256 `body_sha256`; increment canonical `messages_completed` and `message_chunks_completed` only after successful completion. The `gmail_messages_expected`, `gmail_messages_read`, `body_chunks_expected`, and `body_chunks_read` collection-detail aliases must mirror those canonical counters exactly.
8. Require the ordered message count and `manifest_sha256` to remain identical on every page for a thread. Any changed manifest, count mismatch, chunk gap, byte mismatch, or hash mismatch blocks the review.
9. **Attachment metadata** such as filename and MIME type may be recorded, but attachment payloads are out of scope and are not fetched; unread attachment content does not block completeness.
10. Messages received after `snapshot_before` are intentionally excluded from the current run. Messages received at or before the shared snapshot are all in scope.
11. A **zero-result primary-ID query** is complete only when its successful response has no next page token and `complete=true`. If the primary-ID query has zero results and its pagination chain completed, continue with the fully processed CaseToMD evidence and state: `Gmail: no additional relevant evidence found`. This is the complete-context form of the existing branch where **Gmail search succeeds but returns no relevant messages**.
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
- `record_ids_planned == record_id_queries_completed == 1`, and the primary-ID query pagination chain ended with `complete=true`; `query_pages_completed` contains every successfully traversed page.
- `unique_threads_discovered == threads_read_complete`.
- `messages_expected == messages_completed`.
- `message_chunks_expected == message_chunks_completed`.
- `body_hashes_verified == messages_completed`.
- Confirm that all thread manifest hashes were stable; equivalently, `manifest_hashes_stable == threads_read_complete`.
- The collection-detail aliases must also satisfy `gmail_threads_discovered == gmail_threads_enumerated == unique_threads_discovered` and `gmail_threads_read_complete == threads_read_complete`.
- The message and chunk aliases must satisfy `gmail_messages_expected == messages_expected`, `gmail_messages_read == messages_completed`, `body_chunks_expected == message_chunks_expected`, and `body_chunks_read == message_chunks_completed`.
- Therefore `gmail_threads_discovered == gmail_threads_read_complete`, `gmail_messages_expected == gmail_messages_read`, `body_chunks_expected == body_chunks_read`, `body_hashes_verified == gmail_messages_read`, and `manifest_hashes_stable == gmail_threads_read_complete` must also hold.
- The bootstrap request may pass an empty `snapshot_before`; the successful bootstrap response establishes a non-empty `snapshot_before`, and every subsequent Gmail list/read call reuses that exact value.

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

This blocking output must not output Executive Summary, Technical & Incident Assessment, Progress Summary, Root cause, ownership conclusion, or Evidence Appendix content. **Partial results** from the failed run may be used only for the four sanitized counts; they must not support a partial RCA or any other conclusion. A retry starts from the same raw Case ID with a new `snapshot_before`, discards the partial corpus, and does not reuse it.

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

### Whole-case storyline and problem lineage

Before classifying RCA or drafting any report section, reconstruct an internal whole-case storyline from the complete corpus in chronological order:

- **Primary problem / original customer objective:** identify the earliest evidenced fault, risk, planned change, or service objective that opened the case. A later source may refine or explicitly supersede it, but recency or message length alone never redefines it.
- **Intended action:** record what the customer or support team originally planned to do to address the primary problem.
- **Blocking question or decision point:** record why the intended action paused, changed, or required additional investigation.
- **Working hypotheses and actions:** retain intermediate interpretations, troubleshooting advice, and proposed actions as the state of knowledge at that time; do not rewrite them as confirmed causes merely because they drove activity.
- **Corrected finding:** record later evidence that confirms, rejects, or supersedes an earlier interpretation, and state what changed in the understanding.
- **Implemented action and primary outcome:** identify the action that actually addressed the original objective and the evidence-supported outcome.
- **Secondary problems:** record issues discovered or caused during investigation or implementation, including their relationship to the primary problem. Do not promote them to the primary problem merely because the latest or longest source emphasizes them.

Treat Case notes and Gmail as one chronological evidence stream. **Latest-message recency and verbosity must not determine narrative weight.** Use recency to establish the current state and use stronger later evidence to correct earlier claims, but allocate summary space according to each event's role in the primary problem lifecycle. Distinguish a primary cause from a blocker, a secondary symptom, an implementation side effect, and an incidental observation.

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
- Classify each material item as the primary problem, a blocker or decision point, a secondary problem, or an incidental observation before selecting the report structure.
- In a multi-problem assessment, present the primary problem first, then blockers and secondary problems in causal or chronological relationship to it; do not flatten every finding into an equal problem.
- Do not force a planned renewal, migration, maintenance activity, or other original customer objective into an RCA state unless evidence shows that it is itself a fault requiring causal analysis.
- Keep telemetry calculations inside the relevant problem description and show the source inputs.
- Use RCA states: `Under Investigation`, `Suspected`, `Identified`, or `Validated`. Do not label a root cause Identified/Validated without supporting evidence.
- Use exactly one mitigation maturity state:
  - **Proposed**
  - **Lab Validated**
  - **Production Deployed**
  - **Production Outcome Confirmed**
  - **None Active**
- A lab test, one repaired record, a scheduled rollout, or an engineer's success report without post-change production evidence **must not be described as production resolution**.

### Structured Analysis Before Presentation

Do not draft a report while analyzing. Build one structured, evidence-backed case state first:

1. Complete the evidence ledger and whole-case problem lineage.
2. Classify the primary problem, blockers, working hypotheses, corrected findings, actions, outcome, and secondary problems.
3. Set RCA, mitigation maturity, production outcome, ownership, and checkpoint fields.
4. Build the fixed Technical Specification fields and assign an allowed proof state to each.
5. Build milestones, timeline, evidence register, and visual context from evidence only.
6. Route and render the presentation only after persistence succeeds.

Read [output-modes.md](references/output-modes.md) before building the presentation payload. It defines `standard`, `compact`, `follow-up`, `technical`, `flow`, and `full` modes, proof states, adaptive visual rules, and length limits.

ADM activates only when explicitly requested. Represent Details/Findings, Problem Clarification, Cause, and Solution through the structured problem lineage and Technical Specification. Use explicit evidence gaps for unsupported dimensions; do not generate a second ADM outline or filler prose.

### Step 5 - Enforce the Evidence Gate

Every factual answer must pass the internal evidence gate before rendering:

- Build dynamic evidence rows **E1..EN**, where N is the number of verifiable case-specific evidence items. There is no minimum of three.
- Each row must contain `Source`, `Date`, `Verbatim evidence / data`, and `Supports`.
- Every factual value in the Case Card, Technical Specification, visual context, timeline, and full view must map internally to at least one evidence row.
- The `Supports` field reverse-maps evidence to the exact structured field or conclusion.
- `compact`, `technical`, and `flow` outputs contain no Evidence IDs or citation suffixes. Investigation-complete `standard` and `follow-up` render the complete dynamic Evidence Register; explicit `full` renders the same evidence as final Appendix A.
- Answer only the portion supported by evidence. For an unsupported field or disputed conclusion, write `unknown`.
- Distinguish `NOT OBSERVED`, `NOT COLLECTED`, `UNKNOWN`, and `NOT APPLICABLE`; never substitute one for another.
- If no verifiable case-specific evidence exists, **output exactly `unknown`** and stop. Do not persist or render a review.
- **Do not split, duplicate, or invent evidence** to increase the evidence count.
- Domain references may explain evidence but do not count as case-specific evidence by themselves.
- `Appendix A — Evidence Register` is the final section of explicit `full` mode only.

### Step 6 - Reflection and Coverage Review

Before rendering:

1. Revalidate `case_notes_discovered == case_notes_processed` and `record_ids_planned == record_id_queries_completed == 1`, with the primary-ID query pagination chain ending in `complete=true`.
2. Revalidate the canonical equalities `unique_threads_discovered == threads_read_complete`, `messages_expected == messages_completed`, and `message_chunks_expected == message_chunks_completed`.
3. Revalidate `body_hashes_verified == messages_completed`, confirm all thread manifest hashes were stable, verify every Gmail/thread/message/chunk alias still equals its canonical counter, and confirm the bootstrap request may be empty, the bootstrap response establishes a non-empty `snapshot_before`, and subsequent list/read calls reuse that exact value.
4. If any coverage check fails, emit only the prescribed context-collection blocking output and do not update the durable record.
5. Map every factual structured value to evidence and confirm `Supports` reverse mapping.
6. Confirm dates, IDs, names, quotes, calculations, owners, and ETA values against the ledger.
7. Keep unresolved conflicts visible; preserve unsupported values as `unknown` or the precise absence state.
8. Confirm mitigation maturity and production outcome are separate and evidence-backed.
9. Confirm owners are evidence-backed or explicitly `unassigned`.
10. Keep milestones and timeline chronological; do not pad either list.
11. Keep the original objective primary; do not promote a blocker or secondary issue because it is newer or longer.
12. Include only evidenced visual transitions, recurrences, hypotheses, component handoffs, and ownership checkpoints.
13. Confirm the mode router matches the original user request and record review count.
14. Confirm the investigation-complete standard/follow-up contract, explicit-only compact limits, mandatory progress flow, causal assessment, complete visual columns, seven-node Mermaid limit, fixed Technical Specification schema, Timeline, and dynamic Evidence Register.
15. Confirm a failed or incomplete collection will not create or modify a durable case record.
16. Confirm official administrative closure remains separate from RCA state, mitigation maturity, and customer-confirmed production outcome.

### Step 7 - Build the Structured Review Snapshot

After both gates pass, build the v2 payload defined in [output-modes.md](references/output-modes.md). Do not write an Executive Summary or other rendered report first.

The payload must retain the complete coverage counters, current Case Card fields, dynamic evidence digest, and add:

- `technical_spec` with all twelve fixed fields and proof states.
- `problem_lineage` from original objective through outcome and secondary problems.
- chronological `milestones` and `timeline`.
- dynamic `evidence_register` with reverse mapping.
- evidence-only `visual_context` for deterministic selection.

Use `UNKNOWN`, `NOT OBSERVED`, `NOT COLLECTED`, and `NOT APPLICABLE` precisely. Never add a visual-context item that was not established by the case corpus.

### Step 8 - Persist and Present Deterministically

Read [case-record-lifecycle.md](references/case-record-lifecycle.md), write the UTF-8 payload, and run:

```text
python <skill-directory>/scripts/case_record.py update --input <payload.json>
python <skill-directory>/scripts/case_record.py present --case-id <Case ID> --request "<original user request>" --markdown-only
python <skill-directory>/scripts/case_record.py verify-final --case-id <Case ID> --input <candidate-final.md>
```

`present --markdown-only` writes `chat-output.md` plus `chat-output.sha256` and emits the canonical Markdown directly. Put the exact proposed final Markdown in a UTF-8 candidate file, run `verify-final`, and return the verified candidate unchanged. Do not manually shorten, expand, rewrite, or append a second report. A missing artifact, invalid artifact hash, or mismatch blocks completion. JSON-mode `present` retains `mode` and `visual` as the auditable presentation decision.
For follow-ups, use the helper-computed delta returned from the stored record; never reconstruct changes from conversational memory.

Do not persist when context collection is incomplete, the evidence gate fails, or the result is exactly `unknown`. If persistence fails, state `Case record update failed` with the sanitized error and do not claim continuity succeeded.

On administrative closure, show the learning option but do not draft learning unless explicitly requested. Apply sanitized learning only after explicit approval. If the case later reopens, continue the journal and suspend its applied overlay entry pending reclosure and reapproval.

---

## Non-Negotiable Rules

- Complete source context before analysis: process every Case note, exhaust the primary Case ID query pages, and read and verify every snapshot-eligible message in every unique matched Gmail thread before analysis or review generation. Related record IDs remain Case context and never expand Gmail retrieval.
- Reconstruct the complete case storyline before summarizing. The original customer objective anchors the review; later blockers, hypotheses, corrections, actions, outcomes, and secondary problems retain their proportional place in that lifecycle.
- Latest-message recency or verbosity never substitutes for whole-case importance. Use later evidence to establish current state or explicitly correct earlier claims, not to erase the path that produced the outcome.
- Evidence over opinion; unknown over invention.
- Case-specific evidence is required for case-specific conclusions.
- Evidence numbering is dynamic, not a three-item quota.
- Milestones have no minimum count: retain up to five evidence-supported substantive transitions without padding or repetition.
- Evidentiary authority and Management display priority are separate.
- Status pings inform stall detection even when omitted from the displayed timeline.
- Closed/Resolved records are not stale merely because they are old.
- Domain rules are conditionally activated and never substitute for case evidence.
- Production success requires post-change production evidence.
- Outputs must not generate risk scores, manager directives, prevention priorities, or recommendations.
- Evidence-stated actions and checkpoints remain existing commitments, never agent recommendations or implemented controls.
- QA scores are management assessment data, not case-specific technical evidence; never use them to upgrade RCA, mitigation, or production-outcome proof states.
- Existing prevention controls may appear in the Technical Specification only when evidence confirms implementation; planned work is not an existing control.
- `compact`, `technical`, and `flow` stay citation-free. `standard` and `follow-up` include the dynamic Evidence Register; explicit `full` ends with the same register as Appendix A.
- The deterministic presenter owns output mode, visual choice, field limits, and rendering. Do not reproduce its output manually.
- Rendered date/time lists and tables are ordered oldest to newest; undated items follow dated items.
- Every successful review creates or updates one durable per-Case-ID follow-up record; every later review still recollects fresh sources and uses the prior record only for post-analysis delta comparison.
- Incomplete collection never mutates the durable record. Administrative closure never proves RCA or production recovery.
- Closed-case learning is opt-in, sanitized, evidence-strength labeled, user-approved before application, and stored in a persistent local overlay that remains interpretation guidance rather than case proof.
- The default `standard` view must expose the Case Card, Investigation Progress flow, optional secondary diagnostic visual, Causal Assessment, six key Technical Specification fields, available substantive milestones, substantive Timeline, complete dynamic Evidence Register, and durable-record link.
- A follow-up with no material state, ownership, or evidence change routes to investigation-complete `standard`; a materially changed follow-up routes to investigation-complete `follow-up` unless the user explicitly requests another mode. `compact` is explicit-only.
- Explicit `flow` always renders the progress flow and never substitutes a Claim-Evidence Matrix, recurrence comparison, swimlane, or ownership table for it.
- Never shorten away an impact conflict, recovery or post-change validation gap, next-action owner, or due date / ETA. A Claim-Evidence Matrix always retains Claim, Proof state, Evidence, and Validation needed.
