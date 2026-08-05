# Gmail Cloud Bridge Deployment Runbook

This runbook deploys the exhaustive Gmail MCP cloud endpoint. It updates the
existing Gmail MCP Apps Script Web App; it does not deploy the optional
governance example in `examples/optional-appsscript/Code.gs`.

## Deployment gate

Complete these steps in order:

1. Open the existing Gmail MCP Apps Script project, not the optional governance example.
2. Enable the Advanced Gmail Service. Select the service named **Gmail**, API version **v1** (shown as `Gmail v1`).
3. Replace the Web App source with `tools/gmail/cloud/GmailMcpBridge.gs`.
4. Save the project and run a syntax check in the Apps Script editor.
5. Select **Deploy > Manage deployments**, edit the existing Web App, select **New version**, and deploy it.
6. Keep the existing deployment URL; do not create or distribute a replacement endpoint URL.
7. Complete controlled authorization if Google requests the newly required Gmail scopes. Confirm the expected account and scopes before allowing access.
8. Verify a zero-result `list_threads` request returns `complete=true`. Then run a real case query and confirm that it retains one stable snapshot across the complete page-token chain.
9. Verify one multi-message thread through cursor exhaustion and complete the documented hash/count checks for its manifest, messages, and body chunks.
10. **Only then** deploy the updated local Gmail MCP modules and Agent SKILL.

If the Advanced Gmail Service cannot be enabled, authorization cannot be
completed, or either verification fails, stop. Do not deploy the local SKILL
that activates the exhaustive gate.

## Collection contract

- `gmail_list_threads(query, snapshot_before, page_token, max_results)` creates
  or reuses the collection snapshot and exposes real Gmail page tokens.
- `gmail_read_thread_page(thread_id, snapshot_before, cursor)` reads every
  snapshot-eligible message and body chunk in the matched thread. Its cursor is
  exhausted before the thread is counted complete.
- The first successful list response establishes a non-empty
  `snapshot_before`; every later list and read call uses that exact value.
- The related-ID boundary is frozen only after every Case note has been
  processed. It includes the primary ID and supported related IDs explicitly
  present in the case notes; IDs discovered later in Gmail do not expand it.
- Attachments are excluded from content retrieval. Attachment metadata may be
  reported, but attachment bodies are outside this completeness contract.
- Any source, page, cursor, manifest, hash, count, or snapshot failure returns
  `Context collection incomplete` and blocks analysis and report generation.
- `gmail_search`, `gmail_read`, and `gmail_send` remain backward-compatible
  APIs. Search and read cannot satisfy the exhaustive completeness gate.

This cloud source is operational Gmail MCP code. It is intentionally separate
from the optional governance example, and `setup_env.ps1` does not copy it to
the local Gmail tools directory.

## Rollback

Redeploy the prior Apps Script version to the same Web App URL. If local deployment has already occurred, these instructions do not automatically roll back local files: stop Antigravity, deactivate the current exhaustive Agent
SKILL, and restore the prior package's
`plugins/avaya-case-review/skills/case-review/SKILL.md` and prior Gmail MCP
source under `tools/gmail` to the deployed
`%USERPROFILE%\.gemini\config\plugins\avaya-case-review\` and
`%USERPROFILE%\.gemini\tools\gmail\` paths (or rerun the prior package's
installer). Restart Antigravity only after the prior local package is restored.
Keep the exhaustive Agent gate inactive until the prior cloud version and the
zero-result, real-case pagination, and multi-message cursor checks pass again.
The existing Managed Edge broker and explicit `legacy_playwright` rollback
behavior remain unchanged.
