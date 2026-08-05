# Avaya Case Review Suite — Support Manager Setup & Onboarding Guide

> [!NOTE]
> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[MANAGER_ONBOARDING_GUIDE.html](MANAGER_ONBOARDING_GUIDE.html)** directly in any web browser.
>
> This guide is designed for **Avaya Operations & Support Managers**. It walks you through setting up **Antigravity**, the **Case Review Plugin**, and **Gmail / CaseToMD MCP Servers** to generate automated, executive-ready reviews for Siebel SRs and ServiceNow INCs.

---

## 1. Prerequisites

Before starting local setup, ensure your workstation meets the following requirements:

- **Operating System**: Windows 10 or Windows 11.
- **Python**: Python 3.10+ installed and added to system `PATH` (verify by running `python --version` in PowerShell).
- **Network / VPN**: Connected to the internal Avaya network or corporate VPN (required to reach the CaseToMD server at `https://192.168.67.160:8000/mcp`).
- **Google Account**: Logged into your `@avaya.com` Google / Gmail account.

---

## 2. Quick Start: One-Click Automated Setup

### Required Cloud Prerequisite (Before Local Installation)

Before unpacking or running the local installer, open the existing Gmail MCP Apps Script project and follow [GMAIL_CLOUD_BRIDGE.md](GMAIL_CLOUD_BRIDGE.md). Enable the **Advanced Gmail Service** named Gmail, API version v1; deploy the new Web App version at the existing URL; and verify the zero-result, real-case snapshot/page-token, and multi-message cursor checks. Cloud deployment and verification must complete before any `install.bat`, `setup_env.ps1`, or local Agent SKILL activation. If the gate is not satisfied, keep the exhaustive Agent gate inactive.

### Local Component Setup

After the cloud deployment and verification gate passes, configure the local components using the included PowerShell script (`setup_env.ps1`).

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
4. **Deploys Gmail broker modules**: Copies the broker, client, control CLI, thin MCP adapter, and explicit legacy backend into `C:\Users\<username>\.gemini\tools\gmail\`.
5. **Updates Configuration**: Configures `mcp_config.json` with `gmail` (`GMAIL_BACKEND=edge_broker`) and `CaseToMD` MCP server definitions.
6. **Checks broker authentication**: Runs broker status and requests interactive login only when status exits `10`.

---

## 3. Google SSO Authentication (One-Time Setup)

During setup, the installer checks the single Managed Edge broker. If interactive authentication is required, `gmail_brokerctl.py login` opens the dedicated Edge profile and the broker restores its headless context after the login probe.

1. **Log In**: If prompted, log into your `@avaya.com` account and complete any Duo / SSO MFA prompts.
2. **Authorize**: Accept any Google authorization prompts to allow email search/read access.
3. **Complete**: Once the broker reports an authenticated verification probe, close the Edge login window. The dedicated session is saved locally under `C:\Users\<username>\.gemini\tools\gmail\edge_broker_profile`.

The broker state and sanitized operational log are stored under
`%LOCALAPPDATA%\AvayaCaseReview\gmail-broker`. Do not copy the normal Edge
profile or delete `chrome_profile`; the latter remains the one-release rollback
profile.

---

## 4. Verifying Your Setup in Antigravity

1. **Restart Antigravity**: Close and reopen Antigravity.
2. **Check Active Skills**: Ask Antigravity:
   > *"What skills do you have for case reviews?"*
   
   Antigravity should acknowledge the **`case-review`** skill and **`gmail-capability`** skill.

3. **Check MCP Tools**: In Antigravity, verify that the following tools are active:
   - `get_case_markdown` (from `CaseToMD` server)
   - `gmail_list_threads`, `gmail_read_thread_page` (required current case-review collection tools)
   - `gmail_search`, `gmail_read`, `gmail_send` (backward-compatible Gmail APIs; not the completeness workflow)

### Current Case-Review Collection Gate

Every case review must pass **Complete Context Before Analysis**. CaseToMD is fetched first; every Case note is processed, the primary and every supported note-derived related ID are frozen, and each frozen ID is enumerated with `gmail_list_threads` through every `next_page_token`. Each unique matched thread is then read with `gmail_read_thread_page` through every `next_cursor`, including every message in every matched Gmail thread that is eligible for the shared snapshot and every body chunk. The Context Coverage Ledger must pass its note, query, thread, message, chunk, hash, manifest, and shared-snapshot equalities before analysis or report generation.

The first list call may bootstrap with an empty `snapshot_before`, but it must return a non-empty snapshot. Every later list/read call reuses that exact same snapshot. If any source or coverage step fails, the output is only `Context collection incomplete` with sanitized counts and the blocker; no Executive Summary, RCA, ownership conclusion, or Evidence Appendix is produced. `gmail_search` and `gmail_read` remain backward-compatible APIs and explicit legacy rollback surfaces, never an alternate completeness workflow.

The exhaustive endpoint runs in the existing Gmail MCP Apps Script project and requires the **Advanced Gmail Service** named Gmail, API version v1. An administrator must deploy and verify that cloud source before installing the updated local MCP modules and Agent SKILL; `setup_env.ps1` does not deploy Apps Script. See [GMAIL_CLOUD_BRIDGE.md](GMAIL_CLOUD_BRIDGE.md). This operational source is separate from the optional Sheets/Docs governance example, and attachment bodies remain outside the collection contract.

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

1. **Executive Summary**: One citation-free 6-8 sentence paragraph for management and technical readers. It provides conclusion-level information on the incident, evidenced timing/location, affected scope, impact, key response, a one-sentence RCA state or supported conclusion, mitigation maturity and production outcome, current status, and the next evidence-backed checkpoint. Unsupported required facts are `unknown`.
2. **Two Freshness Clocks**:
   - **Case record freshness**: age of the official record's latest update.
   - **Last substantive progress age**: age of the latest concrete technical, mitigation, decision, or impact change.
   - Closed/Resolved records are not marked stale solely because they are old.
3. **Conditional Technical & Incident Assessment**: Starts with problem clarification and adds technical reasoning through environment, findings, cause analysis, solution and validation, and unresolved gaps; it does not restate the complete incident or business impact. Exactly one of a multi-problem `Problem Statement` or a single-issue `Incident & RCA Summary` is used. Future prevention is excluded from Executive Summary. Existing prevention controls appear only here when evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.
4. **Mitigation Maturity**: Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active. Lab success is not presented as production resolution.
5. **Progress Summary and Timeline**: Substantive milestones from CaseToMD, Gmail, supplied documents, and logs. Routine status pings are retained for stall analysis but omitted from display. All dated or timestamped entries are ordered oldest to newest; undated entries follow dated entries.
6. **Ownership & Next Step**: Assignee, last concrete action, stated next action, next-action owner, and due date. This section only restates evidence-backed commitments and does not generate advice.
7. **Appendix A — Evidence Register**: The final report section. Its table contains Ref, Date, Source, **Verbatim evidence / data**, and **Supports**; Supports reverse-maps each row to the exact body conclusion.

The main body contains no Evidence IDs. Risk and action judgments remain with the Manager. If no verifiable case-specific evidence exists, the answer is exactly `unknown`.


---

## 6. Troubleshooting & FAQs

### Q1: Antigravity says `get_case_markdown` is not available or CaseToMD connection failed.
- **Cause**: You may not be connected to the corporate VPN, or the CaseToMD server at `192.168.67.160` is unreachable.
- **Fix**: Verify your VPN connection by testing `https://192.168.67.160:8000/mcp` in your web browser. If a self-signed certificate warning appears, click "Proceed / Continue to site".

