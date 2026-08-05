# Technical Design Document (TDD): Avaya Case Review Suite & Intelligent Diagnostic Engine

---

## 1. Executive Summary & System Objectives

The **Avaya Case Review Suite** is an enterprise-grade AI governance system designed for Avaya Support Managers, Operations Leads, Service Delivery Managers (SDMs), and Technical Escalation Managers. 

The system automates the synthesis of raw ticket data (Siebel SRs and ServiceNow INCs) and off-system email communications (Google Workspace / Gmail), while applying **evidence-triggered technical direction checks** from an embedded 10-Domain Avaya UC/CC expert knowledge base.

### Key Capabilities
1. **1-Click Executive Case Brief Generation**: Transforms hundreds of pages of raw database dumps into clean, executive-ready markdown reports.
2. **Unified Off-System Email Synthesis**: Integrates headless Playwright browser automation with Google Workspace to extract SDM threads, customer commitments, and auto-router (OCD) "UNASSIGNABLE" dispatch alerts.
3. **Evidence-Triggered Technical Direction Checks**: The engine compares retrieved evidence to conditional product references and documents validation gaps and handoff context; reference comparison alone does not prove cause or vendor ownership.
4. **Optional Workspace Governance Extension (not deployed)**: The repository keeps a manually deployable Apps Script reference for Sheets/Docs/digest workflows. It is outside the active installer, MCP, and case-review runtime.

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
| 3. ENTERPRISE DATA SOURCES           |    | 4. GOOGLE WORKSPACE SERVICES          |
|  * Siebel SR Database / ServiceNow   |    |  * @avaya.com Gmail Inbox             |
|  * HTTPS Endpoint:                   |    |  * Optional Apps Script governance    |
|    https://192.168.67.160:8000/mcp   |    |    reference (manual deployment only) |
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
- **Tools Exposed**: `gmail_list_threads(query, snapshot_before, page_token, max_results)` and `gmail_read_thread_page(thread_id, snapshot_before, cursor)` provide the exhaustive case-review collection contract. `gmail_search(query)`, `gmail_read(message_id)`, and `gmail_send(to, subject, body)` retain their schemas as backward-compatible APIs and explicit legacy rollback surfaces; they are not the completeness workflow.
- **Operations**: `status`, `diagnostics`, `start`, `login`, and `stop` expose only sanitized state. The default is `GMAIL_BACKEND=edge_broker`; `GMAIL_BACKEND=legacy_playwright` is an explicit one-release rollback with no automatic fallback.
- **Security**: State and lifetime lock files live under `%LOCALAPPDATA%\AvayaCaseReview\gmail-broker`; logs never contain queries, message content, recipients, cookies, or tokens.

#### Complete Context Before Analysis
The current case-review workflow fetches CaseToMD first, processes every Case note, freezes the primary plus every supported related ID explicitly present in those notes, then exhausts `gmail_list_threads` page tokens for every frozen ID under one shared snapshot. It reads every message in every matched Gmail thread with `gmail_read_thread_page` through cursor exhaustion, including every snapshot-eligible body chunk. The Context Coverage Ledger must pass all note, query, thread, message, chunk, hash, manifest, and snapshot equalities before analysis or report generation.

The first list call may bootstrap with an empty `snapshot_before`; the successful response must return a non-empty snapshot, and every later list/read call must reuse that exact same value. Any incomplete collection returns only `Context collection incomplete` with sanitized coverage counts and the blocker; no review sections, partial RCA, ownership conclusion, or Evidence Appendix are emitted. `gmail_search` and `gmail_read` remain backward-compatible APIs and explicit legacy rollback surfaces, never an alternate way to collect case context.

The cloud side is the existing Gmail MCP Apps Script Web App backed by the **Advanced Gmail Service** named Gmail, API version v1. Its tracked source is `tools/gmail/cloud/GmailMcpBridge.gs`, distinct from `examples/optional-appsscript/Code.gs`. Deploy and verify the cloud version before deploying local MCP modules or activating the Agent gate; `setup_env.ps1` intentionally does not install Apps Script source. The frozen related-ID boundary does not expand from Gmail-discovered IDs, and attachment bodies are excluded. See `docs/GMAIL_CLOUD_BRIDGE.md` for verification and rollback.

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

#### Conditional Technical Direction Checks
1. **Platform vs Application Layers**: When retrieved case evidence matches a layer mismatch, compare platform and application hypotheses and identify the validation needed to distinguish them. Do not present CM configuration as causal without case evidence.
2. **System Attribute References**: Treat `SA9114` and `SA9124` as conditional verification references only when park/unpark evidence triggers them. The review does not inspect the live system and must not claim it does.
3. **API Method Reference**: When UCID evidence activates the check, compare case evidence with official Javadoc, including `LucentV5CallInfo.getUCID()`. This comparison does not enforce a method or prove causation.
4. **Log Evidence Sufficiency**: Distinguish logs that were requested, collected, attached, and analyzed, then identify evidence gaps without assuming silence means absence. `getlogs`, `csta_trace`, and `g3trace` are conditional examples, not universal requirements.

#### Output Brief Schema
1. **Executive Summary & Status**: One citation-free 6-8 sentence paragraph containing conclusion-level incident, timing/location, affected scope, impact, response, a one-sentence RCA state or supported conclusion, mitigation maturity and production outcome, current status, and the next evidenced checkpoint.
2. **Freshness Model**:
   - **Case record freshness** measures the age of the official record update.
   - **Last substantive progress age** measures the age of the latest concrete technical or operational change.
   - Closed/Resolved records are excluded from age-only staleness flags.
