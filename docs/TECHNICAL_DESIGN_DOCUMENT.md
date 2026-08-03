# Technical Design Document (TDD): Avaya Case Review Suite & Intelligent Diagnostic Engine

---

## 1. Executive Summary & System Objectives

The **Avaya Case Review Suite** is an enterprise-grade AI governance system designed for Avaya Support Managers, Operations Leads, Service Delivery Managers (SDMs), and Technical Escalation Managers. 

The system automates the synthesis of raw ticket data (Siebel SRs and ServiceNow INCs) and off-system email communications (Google Workspace / Gmail), while executing **automated technical direction auditing** using an embedded 10-Domain Avaya UC/CC expert knowledge base.

### Key Capabilities
1. **1-Click Executive Case Brief Generation**: Transforms hundreds of pages of raw database dumps into clean, executive-ready markdown reports.
2. **Unified Off-System Email Synthesis**: Integrates headless Playwright browser automation with Google Workspace to extract SDM threads, customer commitments, and auto-router (OCD) "UNASSIGNABLE" dispatch alerts.
3. **Automated Sanity Auditing**: Detects engineer misdirection (e.g. blaming application SDKs for platform configuration issues), verifies system attribute dependencies (such as CM `SA9114`/`SA9124`), enforces official Javadoc API methods (`LucentV5CallInfo.getUCID()`), and flags misdirected vendor escalations (BBE vs CPE vs Verint vs Nuance).
4. **Google Apps Script & Sheet Governance Integration**: Webhook endpoint and scheduled trigger engine (`Code.gs`) that synchronizes case review verdicts into Google Sheets, generates Google Docs briefs, and fires email alerts to managers for stalled cases.

---

## 2. End-to-End System Architecture

The architecture consists of five primary decoupled layers:

```
+-----------------------------------------------------------------------------------+
| 1. CLIENT INTERFACE LAYER                                                          |
|    Antigravity Windows Desktop App (Agent Runtime & Markdown Renderer)             |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 2. MCP BRIDGE & AGENT TOOL SUBSYSTEMS                                              |
|  +-------------------------------------+   +------------------------------------+ |
|  | CaseToMD MCP Bridge                 |   | Gmail MCP Clients + Edge Broker    | |
|  | (casetomd_mcp_bridge.py)          |   | (thin adapter -> one broker)       | |
|  +-------------------------------------+   +------------------------------------+ |
+-----------------------------------------------------------------------------------+
                   |                                           |
                   v                                           v
+--------------------------------------+    +---------------------------------------+
| 3. ENTERPRISE DATA SOURCES           |    | 4. GOOGLE WORKSPACE & APPS SCRIPT     |
|  * Siebel SR Database / ServiceNow   |    |  * @avaya.com Gmail Inbox             |
|  * HTTPS Endpoint:                   |    |  * Google Apps Script (Code.gs)       |
|    https://192.168.67.160:8000/mcp   |    |  * Google Sheet Governance Dashboard  |
+--------------------------------------+    +---------------------------------------+
                   |                                           |
                   +---------------------+---------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 5. INTELLIGENCE ENGINE & 10-DOMAIN KNOWLEDGE BASE                                 |
|  * SKILL: plugins/avaya-case-review/skills/case-review/SKILL.md                    |
|  * 10 Domain Reference Files: aes-cti-jtapi.md, contact-center.md, etc.          |
+-----------------------------------------------------------------------------------+
```

---

## 3. Subsystem Specifications

### 3.1 Client Layer: Antigravity Desktop App Runtime
- **Target OS**: Windows 10 / 11 64-bit
- **Discovery**: Automatically scans `%USERPROFILE%\.gemini\config\plugins` for active skills and MCP configurations.
- **Execution Mode**: Non-sandboxed subagent execution with structured JSON tool invocations and live streaming Markdown report output.

---

### 3.2 MCP Server Bridges

