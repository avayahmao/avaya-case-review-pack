# Avaya Case Review Suite — Support Manager Setup & Onboarding Guide

> [!NOTE]
> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[MANAGER_ONBOARDING_GUIDE.html](MANAGER_ONBOARDING_GUIDE.html)** directly in any web browser.
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

The case review produces a structured, evidence-grounded executive report:

1. **Evidence Gate**: A dynamic `Evidence 1..N` section. Each item includes Source, Date, Verbatim evidence / data, and Supports. There is no three-item quota. If no verifiable case-specific evidence exists, the answer is exactly `不知道`.
2. **Top-Level Verdict**: Bottom-line assessment (`Healthy`, `At Risk`, `Stalled`, or `不知道`) with Evidence IDs.
3. **Two Freshness Clocks**:
   - **Case record freshness**: age of the official record's latest update.
   - **Last substantive progress age**: age of the latest concrete technical, mitigation, decision, or impact change.
   - Closed/Resolved records are not marked stale solely because they are old.
4. **Conditional Technical & Incident Assessment**: Exactly one of a multi-problem `Problem Statement` or a single-issue `Incident & RCA Summary`. Telemetry calculations stay inside the relevant problem.
5. **Mitigation Maturity**: Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active. Lab success is not presented as production resolution.
6. **Progress and Timeline**: Substantive milestones from CaseToMD, Gmail, supplied documents, and logs. Routine status pings are retained for stall analysis but omitted from the displayed timeline.
7. **Risk Flags and Technical Sanity Checks**: Only evidence-backed flags. Domain rules are activated only when matching case evidence exists.
8. **Ownership & Next Step**: Assignee, last concrete action, next action, next-action owner, and due date; unsupported fields are `unassigned`, `not stated`, or `不知道`.
9. **Targeted Recommendations**: The single location for all actions:
   - **Manager & Escalation Actions**
   - **Technical & Diagnostic Actions**
   - Every action includes an Owner and supporting Evidence IDs.


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
