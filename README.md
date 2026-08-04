# Avaya Case Review Suite for Support Managers

> **HTML Version Available**: Open **[README.html](README.html)** directly in your browser.

This package provides an automated **Case Review Suite** for Avaya Support & Operations Managers. It integrates **Antigravity**, **CaseToMD**, **Gmail**, and the **Embedded 10-Domain Avaya Debugger Knowledge Base** to produce executive-ready case reviews for Siebel SRs and ServiceNow INCs with evidence-grounded technical direction checks.

---

## Evidence-Grounded Review Contract

- The executive body is citation-free; all supporting material appears in the final **Appendix A - Evidence Register**.
- The report starts with one 6-8 sentence **Executive Summary** paragraph for management and technical readers. It contains conclusion-level incident, timing/location, affected scope, impact, response, RCA-state, mitigation, status, and next-checkpoint information.
- **Technical & Incident Assessment** supplies the technical reasoning: environment, findings, causal mechanism, validation, and unresolved gaps without restating the summary.
- Future prevention is excluded from Executive Summary. **Existing prevention controls** appear only in the technical assessment when supported by case evidence.
- The appendix table contains Ref, Date, Source, **Verbatim evidence / data**, and **Supports**. The Supports column reverse-maps each row to the body conclusion it validates.
- Any rendered list or table containing dates or timestamps is ordered oldest to newest; undated entries follow dated entries.
- The agent answers only what case-specific evidence supports. With zero verifiable case evidence, it outputs exactly `unknown`.
- **Case record freshness** and **Last substantive progress age** are reported separately; Closed/Resolved records are not stale solely because they are old.
- Mitigation maturity is one of Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active.
- Risk and action judgments remain with the Manager. Ownership fields only restate commitments already present in evidence.

---

## Quick Setup (1-Click)

**Recommended (works under corporate Group Policy):**
1. Unzip the pack.
2. **Double-click `install.bat`** (or from a terminal: `.\install.bat`).
3. The installer deploys the single Managed Edge broker and checks authentication. If its status exits `10`, run `python %USERPROFILE%\.gemini\tools\gmail\gmail_brokerctl.py login` and complete SSO/MFA in the opened Edge window.
4. Restart **Antigravity**.

`install.bat` is a thin wrapper that runs `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_env.ps1`, which is required because Windows PowerShell's default execution policy (`Restricted` / `AllSigned`) blocks unsigned `.ps1` files *before* any code inside the script can adjust the policy.

**Manual (if you prefer to invoke PowerShell yourself):**
```powershell
cd Path\To\avaya-case-review-pack
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_env.ps1
```

### Behind a corporate SSL-inspecting proxy?

The installer automatically works around common corporate SSL inspection (Zscaler / Netskope / Blue Coat) for:
- **pip** - via `--trusted-host pypi.org files.pythonhosted.org ...`
- **Playwright Chromium download** - via `NODE_TLS_REJECT_UNAUTHORIZED=0`, applied only to that single command and restored immediately afterwards.

If your org supplies a corporate CA bundle, prefer setting `NODE_EXTRA_CA_CERTS` to the `.pem` path *before* running `install.bat`:
```powershell
$env:NODE_EXTRA_CA_CERTS = "C:\path\to\corp-ca-bundle.pem"
.\install.bat
```
When that variable is set, the installer uses your CA bundle instead of the bypass. Chromium remains installed for the explicit one-release `legacy_playwright` rollback; normal Gmail traffic uses the Edge broker.

### Gmail broker operations

The broker owns one dedicated Edge context and serializes requests from all Gmail MCP processes. Use `status`, `diagnostics`, `start`, `login`, and `stop` from `gmail_brokerctl.py`; see [`docs/GMAIL_EDGE_BROKER.md`](docs/GMAIL_EDGE_BROKER.md). The rollback switch is explicit (`GMAIL_BACKEND=legacy_playwright`) and there is no automatic fallback.

---

## Complete Documentation Suite (`docs/`)

All project documentation, release notes, installation guides, design specifications, and presentation decks are organized in the **[`docs/`](docs/)** directory:

- **Release Notes & Version Track**:
  - **[docs/RELEASE_NOTES.html](docs/RELEASE_NOTES.html)** / **[docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md)** - v1.6.0 - latest release
- **Executive Presentation**:
  - **[docs/PRESENTATION.html](docs/PRESENTATION.html)** - Interactive Browser Slide Deck
  - **[docs/Avaya_Case_Review_Suite_Presentation.pptx](docs/Avaya_Case_Review_Suite_Presentation.pptx)** - PowerPoint Presentation Deck
- **Technical Architecture & Design**:
  - **[docs/TECHNICAL_DESIGN_DOCUMENT.html](docs/TECHNICAL_DESIGN_DOCUMENT.html)** / **[docs/TECHNICAL_DESIGN_DOCUMENT.md](docs/TECHNICAL_DESIGN_DOCUMENT.md)** - Complete Technical Design Document (TDD)
- **Manager Onboarding & Operational Usage**:
  - **[docs/MANAGER_ONBOARDING_GUIDE.html](docs/MANAGER_ONBOARDING_GUIDE.html)** / **[docs/MANAGER_ONBOARDING_GUIDE.md](docs/MANAGER_ONBOARDING_GUIDE.md)** - Support Manager Setup & Usage Guide
- **Desktop App Installation**:
  - **[docs/ANTIGRAVITY_INSTALLATION_GUIDE.html](docs/ANTIGRAVITY_INSTALLATION_GUIDE.html)** / **[docs/ANTIGRAVITY_INSTALLATION_GUIDE.md](docs/ANTIGRAVITY_INSTALLATION_GUIDE.md)** - Antigravity App Installation & Login Guide

---

## Package Structure

- **`setup_env.ps1`**: Automated environment installer script.
- **`docs/GMAIL_EDGE_BROKER.md`**: Managed Edge broker operation, authentication, diagnostics, and rollback guide.
- **`docs/`**: Centralized documentation suite (Release Notes, Guides, TDD, Presentations, PowerPoint).
- **`plugins/avaya-case-review/`**: The Case Review plugin containing the `case-review` skill, `gmail-capability` skill, and **10 embedded Avaya product domain reference guides** (`aes-cti-jtapi.md`, `contact-center.md`, `recording-wfo.md`, `analytics-kubernetes.md`, `security-vulnerability.md`, `sip-voice-quality.md`, `certificates-login-outage.md`, `digital-channels.md`, `ip-office.md`, `log-collection.md`).
- **`tools/casetomd/`**: Python bridge for the CaseToMD server (`https://192.168.67.160:8000/mcp`).
- **`tools/gmail/`**: Single Managed Edge broker, thin Gmail MCP adapter, and explicit legacy Playwright rollback backend.
- **`examples/optional-appsscript/`**: Optional, manually deployed Google Apps Script reference for Sheets/Docs/Email digest governance. It is not installed or invoked by the active runtime.
