# Exhaustive Context Collection and Completeness Gate Design

**Date:** 2026-08-04

**Status:** Approved for implementation planning

## Problem

The current case-review workflow retrieves one CaseToMD Markdown record, runs case-bounded Gmail searches, and reads selected messages judged relevant. The Agent is instructed to prioritize important email, but the Gmail MCP exposes neither result pagination nor a proof that every matching thread and every message in that thread was read.

A review can therefore be well reasoned from the retrieved subset while still missing an older case note, a less prominent email thread, or an earlier message in a thread. The requested operating principle is stricter: review content must not be generated until the Agent has processed every Case note returned by the official record and every Gmail message in every thread matched by the primary Case ID and Case-note-derived related record IDs.

## Selected Approach

Use the Advanced Gmail Service in the Gmail MCP Apps Script endpoint to provide page-token-based thread enumeration and cursor-based, size-bounded thread reading. Add a mandatory Agent-side completeness ledger. Review generation is allowed only after the ledger proves complete coverage.

Changing the Agent prompt alone is explicitly insufficient because the current Gmail tool contract cannot prove exhaustive enumeration.

## Non-Negotiable Principle

> **Complete Context Before Analysis:** Before generating any review content, the Agent must process every Case note returned by CaseToMD, enumerate every Gmail thread matched by the primary Case ID and all related record IDs found in those Case notes, and read every message in every unique matched thread. If completeness cannot be proven, the Agent must stop without generating a partial review.

This principle has higher priority than relevance ranking, management display priority, report brevity, or time-to-first-draft.

## Scope

### Included

- Every discrete Case note or activity block returned in the CaseToMD Markdown record.
- The primary raw Case ID.
- Every supported case, task, change, activity, escalation, or related-record ID explicitly present in the Case notes.
- Every Gmail thread matched by an exact search for any ID in that frozen query set.
- Every message in every unique matched thread as of a fixed collection snapshot.
- Message metadata and normalized body text.

### Excluded

- Customer-name-only, product-name-only, owner-only, participant-only, or broad date-only Gmail searches.
- IDs discovered only in Gmail messages; the query universe is frozen from the Case record before Gmail enumeration starts.
- Attachment contents. Attachment filenames and MIME metadata may be recorded, but unread attachment content does not block completeness.
- Messages received after the collection snapshot.

## End-to-End Collection Flow

1. Fetch the official CaseToMD record with the raw Case ID.
2. Identify every discrete Case note/activity block in the returned record.
3. Process every note into the internal source ledger, including routine status pings.
4. Extract and deduplicate the primary ID plus every supported related record ID explicitly present in those notes.
5. Freeze the record-ID query set. Do not add names, participants, products, or Gmail-discovered IDs.
6. Start Gmail enumeration. The first Gmail call creates a server-side `snapshot_before` value; all subsequent list and read calls reuse it.
7. For each frozen record ID, call `gmail_list_threads` repeatedly until `next_page_token` is absent and `complete=true`.
8. Deduplicate the union of results by `thread_id` while retaining which record-ID queries matched each thread.
9. For each unique thread, call `gmail_read_thread_page` repeatedly until `next_cursor` is absent and `complete=true`.
10. Reassemble every message body from its ordered chunks and validate byte count and SHA-256.
11. Deduplicate messages by `message_id` and build the evidence ledger.
12. Validate the Context Coverage Ledger.
13. Only after every coverage equality and completion flag passes may the Agent begin analysis and report generation.

All retrieved context is processed, but only substantive evidence is rendered. Routine notes and non-substantive email remain available for stall/activity analysis without being copied into the report body or Evidence Appendix unnecessarily.

## Gmail MCP Tool Contract

Existing `gmail_search`, `gmail_read`, and `gmail_send` tools remain unchanged for backward compatibility. Case review uses two new exhaustive tools.

### `gmail_list_threads`

Input:

```json
{
  "query": "1-23508794022",
  "snapshot_before": "2026-08-04T10:15:30Z",
  "page_token": "",
  "max_results": 100
}
```

For the first query page of the collection run, `snapshot_before` may be omitted. The server creates and returns it. The Agent must pass that exact value to every subsequent query and thread-read call in the run.

Output:

```json
{
  "success": true,
  "query": "1-23508794022",
  "snapshot_before": "2026-08-04T10:15:30Z",
  "thread_ids": ["thread-a", "thread-b"],
  "next_page_token": "opaque-token",
  "complete": false
}
```

Rules:

- The cloud endpoint uses `Gmail.Users.Threads.list` and its real `nextPageToken`.
- The server applies the snapshot cutoff to the exact record-ID query.
- `complete=true` only when the Gmail API returns no next page token.
- `max_results` is a page-size control, not a business-result limit.
- Repeated page tokens, malformed responses, or a missing completion field are protocol errors.
- A zero-result query is complete only after a successful response with no next page token and `complete=true`.

