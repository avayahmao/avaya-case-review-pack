# Avaya Case Review Suite for Support Managers

> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[README.html](file:///e:/case/avaya-case-review-pack/README.html)** directly in your browser.

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

## 📖 Complete Documentation & Guides

- 🌐 **[MANAGER_ONBOARDING_GUIDE.html](file:///e:/case/avaya-case-review-pack/MANAGER_ONBOARDING_GUIDE.html)** / 📄 **[MANAGER_ONBOARDING_GUIDE.md](file:///e:/case/avaya-case-review-pack/MANAGER_ONBOARDING_GUIDE.md)** — Support Manager Setup & Usage Guide
- 🌐 **[ANTIGRAVITY_INSTALLATION_GUIDE.html](file:///e:/case/avaya-case-review-pack/ANTIGRAVITY_INSTALLATION_GUIDE.html)** / 📄 **[ANTIGRAVITY_INSTALLATION_GUIDE.md](file:///e:/case/avaya-case-review-pack/ANTIGRAVITY_INSTALLATION_GUIDE.md)** — Antigravity App Installation & Login Guide

---

## 🛠️ Package Contents

- **`setup_env.ps1`**: Automated environment installer script.
- **`MANAGER_ONBOARDING_GUIDE.html` / `MANAGER_ONBOARDING_GUIDE.md`**: Full setup and usage documentation for managers.
- **`plugins/avaya-case-review/`**: The Case Review plugin containing the `case-review` skill, `gmail-capability` skill, and **10 embedded Avaya product domain reference guides** (`aes-cti-jtapi.md`, `contact-center.md`, `recording-wfo.md`, `analytics-kubernetes.md`, `security-vulnerability.md`, `sip-voice-quality.md`, `certificates-login-outage.md`, `digital-channels.md`, `ip-office.md`, `log-collection.md`).
- **`tools/casetomd/`**: Python bridge for the CaseToMD server (`https://192.168.67.160:8000/mcp`).
- **`tools/gmail/`**: Playwright-based Gmail MCP server for inbox search and email reading.
