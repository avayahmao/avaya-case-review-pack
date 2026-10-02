---
name: "case-review"
description: "Generate and continue an evidence-grounded Operation Manager case review for Avaya Siebel and ServiceNow records. Accept raw IDs such as INC7386572, 1-23659220672, Activity IDs, CTASK..., CHG..., or PRJTASK...; use CaseToMD plus Gmail; route deterministic standard, compact, follow-up, technical, flow, or full output; enforce final-output integrity; maintain one durable follow-up record per Case ID through closure; and, only on explicit request and approval, draft or apply sanitized closed-case learning to local domain knowledge."
---

# Case Review

Produce an evidence-grounded management review without weakening source completeness, causal proof boundaries, or durable-record integrity. The deterministic collector and presenter own mechanical validation; do not reproduce their work manually.

## Final response invariant

After `finalize-overlay` succeeds, it must be the final tool call. The assistant's final answer must be the complete stdout byte-for-byte, with no preface, summary, omission, or appended text. Never replace the canonical standard review with only a Case Card or a statement that the remaining sections were persisted. If stdout is unavailable or truncated, run `case_record.py present --markdown-only` as the final tool call and return that complete stdout unchanged.

## Normal review fast path

Use this path for `Review <Case ID>`, status checks, and ordinary follow-ups. Do not ask the user to choose a format.

For a small or medium case (up to 50 Case notes and 10 Gmail messages) with healthy source tools, target completion within three minutes. This budget never permits skipped evidence. Use one retrieval pass, one evidence-synthesis pass, and one finalization call; do not reopen settled fields or inspect implementation source during the review.

1. Call `get_case_markdown(report_id: "<raw Case ID>")` exactly once. Process every discrete Case note, including status-only activities, and retain related IDs as Case context. Gmail scope remains the primary raw Case ID only.
2. After all Case notes are processed, run:

   ```text
   python <skill-directory>/scripts/gmail_collect_case.py collect --case-id "<raw Case ID>"
   ```

   Continue only when the collector and `manifest.json` both report `status: pass`. Read `digest.json`, never `corpus.json`. For collections over 10 messages, scan the complete corpus once with `gmail_collect_case.py snippets --term <case-specific-term> ... --chars 30000`; it returns bounded excerpts while reporting the total messages scanned. Pull a full body with `query` only for the one or two decisive messages whose snippets need surrounding context. For 10 or fewer messages, selected `query` calls may be issued as one parallel batch. Do not inspect `query --help` during a review.
3. Read only the case-relevant domain excerpts described below. References guide interpretation; they are never case evidence.
4. Build one structured evidence state: primary problem, current progress and impact, problem lineage, official status and ownership, RCA state, mitigation maturity, production outcome, proof-state technical fields, documented next action, separate evidence-linked technical advice, substantive milestones/timeline, evidence rows, and optional visual context.
5. Run `case_record.py schema` once. It is the complete machine-readable overlay contract. Do not inspect presenter source, tests, MCP schemas, or example payloads during a normal review.
6. Write one UTF-8 judgment overlay as `<case-record-directory>/review-overlay.json` and retain it as the auditable finalization input; do not create a cleanup file in the repository. Run the one-shot preflight/finalize command:

   ```text
   python <skill-directory>/scripts/case_record.py finalize-overlay --manifest <collection>/manifest.json --overlay <overlay.json> --case-id <Case ID> --request "<original request>"
   ```

   The command runs `build-payload` validation before any durable mutation and tolerates trailing commas in the agent-authored overlay. Do not run a separate JSON parser. Fix any reported semantic error and rerun the same command; do not recollect CaseToMD or Gmail. Return verified Markdown stdout unchanged.

Do not reopen `chat-output.md`, run `verify-final`, reread memory, or perform a second format review after successful finalization. Finalization already validates, writes, hashes, and verifies the canonical response.

## Complete-context gate

The review is blocked unless all of these are true:

- `case_notes_discovered == case_notes_processed`.
- The collector used one primary-ID query and one non-empty shared snapshot.
- List pagination and every thread cursor chain completed.
- Threads, messages, chunks, body hashes, and stable manifests satisfy the passing manifest equalities.
- No CaseToMD truncation, authentication failure, unreadable thread, or protocol failure occurred.

A completed zero-result primary-ID Gmail query with `complete=true` is valid evidence that Gmail added nothing. `AUTH_REQUIRED` or any incomplete chain is not a zero-result outcome.