#### Subsystem A: CaseToMD MCP Bridge (`tools/casetomd/casetomd_mcp_bridge.py`)
- **Protocol**: Model Context Protocol (MCP) JSON-RPC over STDIO.
- **Backend Endpoint**: `https://192.168.67.160:8000/mcp` (Handles TLS self-signed certificates with `urllib3` SSL context suppression).
- **Tools Exposed**:
  ```json
  {
    "name": "get_case_markdown",
    "description": "Fetch raw case details from Siebel SR or ServiceNow INC and convert to structured Markdown.",
    "parameters": {
      "type": "object",
      "properties": {
        "report_id": {
          "type": "string",
          "description": "Case ID e.g. 1-23659220672, INC7386572, CHG..., CTASK..."
        }
      },
      "required": ["report_id"]
    }
  }
  ```
- **Error Handling**: Implements exponential backoff, HTTP status code translation, and fallback error payloads.

#### Subsystem B: Gmail MCP and Single Managed Edge Broker
- **Protocol**: Each MCP server remains MCP STDIO, while clients send authenticated NDJSON requests over loopback to one `gmail_edge_broker.py` process.
- **Ownership**: The broker is the only process allowed to open `%USERPROFILE%\.gemini\tools\gmail\edge_broker_profile`; all browser operations are serialized.
- **Authentication Persistence**: The broker-owned Edge context retains the Avaya SSO/MFA session across MCP and broker restarts. `gmail_brokerctl.py login` temporarily switches to headful Edge and always restores headless mode.
- **Tools Exposed**: `gmail_search(query)`, `gmail_read(message_id)`, and `gmail_send(to, subject, body)` retain their existing schemas and response text.
- **Operations**: `status`, `diagnostics`, `start`, `login`, and `stop` expose only sanitized state. The default is `GMAIL_BACKEND=edge_broker`; `GMAIL_BACKEND=legacy_playwright` is an explicit one-release rollback with no automatic fallback.
- **Security**: State and lifetime lock files live under `%LOCALAPPDATA%\AvayaCaseReview\gmail-broker`; logs never contain queries, message content, recipients, cookies, or tokens.

---

### 3.3 Intelligence Engine & 10-Domain Knowledge Base

The core brain of the review system is defined in `plugins/avaya-case-review/skills/case-review/SKILL.md`.

#### Progressive Knowledge Base Loading
Upon receiving a case ID, the engine analyzes ticket keywords and conditionally loads domain-specific reference files from `plugins/avaya-case-review/skills/case-review/references/`:

| Domain Reference | Target System & Trigger Keywords |
| :--- | :--- |
| `aes-cti-jtapi.md` | AES, TSAPI, JTAPI, CSTA, DMCC, park/unpark, `SA9114`, `SA9124`, `T####`, `connBelongsToCall` |
| `contact-center.md` | Oceana, AACC, POM, AXP, CMS, skill routing, vector wait-time > 0, EACC |
| `recording-wfo.md` | ACRA, Verint, WFO/WFE, RIS, WebLogic, `CSTA_CALL_CLEARED`, DMSA |
| `analytics-kubernetes.md`| Oceanalytics, Kafka, Kubernetes pod failures, MicroStrategy, ETL pipeline |
| `security-vulnerability.md`| AVAPT/NVAPT, CVE vulnerabilities, SSH/TLS cipher suite hardening, SSL handshakes |
| `sip-voice-quality.md` | SIP signaling, SBC, one-way audio, RTP packet loss, jitter, codec negotiation |
| `certificates-login-outage.md`| Certificate cascade, WebLM, SMGR, login/auth failures, major outage recovery |
| `digital-channels.md` | Email, Social, Infinity, ESL, WeChat/WhatsApp, screen-pop routing |
| `ip-office.md` | IP Office (IPO), SSA, SysMonitor, SIP trunk registration, IPO Manager |
| `log-collection.md` | `getlogs`, `csta_trace`, `g3trace`, `spi.log`, `acr.log`, `tcpdump` log matrix |

