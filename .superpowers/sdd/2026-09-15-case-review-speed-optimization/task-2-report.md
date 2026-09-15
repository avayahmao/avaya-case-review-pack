# Task 2 Report — One-shot deterministic record finalization

## Status

Implemented the backward-compatible `case_record.py finalize` command. It accepts a complete structured payload plus `--case-id` and `--request`, validates and prepares the update under the per-case record lock, renders before durable replacement, writes the record and canonical Markdown/hash artifacts with atomic file replacement, verifies the stored artifact internally, and emits the canonical UTF-8 Markdown exactly once.

The existing `update`, `present`, and `verify-final` commands remain available and retain their existing interfaces.

## TDD evidence

RED was observed for all six focused cases before production implementation: the CLI rejected the unknown `finalize` command and the direct API cases failed because `finalize_case_record` did not exist.

GREEN focused command:

```text
python -m unittest tests.test_case_record.CaseRecordTests.test_finalize_first_review_emits_one_verified_canonical_markdown tests.test_case_record.CaseRecordTests.test_finalize_exact_retry_is_idempotent tests.test_case_record.CaseRecordTests.test_finalize_rejects_divergent_same_snapshot_without_mutation tests.test_case_record.CaseRecordTests.test_finalize_rejects_incomplete_payload_without_mutation tests.test_case_record.CaseRecordTests.test_finalize_matches_update_then_present_byte_for_byte tests.test_case_record.CaseRecordTests.test_finalize_render_failure_leaves_existing_files_unchanged
```

Result: `Ran 6 tests ... OK`.

Regression command:

```text
python -m unittest tests.test_case_record tests.test_case_review_presentation tests.test_case_review_contract
```

Result: `Ran 101 tests ... OK`.

Static checks:

```text
python -m py_compile plugins/avaya-case-review/skills/case-review/scripts/case_record.py tests/test_case_record.py
git diff --check
```

Result: both exited successfully; Git reported only expected working-tree line-ending normalization notices.

## Coverage

- First-review record, Markdown artifact, and SHA-256 creation.
- Exact retry idempotence with byte-for-byte durable-file equality.
- Divergent same-snapshot rejection with no mutation.
- Incomplete-coverage rejection with no mutation.
- Byte-for-byte parity with the prior `update` plus `present --markdown-only` path.
- Render-failure immutability.
- Internal artifact verification and exact UTF-8 stdout bytes on Windows.

## Documentation

Updated canonical Step 8, the output-mode command contract, and the durable record lifecycle to use `finalize` for normal new/follow-up output while documenting the legacy commands as supported compatibility surfaces.

## Concerns

A repository-wide `unittest discover` run was started but did not complete within the bounded observation window because the broader integration suite remained active; it was stopped. No failure appeared in the output observed before stopping. Task-focused lifecycle, presenter, and contract suites are green.

## Fix round 1

Review identified that the first implementation used atomic replacement per file but did not provide transaction-level rollback across `record.json`, `record.md`, `chat-output.md`, and `chat-output.sha256`. A failure after an earlier replacement could therefore leave a mixed durable state.

The finalizer now stages every changed output before replacement, retains per-target backups through internal verification, and restores the exact prior files on any replacement or verification exception. Reopened-case learning-overlay suspension is included in the same staged transaction when applicable. Legacy single-file command behavior remains unchanged.

RED was observed with injected failures at `record.md`, `chat-output.md`, `chat-output.sha256`, and final verification: the previous implementation left changed durable bytes in all four failing scenarios. The `record.json` boundary was also exercised and already failed before mutation.

GREEN focused command:

```text
python -m unittest tests.test_case_record
```

Result: `Ran 24 tests ... OK`.

Regression command:

```text
python -m unittest tests.test_case_record tests.test_case_review_presentation tests.test_case_review_contract
```

Result: `Ran 103 tests ... OK`.

The obsolete lifecycle sentence instructing callers to return a separate verified candidate was removed; `finalize` stdout remains the sole canonical response.
