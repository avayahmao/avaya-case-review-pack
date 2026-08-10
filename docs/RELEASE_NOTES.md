# Release Notes - Avaya Case Review Suite

All notable changes, features, bug fixes, and architectural enhancements for the **Avaya Case Review Suite** are documented here.

---

## [Unreleased]

* Adds a GitHub-rendered **How does it work** Mermaid flowchart to the README and a synchronized pure HTML/CSS workflow view to `README.html`.
* Falls back from rejected full-thread Gmail responses to a snapshot-filtered minimal manifest and cursor-lazy full-message fetches, keeping large threads inside the 30-second broker page timeout without weakening message-count or manifest integrity.
* Returns stable sanitized fetch, validation, normalization, manifest, cursor, and response-stage errors instead of collapsing expected blockers into `APP_ERROR`.
* Updates the existing Gmail MCP Web App deployment to Version 13 and verifies a 100-message thread through 36 cursor pages with 100/100 body byte-count and SHA-256 checks.

---

## [v1.9.0] - 2026-08-10: Codex and Antigravity Installation

### Dual-Host Plugin Distribution

* Adds a Codex-native repository plugin manifest, Git-backed marketplace, bundled Gmail and CaseToMD MCP definitions, and thin Codex skill entry points that preserve the existing canonical case-review workflow.
* Adds a cloud-gated, idempotent `install-codex.ps1` flow while retaining the established Antigravity `install.bat` and `setup_env.ps1` deployment path.
* Adds an Agent installation contract so Codex and Antigravity can safely follow `install this plugin: https://github.com/avayahmao/avaya-case-review-pack`, including checkout inspection, cloud verification, SSO/MFA, and post-install checks.
* Corrects the Git for Windows working-tree encoding attribute while preserving release-wide UTF-8 BOM and CRLF regression enforcement for PowerShell, batch, and cmd entry points.
* Adds Codex packaging and installer regression coverage plus reversible real-install validation, with the complete suite passing 260 tests, 530 subtests, and 14 Apps Script tests.

---

## [v1.8.2] - 2026-08-10: Gmail Body Payload Decoding

### Gmail Cloud Bridge Message Completeness

* Decodes inline Gmail MIME body data returned by the Advanced Gmail Service as an Apps Script byte array instead of silently treating it as an empty body.
* Retrieves large `text/plain` and `text/html` body parts exposed through `body.attachmentId` when they are not actual attachments, while continuing to exclude attachment content.
* Adds regression coverage for inline byte-array bodies, externalized text bodies, empty inline data with an attachment ID, and attachment exclusion.
* Updates the existing Gmail MCP Web App deployment to Version 8 and verifies the affected case at 3 threads, 22 messages, and 22 non-empty message bodies through exhausted cursors.

---

## [v1.8.1] - 2026-08-06: Gmail Cloud Bridge Correctness Fixes

### Snapshot and Cursor Integrity

* Aligns Gmail's second-resolution `before:` query boundary with the read endpoint's inclusive millisecond cutoff, preventing listed threads from becoming empty ghost pages.
* Binds cursor payloads to the normalized thread manifest SHA-256 and rejects stale or mismatched cursors as `INVALID_CURSOR`.
* Keeps the legacy search compatibility path bounded while honoring a caller-supplied `max_results`; exhaustive collection remains on the paginated context APIs.
* Documents the intentional stateless re-fetch behavior and the trade-off against `CacheService` manifest invalidation.
* Updates the existing Gmail MCP Web App deployment to Version 5 and verifies zero-result and full-case pagination/cursor/hash coverage.

---

## [v1.8.0] - 2026-08-06: Exhaustive Context Collection

### Exhaustive Context Collection Deployment