#### Technical Sanity & Risk Audit Rules
1. **Platform vs Application Misdirection**: Flags cases where engineers request application code changes (e.g. JTAPI SDK PEA) when the underlying cause is Communication Manager (CM) configuration (e.g. missing ASAI snapshot on 2nd unpark trunk).
2. **System Attribute Verification**: Checks whether CM system-features `SA9114` and `SA9124` are required for trunk CLI retention across call park/unpark.
3. **API Method Compliance**: Verifies that engineers use official Javadoc methods (`LucentV5CallInfo.getUCID()`) rather than deprecated or zeroed fields (`originalCallInfo.ucid`).
4. **Log Sufficiency**: Cross-checks case logs against `log-collection.md` to ensure `getlogs`, `csta_trace`, and `g3trace` were requested before escalating.

#### Output Brief Schema
1. **Executive Verdict & Overall Health**: Citation-free Healthy, At Risk, Stalled, or `不知道`.
2. **Freshness Model**:
   - **Case record freshness** measures the age of the official record update.
   - **Last substantive progress age** measures the age of the latest concrete technical or operational change.
   - Closed/Resolved records are excluded from age-only staleness flags.
3. **Conditional Technical Assessment**: Exactly one multi-problem `Problem Statement` or single-issue `Incident & RCA Summary`. Telemetry remains inline with its sourced problem.
4. **Mitigation Maturity**: Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active.
5. **Unified Progress and Timeline**: Status pings remain available for stall analysis but are omitted from display when non-substantive.
6. **Ownership & Next Step**: Assignee, last concrete action, stated next action, owner, and due date. It only restates evidence-backed commitments.
7. **Appendix A — Evidence Register**: The final section, using `Ref | Date | Source | Verbatim evidence / data | Supports`.

#### Evidence Processing Contract
1. **Evidentiary authority** is evaluated independently from management display priority.
2. Direct logs and official record facts outrank summaries for factual conclusions.
3. Source conflicts remain visible and disputed conclusions remain `不知道` until resolved.
4. Evidence entries are never split, duplicated, or invented to reach a target count.
5. A reference guide may explain case evidence but cannot replace it.
6. The body contains no Evidence IDs; `Supports` reverse-maps each appendix row to exact body conclusions.
7. The agent does not generate risk lists, scores, directives, or recommended actions.

#### Vendor Escalation Handoff Matrix
- **CM / AES Core Software Bugs** ➔ Assign to **[BBE PEA]** (CM ASAI, AES service crash, crossID exhaustion).
- **POM / AEP Product Code** ➔ Assign to **[CPE PEA]** (POM campaign engine, AEP application server, REST driver).
- **Verint / WFO / RIS / WebLogic** ➔ Assign to **[Verint Support Ticket]** (ACRA recording failure, RIS connection, DMSA).
- **Nuance MRCP / ASR / TTS** ➔ Assign to **[Nuance Support Ticket]** (Speech recognition grammar errors, MRCP v2 timeout).
- **Customer Infrastructure** ➔ Assign to **[Customer / MSP Action]** (LDAP auth, SQL database, firewall ports).

*The handoff matrix informs the technical assessment only; the Manager retains risk judgment.*


---

### 3.4 Google Apps Script & Workspace Subsystem (`tools/appsscript/Code.gs`)

Google Apps Script provides the cloud governance layer for tracking cases across Google Sheets, generating Google Docs briefs, and firing automated daily email digests.

#### Key Functions in `Code.gs`

