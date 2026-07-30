# Avaya Case Review Suite — Support Manager Setup & Onboarding Guide

> [!NOTE]
> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[MANAGER_ONBOARDING_GUIDE.html](file:///e:/case/avaya-case-review-pack/MANAGER_ONBOARDING_GUIDE.html)** directly in any web browser.
>
> This guide is designed for **Avaya Operations & Support Managers**. It walks you through setting up **Antigravity**, the **Case Review Plugin**, and **Gmail / CaseToMD MCP Servers** to generate automated, executive-ready reviews for Siebel SRs and ServiceNow INCs.

---

## 1. Prerequisites

Before running the setup script, ensure your workstation meets the following requirements:

- **Operating System**: Windows 10 or Windows 11.
- **Python**: Python 3.10+ installed and added to system `PATH` (verify by running `python --version` in PowerShell).
- **Network / VPN**: Connected to the internal Avaya network or corporate VPN (required to reach the CaseToMD server at `https://192.168.67.160:8000/mcp`).
- **Google Account**: Logged into your `@avaya.com` Google / Gmail account.

---

## 2. Quick Start: One-Click Automated Setup

The easiest way to configure your system is using the included PowerShell script (`setup_env.ps1`).

### Step-by-Step Execution

1. Open **PowerShell** on your workstation.
2. Navigate to the extracted `avaya-case-review-pack` directory:
   ```powershell
   cd Path\To\avaya-case-review-pack
   ```
3. Run the installer script:
   ```powershell
   .\setup_env.ps1
   ```

> [!TIP]
> If PowerShell displays a script execution policy restriction, run:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> .\setup_env.ps1
> ```

### What the Automated Script Does

1. **Installs Python Libraries**: Installs `mcp` and `playwright`.
2. **Installs Playwright Chromium**: Downloads the headless browser engine required for Gmail automation.
3. **Deploys Plugins**: Copies `plugins/avaya-case-review` to `C:\Users\<username>\.gemini\config\plugins\avaya-case-review`.
4. **Deploys Gmail MCP Script**: Copies `tools/gmail/gmail_mcp_server.py` to `C:\Users\<username>\.gemini\tools\gmail\`.
5. **Updates Configuration**: Configures `mcp_config.json` with `gmail` and `CaseToMD` MCP server definitions.
6. **Initializes Google SSO**: Launches a Chrome window to authenticate your Avaya Google account for Gmail searching and reading.

---

## 3. Google SSO Authentication (One-Time Setup)

During the execution of `setup_env.ps1`, a Chrome browser window will automatically launch and open the Avaya Google Apps Script endpoint.

1. **Log In**: If prompted, log into your `@avaya.com` account and complete any Duo / SSO MFA prompts.
2. **Authorize**: Accept any Google authorization prompts to allow email search/read access.
3. **Complete**: Once you see the Google Apps Script JSON response or Gmail interface, simply **close the Chrome window**. The login session token is saved locally under `C:\Users\<username>\.gemini\tools\gmail\chrome_profile`.

---

## 4. Verifying Your Setup in Antigravity

1. **Restart Antigravity**: Close and reopen Antigravity.
2. **Check Active Skills**: Ask Antigravity:
   > *"What skills do you have for case reviews?"*
   
   Antigravity should acknowledge the **`case-review`** skill and **`gmail-capability`** skill.

3. **Check MCP Tools**: In Antigravity, verify that the following tools are active:
   - `get_case_markdown` (from `CaseToMD` server)
   - `gmail_search`, `gmail_read`, `gmail_send` (from `gmail` server)

---

## 5. Using the Case Review Capability

To request a case review for any Siebel SR or ServiceNow INC, simply ask Antigravity in plain natural language.

### Example Prompts

- **Siebel SR Review**:
  > *"Please generate a case review for SR 1-23659220672"*

- **ServiceNow INC Review**:
  > *"Give me an operations review for ticket INC7429951"*

- **Focusing on Specific Risks & Technical Directions**:
  > *"Review SR 1-2401829311 and check if the technical investigation is on track or misdirected."*

### What the Generated Case Review Contains

The case review will automatically produce a structured executive report:

1. **Top-Level Verdict**: Bottom-line assessment (`🟢 Healthy`, `🟡 At Risk`, or `🔴 Stalled`).
2. **Technical & Incident Assessment**:
   - **Incidents & Technical Progress Summary**: Core fault mechanism, affected Avaya components, and diagnostic progress trajectory.
   - **Root Cause Analysis (RCA)**: Identified / Suspected / `🔍 Under Investigation (Pending: [specific logs/traces/checks])`.
   - **Mitigation Steps**: Active Workaround / `⚠️ None Active / Workaround Pending (Impact: [statement])`.
3. **Progress Summary**: Recent milestone updates from Siebel/ServiceNow and related Gmail threads.
4. **Full Timeline Table**: Consolidated chronicle of activity logs, SDM updates, and email threads.
5. **Risk Flags**: Explicit callouts for staleness (>7/30 days), PEA escalations, unassignable dispatch alerts, missing next steps, **`⚠️ TECHNICAL DIRECTION RISK`**, or **`🔴 MISDIRECTED ESCALATION`**.
6. **Technical Direction Sanity Validation**: Embedded Avaya platform intelligence that automatically cross-checks engineer workarounds against known platform behaviors (e.g. SA9114/SA9124 attributes vs JTAPI PEA requests, ACRA recording boundaries, vendor escalation target accuracy).
7. **Ownership & Next Actions**: Named assignee, last concrete action, next step owner, and due date.
8. **Targeted Recommendations**: Bi-level actionable directives with assigned Owners & Priorities:
   - **1. Manager & Escalation Actions**: SDM alignment, PEA acceleration, SLA/customer communication.
   - **2. Technical & Diagnostic Actions**: Platform parameter checks (e.g. SA9114/SA9124), log/trace requests, vendor routing fixes.


---

## 6. Troubleshooting & FAQs

### Q1: Antigravity says `get_case_markdown` is not available or CaseToMD connection failed.
- **Cause**: You may not be connected to the corporate VPN, or the CaseToMD server at `192.168.67.160` is unreachable.
- **Fix**: Verify your VPN connection by testing `https://192.168.67.160:8000/mcp` in your web browser. If a self-signed certificate warning appears, click "Proceed / Continue to site".

### Q2: Gmail search returns authentication errors or blank results.
- **Cause**: The stored Google SSO session expired or was not completed during setup.
- **Fix**: Re-run the SSO initialization script:
  ```powershell
  python C:\Users\<username>\.gemini\tools\gmail\gmail_mcp_server.py
  ```
  Or re-run `.\setup_env.ps1`.

### Q3: Is technical domain knowledge from the Avaya Debugger used in case reviews?
- **Yes!** Rather than requiring managers to run complex technical trace debugging tools manually, the core diagnostic knowledge from the Avaya Debugger (e.g. trunk CLI loss rules, SA9114/SA9124 requirements, ACRA call boundary bugs, vendor escalation paths) is built directly into the `case-review` skill. Antigravity automatically uses this knowledge during case reviews to verify if the engineers' technical directions are valid or misdirected.

---

## Summary of Files & Paths

| Item | Deployed Path | Description |
|---|---|---|
| **Plugin Folder** | `C:\Users\<username>\.gemini\config\plugins\avaya-case-review` | Case review plugin definition & skills |
| **Gmail MCP Script** | `C:\Users\<username>\.gemini\tools\gmail\gmail_mcp_server.py` | Playwright Gmail MCP server |
| **Chrome Session** | `C:\Users\<username>\.gemini\tools\gmail\chrome_profile` | Persistent Google SSO session profile |
| **MCP Config File** | `C:\Users\<username>\.gemini\config\mcp_config.json` | JSON configuration for Gmail and CaseToMD MCP servers |
