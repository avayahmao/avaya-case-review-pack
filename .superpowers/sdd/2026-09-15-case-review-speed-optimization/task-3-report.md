# Task 3 report — Sanitized collection telemetry

## Result

Added best-effort, allowlisted broker telemetry without changing the cloud API,
Gmail request parameters, response bodies, or collection coverage semantics.

- Every broker process has a random positive `session_sequence`; each dispatched
  request receives a monotonically increasing `run_sequence`.
- Collection records distinguish `COLD`/`WARM` browser state and
  `FIRST_PAGE`/`CONTINUATION` without recording query, snapshot, token, cursor,
  thread, message, body, or hash values.
- Records include queue, service, and total elapsed milliseconds; UTF-8 response
  bytes; requested/result/thread/segment/message/chunk counts; and safe retry and
  timeout reason enums.
- Managed Edge navigation/content-delivery retries and broker browser-restart
  retries contribute to the same request aggregate.
- Existing request correlation remains available only for generated UUIDv4
  request IDs; Case-like request IDs are rejected by the logger and omitted by
  broker emission.
- Telemetry extraction and log writes are both fail-open, so failures cannot
  alter a successful Gmail response.

## TDD evidence

The new allowlist/serialization and broker aggregation tests were run before
implementation and failed on the missing constants, constructor argument,
fields, and retry properties. After implementation:

- `python -m unittest tests.test_gmail_broker_state.SanitizedRotatingLoggerTests ...<telemetry integration tests>`: 16 passed.
- `python -m unittest tests.test_gmail_broker_protocol tests.test_gmail_broker_client tests.test_gmail_broker_state tests.test_gmail_edge_adapter`: 144 passed on the first complete run. A later repeat produced one existing 100 ms cleanup-timing failure at 104.85 ms; that test passed immediately in isolation.
- Focused broker telemetry/integrity selection: 12 passed.
- `python -m py_compile` for both changed runtime modules and all changed Python test modules: passed.
- `git diff --check`: passed (Git reports only expected CRLF normalization notices).

## Concerns

`tests.test_gmail_broker_integration` has existing sub-second Windows socket
deadlines that are intermittent under Python 3.14's event loop. A full-file run
had unrelated concurrency/latency timeouts; all 12 telemetry, privacy, retry,
timeout, and fail-open broker tests pass together. No production behavior was
relaxed to hide those timing failures.
