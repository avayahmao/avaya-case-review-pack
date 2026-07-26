# Avaya Case Review Suite for Support Managers

> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[README.html](file:///e:/case/avaya-case-review-pack/README.html)** directly in your browser.

This package provides an automated **Case Review Suite** for Avaya Support & Operations Managers. It integrates **Antigravity**, **CaseToMD**, **Gmail**, and embedded **Avaya Tier 4 domain rules** to produce executive-ready case reviews for Siebel SRs and ServiceNow INCs.

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
- **`plugins/avaya-case-review/`**: The Case Review plugin containing the `case-review` and `gmail-capability` skills.
- **`tools/casetomd/`**: Python bridge for the CaseToMD server (`https://192.168.67.160:8000/mcp`).
- **`tools/gmail/`**: Playwright-based Gmail MCP server for inbox search and email reading.

