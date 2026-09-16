# Antigravity Speed and Error Hardening Implementation Plan

> **For agentic workers:** Use TDD for each task and run the focused tests before moving to the next task.

**Goal:** Remove the observed Antigravity configuration/encoding failures and reduce case-review orchestration overhead without weakening evidence coverage.

**Architecture:** Keep Gmail and CaseToMD retrieval unchanged, but make the Windows installer emit parser-safe UTF-8 configuration, propagate UTF-8 to every MCP process, and make the case-review contract provide an explicit fast path with a machine-readable Gmail response shape and one-shot finalization.

**Tech Stack:** Windows PowerShell 5.1, Python `unittest`, JSON/Markdown skill contracts.

## Global Constraints

- Preserve exhaustive primary-ID collection, snapshot/cursor equality, body byte/hash checks, and deterministic finalization.
- Do not modify the deployed Cloud Bridge or widen Gmail query scope.
- Preserve unrelated working-tree changes.
- Never use large inline `python -c` payload construction for case-review artifacts.

### Task 1: Parser-safe Antigravity MCP configuration

- Add a regression test proving generated `mcp_config.json` has no UTF-8 BOM and includes `PYTHONIOENCODING=utf-8` for Gmail and CaseToMD.
- Update `setup_env.ps1` to write UTF-8 without BOM and add the environment value to both MCP server definitions.
- Run the installer contract tests and inspect the first three bytes of a generated config.

### Task 2: Fast-path case-review contract

- Document the exact `gmail_list_threads` and `gmail_read_thread_page` response fields (`segments`, `message_count`, `chunk_count`, `body_bytes`, `body_sha256`, `manifest_sha256`, completion token fields).
- Tell Antigravity to use the deterministic `finalize` command once, not inspect internal scripts, probe response shape repeatedly, or run a second `verify-final` after successful finalization.
- Add a small payload-template/validation command if the existing helper can support it without changing output bytes.

### Task 3: Timestamp and evidence-state hardening

- Add tests for rejecting future `reviewed_at` values and for keeping suspected mechanisms explicitly suspected in structured output.
- Implement only the minimal validation needed; do not infer RCA from prose.
- Run case-record and contract regression tests.

### Task 4: Verification

- Run focused installer, case-record, and contract suites.
- Run `rg` to confirm no plugin Markdown contains Chinese characters.
- Report full-suite environmental failures separately if they recur.
