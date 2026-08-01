# Avaya Case Review Suite for Support Managers

> 🌐 **HTML Version Available**: Open **[README.html](README.html)** directly in your browser.

This package provides an automated **Case Review Suite** for Avaya Support & Operations Managers. It integrates **Antigravity**, **CaseToMD**, **Gmail**, and the **Embedded 10-Domain Avaya Debugger Knowledge Base** to produce executive-ready case reviews for Siebel SRs and ServiceNow INCs with automated technical direction sanity checks and risk detection.

---

## Evidence-Grounded Review Contract

- Every factual review includes dynamic `Evidence 1..N` entries with Source, Date, Verbatim evidence / data, and Supports.
- The agent answers only what case-specific evidence supports. With zero verifiable case evidence, it outputs exactly `不知道`.
- **Case record freshness** and **Last substantive progress age** are reported separately; Closed/Resolved records are not stale solely because they are old.
- Mitigation maturity is one of Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active.
- All actions appear only under `Targeted Recommendations` and cite supporting Evidence IDs.

---

## 🚀 Quick Setup (1-Click)

**Recommended (works under corporate Group Policy):**
1. Unzip the pack.
2. **Double-click `install.bat`** (or from a terminal: `.\install.bat`).
3. A Chrome browser window will open to initialize Google SSO for `@avaya.com`. Complete sign-in/MFA if prompted, then close the browser window.
4. Restart **Antigravity**.

`install.bat` is a thin wrapper that runs `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_env.ps1`, which is required because Windows PowerShell's default execution policy (`Restricted` / `AllSigned`) blocks unsigned `.ps1` files *before* any code inside the script can adjust the policy.

**Manual (if you prefer to invoke PowerShell yourself):**
```powershell
cd Path\To\avaya-case-review-pack
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_env.ps1
```

### Behind a corporate SSL-inspecting proxy?

The installer automatically works around common corporate SSL inspection (Zscaler / Netskope / Blue Coat) for:
- **pip** — via `--trusted-host pypi.org files.pythonhosted.org …`
- **Playwright Chromium download** — via `NODE_TLS_REJECT_UNAUTHORIZED=0`, applied only to that single command and restored immediately afterwards.

If your org supplies a corporate CA bundle, prefer setting `NODE_EXTRA_CA_CERTS` to the `.pem` path *before* running `install.bat`:
```powershell
$env:NODE_EXTRA_CA_CERTS = "C:\path\to\corp-ca-bundle.pem"
.\install.bat
```
When that variable is set, the installer uses your CA bundle instead of the bypass.

---

## 📖 Complete Documentation Suite (`docs/`)

All project documentation, release notes, installation guides, design specifications, and presentation decks are organized in the **[`docs/`](docs/)** directory:

- 📝 **Release Notes & Version Track**:
  - 🌐 **[docs/RELEASE_NOTES.html](docs/RELEASE_NOTES.html)** / 📄 **[docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md)** — v1.4.0 - latest release
- 📊 **Executive Presentation**:
  - 🌐 **[docs/PRESENTATION.html](docs/PRESENTATION.html)** — Interactive Browser Slide Deck
  - 📄 **[docs/Avaya_Case_Review_Suite_Presentation.pptx](docs/Avaya_Case_Review_Suite_Presentation.pptx)** — PowerPoint Presentation Deck
- 📐 **Technical Architecture & Design**:
  - 🌐 **[docs/TECHNICAL_DESIGN_DOCUMENT.html](docs/TECHNICAL_DESIGN_DOCUMENT.html)** / 📄 **[docs/TECHNICAL_DESIGN_DOCUMENT.md](docs/TECHNICAL_DESIGN_DOCUMENT.md)** — Complete Technical Design Document (TDD)
- 📖 **Manager Onboarding & Operational Usage**:
  - 🌐 **[docs/MANAGER_ONBOARDING_GUIDE.html](docs/MANAGER_ONBOARDING_GUIDE.html)** / 📄 **[docs/MANAGER_ONBOARDING_GUIDE.md](docs/MANAGER_ONBOARDING_GUIDE.md)** — Support Manager Setup & Usage Guide
- 💻 **Desktop App Installation**:
  - 🌐 **[docs/ANTIGRAVITY_INSTALLATION_GUIDE.html](docs/ANTIGRAVITY_INSTALLATION_GUIDE.html)** / 📄 **[docs/ANTIGRAVITY_INSTALLATION_GUIDE.md](docs/ANTIGRAVITY_INSTALLATION_GUIDE.md)** — Antigravity App Installation & Login Guide

---

## 🛠️ Package Structure

- **`setup_env.ps1`**: Automated environment installer script.
- **`docs/`**: Centralized documentation suite (Release Notes, Guides, TDD, Presentations, PowerPoint).
- **`plugins/avaya-case-review/`**: The Case Review plugin containing the `case-review` skill, `gmail-capability` skill, and **10 embedded Avaya product domain reference guides** (`aes-cti-jtapi.md`, `contact-center.md`, `recording-wfo.md`, `analytics-kubernetes.md`, `security-vulnerability.md`, `sip-voice-quality.md`, `certificates-login-outage.md`, `digital-channels.md`, `ip-office.md`, `log-collection.md`).
- **`tools/casetomd/`**: Python bridge for the CaseToMD server (`https://192.168.67.160:8000/mcp`).
- **`tools/gmail/`**: Playwright-based Gmail MCP server for inbox search and email reading.
- **`tools/appsscript/`**: Google Apps Script module (`Code.gs`) for Google Sheets/Docs/Email digest governance.