* Adds the version-controlled Advanced Gmail Service cloud source at `tools/gmail/cloud/GmailMcpBridge.gs` and its existing-Web-App deployment and rollback runbook. The source is distributed but intentionally not copied by `setup_env.ps1`.
* Adds `gmail_list_threads` and `gmail_read_thread_page` deployment guidance for one stable snapshot, complete page-token and cursor chains, message/body counts, and hash verification.
* Aligns **Complete Context Before Analysis** documentation: process every Case note and every message in every matched Gmail thread before analysis. The primary and note-derived related-ID boundary is frozen before Gmail retrieval, and attachment bodies remain excluded.
* Requires `Context collection incomplete` with sanitized counts and a blocker whenever source or coverage verification fails. Existing `gmail_search`, `gmail_read`, and `gmail_send` remain backward-compatible APIs but cannot satisfy the exhaustive gate.
* Keeps the Agent gate inactive until the cloud endpoint passes zero-result, real-case pagination, and multi-message cursor verification; this release records the verified deployment and runtime activation.

---

## [v1.7.0] - 2026-08-04: Layered Executive and Technical Reporting

### Executive Report Clarity and Evidence Integrity

* Applies layered disclosure: a one-paragraph, 6-8 sentence Executive Summary contains conclusion-level incident, impact, response, RCA state, mitigation, status, and next-checkpoint information.
* Makes `Technical & Incident Assessment` the exclusive home for problem clarification, findings, causal reasoning, solution validation, and unresolved technical gaps, with explicit anti-duplication checks.
* Keeps ADM depth adaptive inside the technical assessment instead of appending a second rigid ADM outline.
* Removes Future prevention from Executive Summary. Implemented prevention controls remain technical evidence; planned preventive work remains an evidence-stated checkpoint rather than an Agent recommendation.
* Makes Progress Summary evidence-driven (`up to five` milestones) so sparse records are never padded or repeated.
* Orders rendered date/time content from oldest to newest, with undated entries last, and uses lowercase `unknown` for unsupported required facts.

### Documentation, Distribution, and Safety

* Rewrites technical-direction and vendor-handoff guidance as conditional, evidence-triggered references rather than automated causal or routing judgments.
* Synchronizes README, Manager Guide, Technical Design, HTML presentation, and the 12-slide PowerPoint deck with the current report contract and Single Managed Edge broker architecture.
* Moves the unused Google Apps Script governance prototype out of active tools and the release archive, preserving it only as an optional source example.
* Expands regression coverage to 213 tests, including PPTX-visible-text geometry, template hierarchy, strict HTML structure, release-manifest safety, sparse evidence, ADM, and prevention-state boundaries.

---

## [v1.6.0] - 2026-08-03: Single Managed Edge Gmail Broker

### Gmail Authentication and Multi-MCP Reliability

* Adds one per-user loopback Edge broker that owns the dedicated `edge_broker_profile` and serializes browser work for all Gmail MCP processes.
* Adds lazy startup, lifetime cross-session ownership locking, two-hour idle shutdown, structured authentication errors, sanitized diagnostics, and explicit `status`, `diagnostics`, `start`, `login`, and `stop` controls.
* Keeps `gmail_search`, `gmail_read`, and `gmail_send` schemas unchanged. The default backend is `GMAIL_BACKEND=edge_broker`; `GMAIL_BACKEND=legacy_playwright` remains an explicit one-release rollback with no automatic fallback.
* Retains Chromium installation and `chrome_profile` only for rollback; broker logs never contain queries, message content, recipients, cookies, or tokens.
* Treats a closed login window as recoverable when SSO has already persisted, restoring the headless context and running one safe verification probe before reporting success.

## [v1.5.0] - 2026-08-02: Executive Report Readability Redesign

### Executive Report Readability Redesign

* Moves all rendered evidence into a final reverse-mapped `Appendix A — Evidence Register`.
* Removes inline Evidence annotations from the executive body.
* Removes generated risk lists and recommended actions so Managers retain judgment ownership.
* Keeps the internal evidence gate, source-conflict handling, and production-confirmation safeguards unchanged.
* Aligns the optional Google Apps Script reference for Google Docs/Sheets output with the appendix contract and migrates the previous eight-column tracker schema.

---

## [v1.4.0] - 2026-08-02: Evidence-Grounded Workflow Hardening

### Evidence-Grounded Workflow Hardening

* **Dynamic Evidence Gate**
  * Adds `Evidence 1..N` entries with Source, Date, Verbatim evidence / data, and Supports.
  * Answers only evidence-supported questions; when no verifiable case-specific evidence exists, outputs exactly `unknown`.
  * Prevents evidence splitting, duplication, or invention to reach a target count.