If CaseToMD fails before a ledger exists, output only:

```text
Context collection incomplete — review not generated.

Case notes: 0/unknown
Record-ID queries: 0/unknown
Gmail threads: 0/unknown
Gmail messages: 0/unknown
Blocker: CaseToMD unavailable — <exact sanitized failure>
```

For any later collection failure, use the collector's same five-line blocker with the verified counts. Do not analyze partial evidence or mutate the durable record. Use `--resume` only for an interrupted collection under its existing snapshot; otherwise a genuine retry starts fresh.

Read [case-review-contract.md](references/case-review-contract.md) only when the collector is unavailable and manual MCP rollback is required, when maintaining the contract, or when diagnosing a disputed gate. Do not load it during a passing normal review.

## Evidence-backed analysis

- Reconstruct the whole-case storyline in chronological order: original objective or primary fault, intended action, blocker, working hypotheses, corrected finding, implemented action/outcome, then secondary problems.
- Treat Case notes and Gmail as one evidence stream. Recency and message length do not redefine the primary problem.
- Preserve source conflicts. Use `unknown` when stronger evidence does not resolve them.
- Separate observations, confirmed mechanisms, hypotheses, mitigation, administrative status, and production outcome.
- A restart, failover, upgrade, escalation, assignment, or closure does not by itself prove cause or durable recovery.
- Use RCA states `Under Investigation`, `Suspected`, `Identified`, `Validated`, or `unknown` only as supported.
- Use one mitigation state: `Proposed`, `Lab Validated`, `Production Deployed`, `Production Outcome Confirmed`, or `None Active`.
- Distinguish logs `requested`, `collected`, `attached`, and `analyzed`.
- Owners, due dates, impact, and escalation state must be evidenced; otherwise use `unassigned`, `not stated`, or `unknown`.
- For open work, calculate Case record freshness and last substantive progress age. Over 7 days is `STALE`; over 30 days is `CRITICAL STALL`. Do not flag Closed/Resolved cases solely because they are old.

Create dynamic evidence rows `E1..EN` with `Source`, `Date`, `Verbatim evidence / data`, and `Supports`. Do not split, duplicate, or invent evidence. Every factual Case Card, technical, timeline, and visual value must map to evidence. If no verifiable case evidence exists, output exactly `unknown` and do not persist.

Rendered dated lists and tables are oldest first; equal timestamps preserve source order and undated entries follow dated entries. The Investigation Progress flow is the visual-context exception: sort `visual_context.transitions` oldest first only when every transition has a date. If any transition lacks a date, preserve the authored sequence and caption it as having unknown precise timing; its arrows never prove causation. The presenter enforces these rules mechanically.

Every successful structured mode begins with `# Case Review - <ID>` and a concise four-line `## Executive Summary`. The first line combines official Status with a brief Reported issue from `current.primary_problem`; the other lines give customer impact, the most important confirmed finding, and production outcome in plain language. Use `unknown` for unsupported values. Write `current.impact` and `current.confirmed_finding` as one short, jargon-free statement each; put exact trace and log progress with uncertainty in `current.current_progress`. The summary must reflect the whole case, including material contradictions, without promoting a hypothesis to a finding. Mention NotebookLM validation only when an actual case-specific result is available and substantiated by evidence; otherwise omit it entirely. NotebookLM is not a required collection source.

Follow the summary with `## Case Card` (`## Current Case Card` in full or follow-up mode). `Reported Problem / Symptom` comes from `current.primary_problem`. `Current State` comes from `current.current_progress` and explains concrete investigation progress, trace or log findings, and remaining validation gaps rather than repeating the official status. Keep RCA state, mitigation maturity, and production outcome distinct. The card's `### Action Plan` contains only the existing evidence-stated `Required Action / Next Step` from `current.next_action`, plus its evidenced owner and due date; use `not stated` when no commitment is documented. A separate `## Technical Advice` section then gives recommended immediate diagnostics, conditional potential solutions, and long-term steps. Each recommendation identifies relevant case evidence or a specific evidence gap. A proposed step is never rendered as an existing commitment, implemented work, or a confirmed cause.

## Domain routing

After CaseToMD identifies the products and symptoms, read only matching excerpts:

