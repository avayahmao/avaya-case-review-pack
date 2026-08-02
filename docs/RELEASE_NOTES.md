# Release Notes - Avaya Case Review Suite

All notable changes, features, bug fixes, and architectural enhancements for the **Avaya Case Review Suite** are documented here.

---

## [Unreleased]

### Executive Report Readability Redesign

* Moves all rendered evidence into a final reverse-mapped `Appendix A — Evidence Register`.
* Removes inline Evidence annotations from the executive body.
* Removes generated risk lists and recommended actions so Managers retain judgment ownership.
* Keeps the internal evidence gate, source-conflict handling, and production-confirmation safeguards unchanged.

---

## [v1.4.0] - 2026-08-02: Evidence-Grounded Workflow Hardening

### Evidence-Grounded Workflow Hardening

* **Dynamic Evidence Gate**
  * Adds `Evidence 1..N` entries with Source, Date, Verbatim evidence / data, and Supports.
  * Answers only evidence-supported questions; when no verifiable case-specific evidence exists, outputs exactly `不知道`.
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

* Added Google Apps Script webhook, tracking-sheet, Google Docs brief, and scheduled digest modules.
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