### `gmail_read_thread_page`

Input:

```json
{
  "thread_id": "thread-a",
  "snapshot_before": "2026-08-04T10:15:30Z",
  "cursor": ""
}
```

Output:

```json
{
  "success": true,
  "thread_id": "thread-a",
  "snapshot_before": "2026-08-04T10:15:30Z",
  "message_count": 8,
  "manifest_sha256": "...",
  "segments": [
    {
      "message_id": "message-1",
      "internal_date": "2026-08-01T08:00:00Z",
      "from": "sender@example.com",
      "to": ["recipient@example.com"],
      "cc": [],
      "subject": "Case update",
      "body_chunk": "...",
      "chunk_index": 0,
      "chunk_count": 1,
      "body_bytes": 1234,
      "body_sha256": "...",
      "attachment_names": []
    }
  ],
  "messages_completed": 1,
  "next_cursor": "opaque-cursor",
  "complete": false
}
```

Rules:

- The cloud endpoint uses `Gmail.Users.Threads.get` and returns every message at or before the snapshot, not only messages containing the searched ID.
- Messages are ordered by normalized internal date ascending, with stable message-ID tie breaking.
- `manifest_sha256` is computed from the complete ordered list of included message IDs and remains identical on every page.
- The server normalizes a message body from `text/plain`; when unavailable, it extracts readable text from `text/html`.
- Attachment payloads are never returned. Attachment names and MIME types may be included as metadata.
- The full normalized UTF-8 body is hashed before chunking. Chunk boundaries must not split UTF-8 code points.
- The server controls the response byte budget so the response remains safely below the broker's 8 MiB frame limit.
- `cursor` is opaque, server-issued, and validated against thread ID and snapshot. Invalid, repeated, or regressing cursors are protocol errors.
- `complete=true` only after every message and every body chunk is returned.

## Cloud Apps Script Architecture

The current Gmail MCP Apps Script Web App is the cloud execution layer. It must be upgraded to use the Advanced Gmail Service:

- `Gmail.Users.Threads.list`
- `Gmail.Users.Threads.get`

The existing `search`, `read`, and `send` actions remain available. New actions implement the exhaustive tool contract.

The repository will add an explicitly named cloud deployment source, for example:

```text
tools/gmail/cloud/GmailMcpBridge.gs
```

This file is the source of the Gmail MCP cloud Web App. It is separate from `examples/optional-appsscript/Code.gs`, which remains an inactive, optional Sheets/Docs governance example. The installer must not confuse or merge the two modules.

Deployment requires enabling the Advanced Gmail Service in the existing Apps Script project and publishing a new version of the same Web App deployment. A controlled Google authorization confirmation may be required if scopes change. Edge broker authentication architecture and browser profiles do not change.

## Local Gmail Runtime Changes

The local MCP and broker add two methods without changing existing schemas:

- `gmail_list_threads`
- `gmail_read_thread_page`

Required changes include:

- MCP tool schemas and dispatch.
- Broker protocol allowed-method validation.
- Managed Edge action/parameter mapping.
- Explicit legacy backend URL mapping, with no automatic fallback.
- Parameter validation for snapshot, page token, page size, thread ID, and cursor.
- Sanitized errors that never include queries, message content, tokens, or cursors.
- Response-size enforcement below the existing broker frame limit.

## Case Note Completeness

Completeness is defined against the official CaseToMD record returned for the raw Case ID.

- Every discrete note/activity block in that record must be identified and processed before Gmail collection.
- Status-only notes are processed and counted even when omitted from the displayed timeline.
- The note count is derived from the structured record boundaries available in the returned Markdown.
- If note boundaries cannot be enumerated unambiguously, a truncation indicator appears, or parsing fails, the completeness gate fails.
- The Agent must not silently treat a partial or structurally ambiguous record as complete.

## Context Coverage Ledger

The Agent maintains an internal ledger with at least:

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
```

The review gate passes only when:

```text
case_notes_discovered == case_notes_processed
record_ids_planned == record_id_queries_completed
all query pagination chains ended with complete=true
unique_threads_discovered == threads_read_complete
messages_expected == messages_completed
message_chunks_expected == message_chunks_completed
body_hashes_verified == messages_completed
all thread manifest hashes were stable
```

Duplicate threads across record-ID queries and duplicate messages across data paths are expected and are deduplicated before the equality checks. Duplicate discovery never permits a source item to be skipped.

## Failure Behavior

The Agent must stop before analysis if any completeness requirement fails. It outputs only:

```text
Context collection incomplete — review not generated.