| Topic | Reference |
|---|---|
| AES, CTI, JTAPI, TSAPI, CSTA, DMCC | [aes-cti-jtapi.md](references/aes-cti-jtapi.md) |
| Contact Center, Oceana, AACC, POM, CMS | [contact-center.md](references/contact-center.md) |
| Recording, ACRA, WFO/WFE, Verint | [recording-wfo.md](references/recording-wfo.md) |
| Analytics, Oceanalytics, Kubernetes | [analytics-kubernetes.md](references/analytics-kubernetes.md) |
| Security, AVAPT/NVAPT, CVE | [security-vulnerability.md](references/security-vulnerability.md) |
| SIP, voice quality, SBC | [sip-voice-quality.md](references/sip-voice-quality.md) |
| Certificates, WebLM, login, outage | [certificates-login-outage.md](references/certificates-login-outage.md) |
| Digital channels | [digital-channels.md](references/digital-channels.md) |
| IP Office | [ip-office.md](references/ip-office.md) |
| Log collection and traces | [log-collection.md](references/log-collection.md) |

For a large reference, use its contents block or `rg -n` with the case-specific product, error, and protocol terms, then read only the matching section. Never read the same reference twice in one review. Locate an approved local learning overlay with `case_record.py knowledge-path --domain <reference-stem>` and read it only when it exists.

## Build the Structured Review Snapshot

`case_record.py schema` defines all required current, evidence, technical, lineage, milestone, timeline, and visual fields. Use allowed proof states exactly: `OBSERVED`, `CONFIRMED MECHANISM`, `SUSPECTED`, `CONTRADICTED`, `NOT TESTED`, `PRODUCTION DEPLOYED`, `OUTCOME CONFIRMED`, `NOT OBSERVED`, `NOT COLLECTED`, `NOT APPLICABLE`, or `UNKNOWN`.

Set required `current.impact` to one concise plain-language statement of evidenced customer or service impact (otherwise `unknown`) and keep `current.confirmed_finding` equally concise and plain (otherwise `unknown`). Set required `current.current_progress` to the specific work completed, exact trace or log findings, and remaining uncertainty (otherwise `unknown`). Set required `presentation.technical_advice` to an object with `immediate_diagnostics: [{action, basis}]`, `potential_solutions: [{action, condition, basis}]`, and `long_term_steps: [{action, basis}]`. Each array may be empty when no grounded advice is available; the presenter shows that gap honestly. `basis` identifies the case evidence or exact missing evidence that makes the step relevant. Do not put an unevidenced action into `current.next_action` to fill a gap; that field represents a documented next commitment in the Case Card's Action Plan.

For the normal overlay, use top-level `evidence_rows` and write each evidence fact once. Keep the rows oldest-first; `build-payload` assigns `E1..EN` and derives `evidence_digest`, `presentation.evidence_register`, optional timeline rows from `by` plus `change`, and milestones from `milestone_change`. If more than five milestones are marked, it preserves the first two and last three. Do not duplicate those generated arrays in `presentation`.

Set `reviewed_at` to current UTC with a `Z` suffix. Mechanical coverage counters come only from the passing manifest. Never construct the payload inline in a shell command.

The presenter chooses `standard`, `compact`, `follow-up`, `technical`, `flow`, or `full`. Plain reviews use investigation-complete `standard`; `compact` is explicit-only. Read [output-modes.md](references/output-modes.md) only for an explicit nonstandard mode or presenter maintenance, not for a normal standard review.

## Persist and Present Deterministically

Every successful review updates one durable per-Case-ID record. The prior record is a post-analysis comparison baseline only; every genuine follow-up still requires fresh CaseToMD and Gmail evidence.

The normal path is one `finalize-overlay` command. Separate `build-payload`, `finalize`, `case_record.py update`, `case_record.py present --markdown-only`, and `verify-final` remain diagnostic compatibility commands, not extra normal-review steps.

Read [case-record-lifecycle.md](references/case-record-lifecycle.md) only for persistence failures, migration, reopened-case handling, or learning operations. On administrative closure, show the learning option. Draft learning only on explicit request. Apply sanitized learning only after explicit approval.

## Non-negotiable boundaries

- Evidence over opinion; `unknown` over invention.
- Complete source context before analysis.
- Primary raw Case ID only for Gmail.
- Attachments are metadata-only unless separately supplied by the user.
- Domain guidance never counts as case proof.
- Outputs must not generate risk scores, unsupported manager directives, prevention priorities, or unevidenced recommendations.
- Evidence-stated actions remain existing commitments. New diagnostic or solution advice is labeled as recommendation or conditional hypothesis, with its evidence basis and validation condition visible.
- Administrative closure remains separate from RCA and production outcome.