3. **Conditional Technical Assessment**: Starts with problem clarification and adds technical reasoning through environment and findings, causal mechanism, solution and validation, and unresolved gaps. It uses exactly one multi-problem `Problem Statement` or single-issue `Incident & RCA Summary`.
4. **Mitigation Maturity**: Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active.
5. **Progress Summary and Timeline**: Progress Summary renders up to five substantive milestones supported by evidence and renders one when only one exists; it never pads or repeats evidence. Status pings remain available for stall analysis but are omitted from display when non-substantive. Rendered dated or timestamped entries are ordered oldest to newest; undated entries follow dated entries.
6. **Ownership & Next Step**: Assignee, last concrete action, stated next action, owner, and due date. It only restates evidence-backed commitments.
7. **Appendix A — Evidence Register**: The final section, using `Ref | Date | Source | Verbatim evidence / data | Supports`.

#### Evidence Processing Contract
1. **Evidentiary authority** is evaluated independently from management display priority.
2. Direct logs and official record facts outrank summaries for factual conclusions.
3. Source conflicts remain visible and disputed conclusions remain `unknown` until resolved.
4. Evidence entries are never split, duplicated, or invented to reach a target count.
5. A reference guide may explain case evidence but cannot replace it.
6. The body contains no Evidence IDs; `Supports` reverse-maps each appendix row to exact body conclusions.
7. The agent does not generate risk lists, scores, or directives. The agent does not generate recommendations. Evidence-backed commitments may be restated only as planned work or evidence-stated next checkpoints.
8. Any rendered list or table containing dates or timestamps is sorted ascending by normalized date/time; the freshness calculation still uses the newest dated evidence internally.
9. Generate Technical & Incident Assessment before extracting Executive Summary so the headline conclusion has one reasoning source.
10. Remove technical paragraphs that only paraphrase the summary without new findings, mechanism, validation, or unresolved gaps.
11. Future prevention is excluded from Executive Summary. Existing prevention controls appear only under the relevant technical problem when evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.
12. Progress Summary has no minimum count; its displayed milestone count follows the available substantive evidence and never pads or repeats evidence.

#### Vendor Handoff Reference Matrix
This reference applies only after case evidence establishes the failing component. It does not assign vendor ownership; the Manager retains ownership and risk judgment.

- **Evidence-confirmed CM / AES core defect** — **reference destination: [BBE PEA]** (CM ASAI, AES service crash, crossID exhaustion).
- **Evidence-confirmed POM / AEP product-code defect** — **reference destination: [CPE PEA]** (POM campaign engine, AEP application server, REST driver).
- **Evidence-confirmed Verint / WFO / RIS / WebLogic defect** — **reference destination: [Verint Support Ticket]** (ACRA recording failure, RIS connection, DMSA).
- **Evidence-confirmed Nuance MRCP / ASR / TTS defect** — **reference destination: [Nuance Support Ticket]** (speech recognition grammar errors, MRCP v2 timeout).
- **Evidence-confirmed customer infrastructure condition** — **reference destination: Customer / MSP** (LDAP authentication, SQL database, firewall ports).


---

### 3.4 Optional Google Apps Script Governance Extension (`examples/optional-appsscript/Code.gs`)

This file is a reference implementation for an optional Google Sheets/Docs governance workflow. It is not part of the active runtime: `setup_env.ps1` does not install it, no MCP server calls its `doPost()` handler, and the Gmail cloud `doGet(e)` endpoint is a separate application. It should be deployed manually only when persistent Sheets/Docs tracking or scheduled manager digests are an explicit requirement.

#### Optional capabilities

```javascript
/**
 * 1. doPost(e): HTTP Webhook Endpoint
 * Receives JSON payload from a separately configured caller.
 */
function doPost(e) { ... }

/**
 * 2. updateCaseTrackingSheet(caseData): Google Sheet Governance Dashboard
 * Appends or updates case row in 'Case Tracker' sheet with conditional status formatting.
 */
function updateCaseTrackingSheet(caseData) { ... }

/**
 * 3. createGoogleDocReport(caseData): Google Doc Brief Generator
 * Creates a formatted Google Doc brief with the Executive Summary and Evidence Appendix.
 */
function createGoogleDocReport(caseData) { ... }

/**
 * 4. sendDailyManagerDigest(): Scheduled Manager Email Digest
 * Evaluates 'Case Tracker' sheet daily for Stalled (>7/30 days) and At Risk cases, sending HTML email alerts via MailApp.
 */
function sendDailyManagerDigest() { ... }
```

#### Activation requirements

Before using this optional extension, configure its Google Apps Script project, set the spreadsheet/folder/email settings, deploy the Web App with an appropriate access policy, connect a caller that posts the payload, and create the manager-digest trigger. None of these steps are performed by the installer.

#### JSON Payload Contract for `doPost` Webhook

This payload applies only to a manually deployed optional extension and a separately configured caller; it is not sent or consumed by the active runtime.

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
      "supports": "Executive Summary — Status: Stalled; Ownership — Next owner"
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
4. **Optional Apps Script Validation**: Only when the governance extension is separately deployed, execute its `doGet()` health check, a controlled `doPost()` test payload, and the configured trigger. This is not part of the standard release validation.
5. **Presentation & Doc Generation**: Validate the PowerPoint and interactive HTML artifacts when those files change.
