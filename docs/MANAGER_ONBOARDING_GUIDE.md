# Avaya Case Review Suite — Support Manager Setup & Onboarding Guide

> [!NOTE]
> 🌐 **HTML Version Available**: If you do not have a Markdown reader, open **[MANAGER_ONBOARDING_GUIDE.html](MANAGER_ONBOARDING_GUIDE.html)** directly in any web browser.
>
> This guide is designed for **Avaya Operations & Support Managers**. It walks you through setting up the **Case Review Plugin** and **Gmail / CaseToMD MCP Servers** in Antigravity; Codex users follow the parallel installation path in [`../INSTALL.md`](../INSTALL.md).

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

Before unpacking or running the local installer, open the existing Gmail MCP Apps Script project and follow [GMAIL_CLOUD_BRIDGE.md](GMAIL_CLOUD_BRIDGE.md). Enable the **Advanced Gmail Service** named Gmail, API version v1; deploy the new Web App version at the existing URL; and verify the zero-result, real-case snapshot/page-token, and multi-message cursor checks. Cloud deployment and verification must complete before any `install-codex.ps1`, `install.bat`, `setup_env.ps1`, or local Agent SKILL activation. If the gate is not satisfied, keep the exhaustive Agent gate inactive.

### Codex Setup

For Codex, follow [`../INSTALL.md`](../INSTALL.md) or run the checked-out installer after the cloud gate passes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-codex.ps1 -CloudBridgeVerified
```

Start a new Codex task after the installer reports success. The Antigravity-specific steps below are not required for a Codex-only installation.

### Antigravity Local Component Setup

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
2. **Installs Playwright Chromium**: Downloads Chromium only for the explicit `legacy_playwright` rollback path; default Gmail operation uses the single Managed Edge broker.
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

Every case review must pass **Complete Context Before Analysis**. CaseToMD is fetched first; every Case note is processed, supported related IDs are retained as Case context, and only the primary raw Case ID is enumerated with `gmail_list_threads` through every `next_page_token`. Each unique matched thread is then read with `gmail_read_thread_page` through every `next_cursor`, including every message in every primary-ID-matched Gmail thread that is eligible for the shared snapshot and every body chunk. The Context Coverage Ledger requires exactly one completed record-ID query and must pass its note, thread, message, chunk, hash, manifest, and shared-snapshot equalities before analysis or report generation.

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

- **Continue a Follow-up**:
  > *"Review SR 1-23659220672 again and show what changed."*

- **Learn from a Closed Case**:
  > *"Learn from closed SR 1-23659220672."*

### What the Generated Case Review Contains

Every successful review first creates a **structured ReviewSnapshot v2** from the complete evidence corpus. It preserves the whole-case storyline and problem lineage from the primary problem through blockers, corrections, outcome, and secondary problems, plus the fixed proof-state Technical Specification, milestones, timeline, Evidence Register, and evidence-only visual context before any chat presentation is rendered.

The deterministic router then selects one mode:

1. **standard**: Default investigation-complete first or unchanged review. It includes the Case Card, Investigation Progress flow, Causal Assessment, six key Technical Specification fields, substantive Timeline, complete dynamic Evidence Register, and an optional secondary diagnostic visual.
2. **compact**: Explicit compact request only. It returns the Case Card without replaying the complete investigation.
3. **follow-up**: Automatic when a prior successful review exists and material state, ownership, or evidence changed. Computed changes appear first, followed by the same investigation-complete core as standard.
4. **technical**: A fixed **Technical Specification** table using Field / Proof state / Value / Evidence basis. `NOT OBSERVED`, `NOT COLLECTED`, `UNKNOWN`, and `NOT APPLICABLE` remain distinct.
5. **flow**: An investigation visual requested by the user. Chronology arrows do not claim causality and Mermaid flows are limited to seven nodes.
6. **full**: Explicit on-demand structured report. This is the only mode that renders the complete Timeline and **Appendix A — Evidence Register**, with the Evidence Register last.

The Investigation Progress flow is always present in standard/follow-up and uses chronology arrows, never causal arrows. The router may add one secondary evidence-backed event comparison, claim-evidence matrix, component swimlane, or ownership checkpoint. It never invents a causal edge or component handoff, and a Claim-Evidence Matrix always retains all four columns.

The presenter writes canonical `chat-output.md` plus `chat-output.sha256`. The final-output verifier must pass before the rendered Markdown is returned unchanged; a mismatch blocks completion.

All dated milestones, timeline rows, and evidence rows are ordered oldest to newest; undated entries follow dated entries.

Mitigation maturity remains Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active. Risk and action judgments remain with the Manager. With no verifiable case-specific evidence, the answer is exactly `unknown` and the record is unchanged.

### Durable Follow-up Record

Every successful review creates or updates one persistent record for the normalized primary Case ID under `%LOCALAPPDATA%\AvayaCaseReview\case-records\<CASE-ID>\`. The record contains ReviewSnapshot v2, the current Case Card, computed delta, append-only compact history, and decisive evidence digest. Detailed technical, visual, and full views are generated on demand from the stored structured snapshot.

A repeated review always recollects CaseToMD and Gmail under a fresh complete snapshot. The prior record is not evidence and cannot satisfy the collection gate. If collection fails, the stored record is not changed.

Official Closed, Resolved, or Completed status marks administrative closure only. It does not prove validated RCA or confirmed production recovery. A closed record shows `Learning option: available`. Asking to learn creates a sanitized, evidence-strength-labeled candidate; the candidate is applied to the persistent local domain overlay only after explicit approval. Future matching reviews may use that overlay as diagnostic guidance, never as case proof. If the case later reopens, its applied learning entry is suspended until a new closure and approval.


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
| **Case follow-up records** | `%LOCALAPPDATA%\AvayaCaseReview\case-records` | Per-Case-ID ReviewSnapshot v2, current card, deltas, and compact history |
| **Approved local knowledge** | `%LOCALAPPDATA%\AvayaCaseReview\domain-knowledge` | User-approved sanitized learning overlays loaded after packaged references |
| **MCP Config File** | `C:\Users\<username>\.gemini\config\mcp_config.json` | JSON configuration for Gmail and CaseToMD MCP servers |
