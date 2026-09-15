# Case review speed optimization implementation plan

## Goal

Reduce end-to-end case-review latency without weakening Complete Context Before
Analysis, the single-primary-ID query rule, snapshot/cursor/hash verification,
or deterministic durable-record output.

## Evidence baseline

The 2026-09-15 SR test collected 26 Case notes, 12 threads, and 57 messages.
The broker recorded 43 thread-page requests over roughly 5m49s, one terminal
read timeout, 79.4 aggregate queue-wait seconds, and an active broker whose
build ID did not match the installed v1.10.1 runtime. The case artifact was
valid, but orchestration repeated rendering/final verification and began a
second collection after an artifact already existed.

## Global constraints

- Do not change cloud deployment or widen the Gmail query scope.
- Do not parallelize browser contexts, skip messages, loosen hashes/counts, or
  reuse a partial snapshot after a terminal collection failure.
- Preserve backward-compatible `case_record.py` commands and existing output
  bytes for current workflows.
- Keep all new telemetry sanitized: no Case IDs, thread/message IDs, queries,
  tokens, cursors, bodies, or hashes.
- Every behavior change gets RED/GREEN tests before production code.

## Tasks

### Task 1 — Broker build coherence guard

Change the runtime broker client to detect a live state whose `build_id` does
not equal the current runtime build before sending health or data requests.
Fail closed with a stable sanitized build-mismatch error; do not auto-start a
second broker against the same Edge profile. Add unit/integration coverage for
matching, mismatched, stale, and absent state, and preserve the existing lazy
startup contract.

### Task 2 — One-shot deterministic record finalization

Add a `case_record.py finalize` command that atomically performs the existing
validated update, deterministic present, artifact/hash write, and self-
verification in one process. It must preserve idempotence, same-snapshot
rejection, incomplete-coverage immutability, and the existing `update`,
`present`, and `verify-final` commands. Update the canonical case-review skill
to use `finalize` for new/follow-up output and add tests proving one-shot output
matches the existing canonical artifact byte-for-byte.

### Task 3 — Sanitized collection telemetry

Add optional run/phase correlation and safe counters to broker/collector logs:
run sequence, first-page vs continuation, retry count/reason, response bytes,
segment/message/chunk counts, and phase timings. Existing log allowlists must
reject sensitive values. Add tests for allowlists and aggregation fields.

### Task 4 — Benchmark and acceptance

Run focused/full suites, a synthetic collector benchmark, and a warm/cold
broker benchmark. Compare against the baseline with p50/p95 request and total
run times. Do not use production message content as benchmark data. Record
whether the P0 fixes reduce repeated finalization and prevent old-build broker
reuse; leave cloud batching/page-cap changes as a separate plan if the data do
not justify them.

## Completion criteria

- Tasks 1–3 have reviewed commits and green focused tests.
- Existing supported-host suite remains green.
- No output contract or coverage equality changes.
- Benchmark results identify the next safe optimization; no speculative cloud
  change is shipped without byte/hash regression coverage.