```javascript
/**
 * 1. doPost(e): HTTP Webhook Endpoint
 * Receives JSON payload from Antigravity/Case Review Agent.
 */
function doPost(e) { ... }

/**
 * 2. updateCaseTrackingSheet(caseData): Google Sheet Governance Dashboard
 * Appends or updates case row in 'Case Tracker' sheet with conditional status formatting.
 */
function updateCaseTrackingSheet(caseData) { ... }

/**
 * 3. createGoogleDocReport(caseData): Google Doc Brief Generator
 * Creates a formatted Google Doc brief with the Executive Verdict and Evidence Appendix.
 */
function createGoogleDocReport(caseData) { ... }

/**
 * 4. sendDailyManagerDigest(): Scheduled Manager Email Digest
 * Evaluates 'Case Tracker' sheet daily for Stalled (>7/30 days) and At Risk cases, sending HTML email alerts via MailApp.
 */
function sendDailyManagerDigest() { ... }
```

#### JSON Payload Contract for `doPost` Webhook
```json
{
  "case_id": "1-23659220672",
  "title": "AES JTAPI null address on unpark",
  "health_status": "Stalled",
  "owner": "John Doe",
  "next_owner": "Jane Smith (Tier 3)",
  "summary": "Case stalled for 14 days waiting for unassigned PEA review.",
  "evidence": [
    {
      "ref": "E1",
      "date": "2026-08-01",
      "source": "Case activity",
      "verbatim": "PEA review remains pending with no ETA.",
      "supports": "Verdict — Stalled; Ownership — Next owner"
    }
  ]
}
```

---

## 4. Security, Authentication & Data Protection

1. **Credential Isolation**: Zero hardcoded passwords or API keys in repository files.
2. **SSO Session Token Isolation**: The broker-owned Edge SSO context is isolated in `%USERPROFILE%\.gemini\tools\gmail\edge_broker_profile`; state and lock files are ACL-protected under `%LOCALAPPDATA%\AvayaCaseReview\gmail-broker`.
3. **Single Browser Owner**: MCP processes never launch Edge in broker mode. A lifetime owner lock and loopback token prevent a second broker from opening the profile.
4. **Transport Security**: Internal TLS endpoints (CaseToMD server) use HTTPS with explicit SSL context handling; broker traffic is loopback-only and token-authenticated.
5. **Data Minimization**: Case data is fetched on-demand in memory; no persistent raw ticket database copies are stored locally and broker logs contain only sanitized counters.

---

## 5. Deployment & Installation Architecture

Installation is completely automated via PowerShell (`setup_env.ps1`):

```powershell
# 1. Environment Verification
# Checks Python 3.10+, PowerShell 5.1+, and Antigravity App directory

# 2. Dependency Installation (Chromium remains for explicit rollback)
python -m pip install --upgrade pip
pip install mcp playwright urllib3 requests python-pptx

# 3. Playwright Chromium Browser Setup for legacy rollback
playwright install chromium

# 4. Plugin & MCP Deployment
# Copies plugins/avaya-case-review to %USERPROFILE%\.gemini\config\plugins\
# Copies the broker modules and configures GMAIL_BACKEND=edge_broker
# Configures %USERPROFILE%\.gemini\config\mcp_config.json for CaseToMD & Gmail MCP servers
# Checks broker status; runs gmail_brokerctl.py login only on exit code 10
```

---

## 6. Verification & Validation Framework

1. **Unit Testing**: Python MCP bridge validation via STDIO ping/pong test.
2. **Contract Regression Matrix**: `tests/case_review_scenarios.json` covers closed/resolved age handling, single-issue and multi-problem structures, Gmail no-result behavior, status-only activity, lab-versus-production mitigation, missing required tools, conflicting sources, zero evidence, and appendix reverse mapping.
3. **Contract Validator**: `python -m unittest tests.test_case_review_contract -v` verifies the runtime skill, MD/HTML parity, release state, and portable links.
4. **Google Apps Script Validation**: Execute the `doGet()` health check and a controlled `doPost()` test payload.
5. **Presentation & Doc Generation**: Validate the PowerPoint and interactive HTML artifacts when those files change.
