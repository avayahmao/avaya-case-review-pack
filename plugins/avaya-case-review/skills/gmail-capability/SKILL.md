---
name: gmail-capability
description: Provide backward-compatible Gmail APIs plus the exhaustive case-review thread/message collection workflow.
---

# Gmail Global Skill

This skill allows Antigravity to interact with the user's Gmail / Avaya email inbox in any workspace or project. For case reviews, the required current workflow is **Complete Context Before Analysis**; broad inbox exploration is not a substitute for case-bounded collection.

## Capabilities

1. **Enumerate Case Threads**:
   Use `gmail_list_threads(query, snapshot_before, page_token, max_results)` for the primary raw Case ID only until every `next_page_token` is exhausted under one shared non-empty snapshot. Do not query Case-note-derived or Gmail-discovered related IDs.

2. **Read Complete Threads**:
   Use `gmail_read_thread_page(thread_id, snapshot_before, cursor)` for every unique matched thread until every `next_cursor` is exhausted. Read every snapshot-eligible message and verify body chunks, byte counts, hashes, and stable manifests.

3. **Send Email**:
   Use native MCP tool `gmail_send(to, subject, body)` or run fallback script:
   `python %USERPROFILE%\.gemini\tools\gmail\gmail_mcp_server.py send "<to>" "<subject>" "<body>"`

4. **Backward-Compatible APIs**:
   `gmail_search(query)` and `gmail_read(message_id)` remain available for compatibility and explicit legacy rollback. They are never the completeness workflow for a case review and must not determine which case context is collected.

## Complete Context Before Analysis

Process every Case note before Gmail collection, retain supported related IDs as Case context, set the Gmail query plan to the primary raw Case ID only, and maintain the Context Coverage Ledger with `record_ids_planned == record_id_queries_completed == 1`. Do not analyze or generate a review until every primary-query list page, unique thread, message, body chunk, hash, and manifest check passes. If collection fails, return `Context collection incomplete` with only sanitized counts and the blocker; do not emit review sections.

## MCP Tools
When the `gmail` MCP server is active in Antigravity, use native tools:
- `gmail_list_threads(query, snapshot_before, page_token, max_results)`
- `gmail_read_thread_page(thread_id, snapshot_before, cursor)`
- `gmail_search(query)`
- `gmail_read(message_id)`
- `gmail_send(to, subject, body)`