### Q2: Gmail search returns an authentication or broker error.
- **Cause**: The dedicated Edge session may require SSO/MFA, or the broker may not be running.
- **Fix**: Run the sanitized control commands:
  ```powershell
  python C:\Users\<username>\.gemini\tools\gmail\gmail_brokerctl.py status
  python C:\Users\<username>\.gemini\tools\gmail\gmail_brokerctl.py login
  python C:\Users\<username>\.gemini\tools\gmail\gmail_brokerctl.py diagnostics
  ```
  Exit code `10` means authentication is required; `20` means broker/browser unavailable. The MCP client lazy-starts one broker and never falls back automatically.

### Q3: Is technical domain knowledge from the Avaya Debugger used in case reviews?
- **Yes!** Rather than requiring managers to run complex technical trace debugging tools manually, the core diagnostic knowledge from the Avaya Debugger (e.g. trunk CLI loss rules, SA9114/SA9124 requirements, ACRA call boundary bugs, vendor escalation paths) is built directly into the `case-review` skill. Antigravity automatically uses this knowledge during case reviews to verify if the engineers' technical directions are valid or misdirected.

---

## Summary of Files & Paths

| Item | Deployed Path | Description |
|---|---|---|
| **Plugin Folder** | `C:\Users\<username>\.gemini\config\plugins\avaya-case-review` | Case review plugin definition & skills |
| **Gmail MCP / broker** | `C:\Users\<username>\.gemini\tools\gmail\gmail_mcp_server.py` and `gmail_edge_broker.py` | Thin MCP adapter and single Managed Edge owner |
| **Edge broker session** | `C:\Users\<username>\.gemini\tools\gmail\edge_broker_profile` | Dedicated persistent SSO context |
| **Legacy rollback session** | `C:\Users\<username>\.gemini\tools\gmail\chrome_profile` | Explicit `legacy_playwright` fallback only |
| **Broker state** | `%LOCALAPPDATA%\AvayaCaseReview\gmail-broker` | State, lock, and sanitized rotating log |
| **MCP Config File** | `C:\Users\<username>\.gemini\config\mcp_config.json` | JSON configuration for Gmail and CaseToMD MCP servers |