* **Source Retrieval & Conflict Handling**
  * Restores raw Case ID handling for INC, SR, Activity, CTASK, CHG, and PRJTASK.
  * Defines explicit CaseToMD/Gmail missing, failed, and no-result behavior.
  * Separates evidentiary authority from management display priority and preserves unresolved source conflicts.
* **Freshness & Activity Accuracy**
  * Separates Case record freshness from Last substantive progress age.
  * Excludes Closed/Resolved cases from age-only staleness flags.
  * Retains routine status pings for stall analysis while omitting non-substantive pings from the displayed timeline.
* **Technical & Mitigation Accuracy**
  * Gates domain sanity checks on matching case-specific evidence.
  * Distinguishes Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, and None Active.
  * Keeps all action items exclusively in `Targeted Recommendations`.
* **Regression Coverage**
  * Adds nine contract scenarios covering closed records, single and multi-problem reviews, Gmail no results, status-only activity, lab-versus-production outcomes, missing tools, source conflicts, and zero evidence.
* **Documentation Parity**
  * Synchronizes [Manager Onboarding](MANAGER_ONBOARDING_GUIDE.md), [Technical Design](TECHNICAL_DESIGN_DOCUMENT.md), their HTML companions, and the top-level README.

---

## [v1.3.0] - 2026-07-30: Technical & Incident Assessment & Bi-Level Recommendations

### Technical & Incident Review Enhancements

* **`Technical & Incident Assessment` Module**
  * Added dedicated technical assessment to the case-review brief.
  * Added structured RCA classification and mitigation tracking.
* **Bi-Level `Targeted Recommendations`**
  * Manager & Escalation Actions cover SDM alignment, PEA tracking, SLA, and customer communication.
  * Technical & Diagnostic Actions cover concrete platform checks, logs, traces, and vendor routing.
* **Documentation & Technical Design Parity**
  * Updated [Manager Onboarding Markdown](MANAGER_ONBOARDING_GUIDE.md) and [HTML](MANAGER_ONBOARDING_GUIDE.html).
  * Updated [Technical Design Markdown](TECHNICAL_DESIGN_DOCUMENT.md) and [HTML](TECHNICAL_DESIGN_DOCUMENT.html).

---

## [v1.2.4] - 2026-07-27: Agent Default Context

* Added root `AGENTS.md` with runtime layout, repository conventions, validation commands, and release guidance.

---

## [v1.2.3] - 2026-07-27: Gmail SSO Playwright Robustness

* Added `page.is_closed()` guards and protected context cleanup so early browser-window closure does not crash SSO setup.

---

## [v1.2.2] - 2026-07-27: Corporate-Friendly Installer

* Added the `install.bat` wrapper.
* Scoped the Playwright Chromium TLS bypass to the download command and restored the prior environment value afterwards.

---

## [v1.2.1] - 2026-07-27: PowerShell Encoding Normalization

* Enforced CRLF plus UTF-8 BOM for `*.ps1`, `*.bat`, and `*.cmd` through `.gitattributes`.

---

## [v1.2.0] - 2026-07-26: Governance & Technical Specifications

* Added an optional Google Apps Script webhook, tracking-sheet, Google Docs brief, and scheduled digest reference module; it was not part of the active installer/runtime.
* Added the PowerPoint and interactive HTML presentation decks.
* Published [Technical Design Markdown](TECHNICAL_DESIGN_DOCUMENT.md) and [HTML](TECHNICAL_DESIGN_DOCUMENT.html).
* Centralized project documentation under `docs/`.

---

## [v1.1.0] - 2026-07-26: Embedded 10-Domain Diagnostic Engine

* Added references for AES/CTI, Contact Center, Recording/WFO, Analytics/Kubernetes, Security, SIP/Voice Quality, Certificates/Login/Outage, Digital Channels, IP Office, and Log Collection.
* Added conditional technical direction and vendor-handoff checks.
* Added the manager onboarding and installation guides.

---

## [v1.0.0] - 2026-07-26: Initial Release

* Added the case-review and Gmail capability skills.
* Added the CaseToMD MCP bridge.
* Added the Playwright Gmail MCP server with persistent SSO profile.
* Added the automated installer.