Case notes: <processed>/<discovered>
Record-ID queries: <completed>/<planned>
Gmail threads: <completed>/<discovered>
Gmail messages: <completed>/<expected>
Blocker: <exact sanitized failure>
```

It must not output Executive Summary, Technical & Incident Assessment, Progress Summary, RCA, mitigation conclusions, ownership conclusions, Timeline, or Evidence Appendix from a partial corpus.

Blocking conditions include:

- CaseToMD failure, ambiguous note boundaries, or detected truncation.
- Gmail tool absence, authentication failure, timeout, quota exhaustion, or application error.
- Missing, malformed, repeated, or regressing page tokens/cursors.
- A listed thread disappearing or becoming unreadable before completion.
- Changed thread manifest hash within the same snapshot run.
- Message-count, chunk-count, byte-count, or body-hash mismatch.
- Response truncation or missing `complete` metadata.

After authentication or transient service recovery, retry starts from the beginning with the same raw Case ID and a new snapshot. Partial results from the failed run are not reused for report generation.

## Snapshot and Concurrency Semantics

- One server-generated snapshot is shared across every record-ID query and thread read in a review run.
- Thread enumeration searches only content at or before that snapshot.
- Thread reads include every message at or before that snapshot, even if the message itself does not contain a searched ID.
- Messages received after the snapshot are intentionally excluded and belong to the next review run.
- Completion is therefore an auditable "complete as of" guarantee rather than an assertion that the mailbox can never change.

## Security, Privacy, and Quotas

- Search queries remain exact record IDs; broad person or customer searches are prohibited.
- Logs and diagnostics contain counts, state, elapsed time, and sanitized error codes only.
- Logs never contain query values, subjects, senders, recipients, bodies, attachment names, page tokens, cursors, cookies, or OAuth data.
- Gmail API quota and transient errors use bounded retry/backoff. Exhausted retries block the review rather than returning partial context.
- No arbitrary thread or message limit is allowed. Page size and response byte budget exist only for transport safety.
- The Agent may process content incrementally into its internal ledger, but it may not analyze or draft conclusions until the final gate passes.

## Backward Compatibility

- Existing `gmail_search`, `gmail_read`, and `gmail_send` names and schemas remain unchanged.
- The default backend remains the Single Managed Edge broker.
- No automatic fallback to legacy Playwright is introduced.
- Existing authentication, status, diagnostics, login, and stop controls remain unchanged.
- Only the case-review workflow requires the new exhaustive methods and completeness proof.

## Documentation Impact

Implementation must align:

- `plugins/avaya-case-review/skills/case-review/SKILL.md`
- Gmail MCP/broker/cloud-source documentation
- README Markdown and HTML
- Manager Onboarding Markdown and HTML
- Technical Design Markdown and HTML
- Release Notes Markdown and HTML
- Presentation sources if they describe retrieval behavior
- Runtime deployment allowlists and release manifest when new source/runtime files are added

## Verification Strategy

Automated coverage must include:

1. Every Case note is processed before ID extraction or Gmail calls.
2. Only primary and Case-note-derived record IDs form the query set.
3. Multiple Gmail result pages are followed to token exhaustion.
4. Zero-result queries pass only with a successful complete pagination chain.
5. Duplicate threads across queries are read once and retain match provenance.
6. Every message in a multi-message thread is returned in chronological order.
7. Large message bodies are chunked without UTF-8 corruption and reassemble to the advertised byte count and SHA-256.
8. HTML-only message bodies normalize to readable text.
9. Attachment names may be reported while payloads remain excluded.
10. Snapshot-after messages are excluded consistently.
11. Token/cursor loops, malformed responses, disappearing threads, manifest changes, count mismatches, hash mismatches, truncation, quota exhaustion, authentication failure, and timeout all block review generation.
12. The failure response contains only coverage counts and the sanitized blocker; no partial review sections appear.
13. Existing Gmail tool schemas remain backward compatible.
14. Broker frame-size and log-redaction invariants remain enforced.

## Acceptance Criteria

The feature is complete when:

- the Agent cannot generate a review before the Context Coverage Ledger passes;
- every Case note returned by CaseToMD is counted and processed;
- every primary/related-ID Gmail query reaches page-token exhaustion;
- every unique matched thread and every snapshot-eligible message is read completely;
- message manifests, chunks, byte counts, and SHA-256 values validate;
- any incomplete source produces only the prescribed blocking response;
- attachments remain explicitly outside the completeness gate;
- existing Gmail tools and Single Managed Edge behavior remain compatible;
- the cloud Apps Script source is clearly separated from the optional governance example;
- repository and deployed runtime copies are synchronized; and
- the complete automated test suite passes.
