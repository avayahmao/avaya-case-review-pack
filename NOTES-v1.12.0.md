# v1.12.0 — Clearer Case Progress and Technical Advice

Case reviews now open with a concise Executive Summary covering status, the reported issue, impact, critical confirmed finding, and production outcome. The Case Card separates the reported symptom from work completed and unresolved validation. Its Action Plan contains only the next step, owner, and due date already recorded in the case; evidence-linked diagnostics, conditional solutions, and longer-term recommendations appear separately as Technical Advice.

The release also strengthens single-snapshot collection resume integrity with per-thread checkpoints and bounded targeted queries. In local synthetic measurements, 20 threads of 20 KB each reduced cumulative progress writes from 8.28 MB to 0.392 MB for a 0.39 MB corpus; a 500,000-match snippet search fell from 0.789 s / 44.2 MB to 0.002 s / 1.1 MB. These are local collector measurements; the cloud bridge still re-fetches a full thread for each cursor page. The release includes the post-v1.11.0 QA scoring and writing refinement from commit `06a4170`.

The explicit legacy Gmail rollback path also URL-encodes message IDs before building read requests.

Codex upgrades can now stop a broker from the previous installed build after checking its live protocol and identity. Normal Gmail requests continue to require the exact broker build.

The Antigravity installer and cloud verification runbook now read the Cloud Bridge identity correctly from a clean Windows checkout with CRLF line endings.

When Codex and an older Antigravity installation share the Managed Edge profile, the first product to start the broker determines its build. A Codex-only update leaves Antigravity files unchanged but does not guarantee concurrent Gmail use with that older build.

New review overlays must include `current.impact`, `current.current_progress`, and the three `presentation.technical_advice` arrays. Unsupported case facts remain `unknown`, and NotebookLM findings require actual case-specific validation.

For installation, clone the exact `v1.12.0` tag into a unique temporary directory, verify `git describe --exact-match --tags HEAD`, inspect `INSTALL.md`, and run the checked-out no-flag installer for Codex or Antigravity. The installer validates the local release attestation and live Gmail cloud compatibility.
