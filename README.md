# Avaya Case Review Suite for Support Managers

> 🌐 **HTML Version Available**: Open **[README.html](file:///e:/case/avaya-case-review-pack/README.html)** directly in your browser.

This package provides an automated **Case Review Suite** for Avaya Support & Operations Managers. It integrates **Antigravity**, **CaseToMD**, **Gmail**, and the **Embedded 10-Domain Avaya Debugger Knowledge Base** to produce executive-ready case reviews for Siebel SRs and ServiceNow INCs with automated technical direction sanity checks and risk detection.

---

## 🚀 Quick Setup (1-Click)

1. Open **PowerShell**.
2. Navigate to this directory:
   ```powershell
   cd Path\To\avaya-case-review-pack
   ```
3. Run the setup script:
   ```powershell
   .\setup_env.ps1
   ```
4. A Chrome browser window will open to initialize Google SSO for `@avaya.com`. Complete sign-in/MFA if prompted, then close the browser window.
5. Restart **Antigravity**.

---

## 📖 Complete Documentation Suite (`docs/`)

All project documentation, installation guides, design specifications, and presentation decks are organized in the **[`docs/`](file:///e:/case/avaya-case-review-pack/docs)** directory:

- 📊 **Executive Presentation**:
  - 🌐 **[docs/PRESENTATION.html](file:///e:/case/avaya-case-review-pack/docs/PRESENTATION.html)** — Interactive Browser Slide Deck
  - 📄 **[docs/Avaya_Case_Review_Suite_Presentation.pptx](file:///e:/case/avaya-case-review-pack/docs/Avaya_Case_Review_Suite_Presentation.pptx)** — PowerPoint Presentation Deck
- 📐 **Technical Architecture & Design**:
  - 🌐 **[docs/TECHNICAL_DESIGN_DOCUMENT.html](file:///e:/case/avaya-case-review-pack/docs/TECHNICAL_DESIGN_DOCUMENT.html)** / 📄 **[docs/TECHNICAL_DESIGN_DOCUMENT.md](file:///e:/case/avaya-case-review-pack/docs/TECHNICAL_DESIGN_DOCUMENT.md)** — Complete Technical Design Document (TDD)
- 📖 **Manager Onboarding & Operational Usage**:
  - 🌐 **[docs/MANAGER_ONBOARDING_GUIDE.html](file:///e:/case/avaya-case-review-pack/docs/MANAGER_ONBOARDING_GUIDE.html)** / 📄 **[docs/MANAGER_ONBOARDING_GUIDE.md](file:///e:/case/avaya-case-review-pack/docs/MANAGER_ONBOARDING_GUIDE.md)** — Support Manager Setup & Usage Guide
- 💻 **Desktop App Installation**:
  - 🌐 **[docs/ANTIGRAVITY_INSTALLATION_GUIDE.html](file:///e:/case/avaya-case-review-pack/docs/ANTIGRAVITY_INSTALLATION_GUIDE.html)** / 📄 **[docs/ANTIGRAVITY_INSTALLATION_GUIDE.md](file:///e:/case/avaya-case-review-pack/docs/ANTIGRAVITY_INSTALLATION_GUIDE.md)** — Antigravity App Installation & Login Guide

---

## 🛠️ Package Structure

- **`setup_env.ps1`**: Automated environment installer script.
- **`docs/`**: Centralized documentation suite (Guides, TDD, Presentations, PowerPoint).
- **`plugins/avaya-case-review/`**: The Case Review plugin containing the `case-review` skill, `gmail-capability` skill, and **10 embedded Avaya product domain reference guides** (`aes-cti-jtapi.md`, `contact-center.md`, `recording-wfo.md`, `analytics-kubernetes.md`, `security-vulnerability.md`, `sip-voice-quality.md`, `certificates-login-outage.md`, `digital-channels.md`, `ip-office.md`, `log-collection.md`).
- **`tools/casetomd/`**: Python bridge for the CaseToMD server (`https://192.168.67.160:8000/mcp`).
- **`tools/gmail/`**: Playwright-based Gmail MCP server for inbox search and email reading.
- **`tools/appsscript/`**: Google Apps Script module (`Code.gs`) for Google Sheets/Docs/Email digest governance.
