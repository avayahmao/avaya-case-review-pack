# Release Notes — Avaya Case Review Suite

All notable changes, features, bug fixes, and architectural enhancements for the **Avaya Case Review Suite** are documented in this file.

---

## [v1.2.0] — 2026-07-26: Complete Governance & Technical Specifications Release

### 🚀 New Features & Modules
* **Google Apps Script & Workspace Governance Integration (`tools/appsscript/Code.gs`)**:
  * **HTTP Webhook (`doPost`)**: Endpoint to receive Antigravity case review JSON payloads in the cloud.
  * **Google Sheets Governance Dashboard (`updateCaseTrackingSheet`)**: Appends and updates case review records with conditional status highlighting (`🟢 Healthy`, `🟡 At Risk`, `🔴 Stalled`).
  * **Google Docs Brief Generator (`createGoogleDocReport`)**: Automatically creates structured executive case briefs in Google Drive.
  * **Scheduled Email Digest (`sendDailyManagerDigest`)**: Automated trigger function that sweeps the tracking sheet daily and emails HTML alert digests to management for all stalled or at-risk cases.
* **Executive Presentation Deck (12 Slides)**:
  * **PowerPoint Presentation (`docs/Avaya_Case_Review_Suite_Presentation.pptx`)**: High-impact executive slide deck designed for leadership reviews.
  * **Interactive HTML Slide Deck (`docs/PRESENTATION.html`)**: Web-browser slide deck accessible on any device.
* **Technical Design Document (TDD)**:
  * Published complete architectural specifications in **[`docs/TECHNICAL_DESIGN_DOCUMENT.md`](file:///e:/case/avaya-case-review-pack/docs/TECHNICAL_DESIGN_DOCUMENT.md)** and **[`docs/TECHNICAL_DESIGN_DOCUMENT.html`](file:///e:/case/avaya-case-review-pack/docs/TECHNICAL_DESIGN_DOCUMENT.html)** covering runtime discovery, MCP bridges, technical sanity auditing, and security protocols.

### 🧹 Refactoring & Repository Organization
* **Centralized Documentation (`docs/`)**: Organized all user guides, installation manuals, design docs, release notes, and presentation files into a single `docs/` folder structure for clean repository maintenance.

---

## [v1.1.0] — 2026-07-26: Embedded 10-Domain Diagnostic Engine & Manager Onboarding

### 🧠 Intelligent Diagnostic Engine
* **Embedded 10-Domain Avaya Reference Suite (`plugins/avaya-case-review/skills/case-review/references/`)**:
  1. `aes-cti-jtapi.md`: AES, TSAPI, CSTA, DMCC, park/unpark, `SA9114`/`SA9124`, `T####` ASAI trunks.
  2. `contact-center.md`: Oceana, AACC, POM, AXP, CMS, vector wait-time > 0, skill routing.
  3. `recording-wfo.md`: ACRA, Verint, WFO/WFE, RIS, WebLogic, `CSTA_CALL_CLEARED`.
  4. `analytics-kubernetes.md`: Oceanalytics, Kafka, Kubernetes pod failures, MicroStrategy, ETL.
  5. `security-vulnerability.md`: AVAPT/NVAPT, CVE vulnerabilities, SSH/TLS cipher suite hardening.
  6. `sip-voice-quality.md`: SIP signaling, SBC, one-way audio, RTP packet loss, jitter, codec negotiation.
  7. `certificates-login-outage.md`: Certificate cascade, WebLM, SMGR, login/auth failures, major outage recovery.
  8. `digital-channels.md`: Email, Social, Infinity, ESL, WeChat/WhatsApp, screen-pop routing.
  9. `ip-office.md`: IP Office (IPO), SSA, SysMonitor, SIP trunk registration, IPO Manager.
  10. `log-collection.md`: `getlogs`, `csta_trace`, `g3trace`, `spi.log`, `acr.log`, `tcpdump` log matrix.
* **Automated Technical Direction Sanity Auditor**:
  * Detects platform vs application misdirection (e.g. blaming JTAPI SDK instead of CM ASAI snapshot configuration).
  * Enforces official Javadoc API methods (`LucentV5CallInfo.getUCID()`).
  * Cross-checks log sufficiency before escalation.
* **Vendor Escalation Verification**: Validates handoffs across BBE PEA, CPE PEA, Verint Support, Nuance, and Customer MSP.

### 📖 Documentation & Guides
* **Antigravity Installation Guide (`docs/ANTIGRAVITY_INSTALLATION_GUIDE.md` / `.html`)**: Common-sense Windows Desktop App setup and Google SSO login guide.
* **Manager Onboarding Guide (`docs/MANAGER_ONBOARDING_GUIDE.md` / `.html`)**: Support Manager operational workflow, VPN prerequisites, and example prompts.

---

## [v1.0.0] — 2026-07-26: Initial Release

### 🎉 Initial Release Highlights
* **Case Review Plugin (`plugins/avaya-case-review/`)**: Initial implementation of `case-review` and `gmail-capability` skills.
* **CaseToMD MCP Bridge (`tools/casetomd/casetomd_mcp_bridge.py`)**: MCP server for fetching Siebel SRs and ServiceNow INCs over internal HTTPS endpoints (`https://192.168.67.160:8000/mcp`).
* **Playwright Gmail MCP Server (`tools/gmail/gmail_mcp_server.py`)**: Headless browser integration with local SSO profile persistence (`chrome_profile`) for deep inbox searching across `@avaya.com` email threads.
* **Automated Installer (`setup_env.ps1`)**: 1-click PowerShell deployment script.
