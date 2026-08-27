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
|    Codex or Antigravity Windows App (Agent Runtime & Markdown Renderer)            |
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

### 3.1 Client Layer: Codex and Antigravity Runtimes
- **Target OS**: Windows 10 / 11 64-bit
- **Codex Discovery**: Loads `.codex-plugin/plugin.json`, root `skills/`, and `.mcp.json` through the Git-backed `avaya-case-review-pack` marketplace.
- **Antigravity Discovery**: Scans `%USERPROFILE%\.gemini\config\plugins` for active skills and MCP configurations deployed by `setup_env.ps1`.
- **Execution Mode**: Host-controlled agent execution with structured tool invocations and live streaming Markdown report output; filesystem/network permissions follow the selected host's policy.

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
The current case-review workflow fetches CaseToMD first, processes every Case note, retains explicitly stated related IDs as Case context, then exhausts `gmail_list_threads` page tokens for the primary raw Case ID only under one shared snapshot. It reads every message in every primary-ID-matched Gmail thread with `gmail_read_thread_page` through cursor exhaustion, including every snapshot-eligible body chunk. The Context Coverage Ledger requires exactly one completed record-ID query and must pass all note, thread, message, chunk, hash, manifest, and snapshot equalities before analysis or report generation.

The first list call may bootstrap with an empty `snapshot_before`; the successful response must return a non-empty snapshot, and every later list/read call must reuse that exact same value. Any incomplete collection returns only `Context collection incomplete` with sanitized coverage counts and the blocker; no review sections, partial RCA, ownership conclusion, or Evidence Appendix are emitted. `gmail_search` and `gmail_read` remain backward-compatible APIs and explicit legacy rollback surfaces, never an alternate way to collect case context.

The cloud side is the existing Gmail MCP Apps Script Web App backed by the **Advanced Gmail Service** named Gmail, API version v1. Its tracked source is `tools/gmail/cloud/GmailMcpBridge.gs`, distinct from `examples/optional-appsscript/Code.gs`. Deploy and verify the cloud version before deploying local MCP modules or activating the Agent gate; `setup_env.ps1` intentionally does not install Apps Script source. The Agent sends only the primary raw Case ID to Gmail; related IDs from Case notes or Gmail do not expand the query plan, and attachment bodies are excluded. See `docs/GMAIL_CLOUD_BRIDGE.md` for verification and rollback.

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

#### Structured ReviewSnapshot v2 and Presentation Modes
Before rendering, the analysis builds a **structured ReviewSnapshot v2**: current Case Card fields, whole-case storyline and problem lineage from the primary problem through blockers, corrections, outcome, and secondary problems, fixed proof-state Technical Specification, milestones, timeline, Evidence Register, and evidence-only visual context. Source recency and message length do not determine narrative weight.

The deterministic `review_presenter.py` router exposes six modes:

1. **standard**: Default investigation-complete first or unchanged review with Case Card, mandatory Investigation Progress flow, Causal Assessment, six key Technical Specification fields, substantive Timeline, complete dynamic Evidence Register, and an optional secondary diagnostic visual.
2. **compact**: Explicit compact request only; renders the Case Card without the investigation-complete sections.
3. **follow-up**: Automatic delta-first view when a prior successful review has material state, ownership, or evidence changes; it then renders the same investigation-complete core as standard.
4. **technical**: Fixed `Field | Proof state | Value | Evidence basis` Technical Specification.
5. **flow**: Explicit investigation visual with chronology-not-causality wording and a seven-node Mermaid limit.
6. **full**: Explicit structured report; the only mode that renders Appendix A — Evidence Register, with that section last.

The standard/follow-up renderer always includes a bounded Investigation Progress flow. The secondary diagnostic router may add at most one event comparison, claim-evidence matrix, component swimlane, or ownership checkpoint. Visual context never invents recurrence, hypotheses, component handoffs, or causal edges. Mitigation maturity remains Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active.

All dated milestones, timeline rows, and evidence rows are ordered oldest to newest; undated entries follow dated entries.

#### Evidence Processing Contract
1. **Evidentiary authority** is evaluated independently from management display priority.
2. Direct logs and official record facts outrank summaries for factual conclusions.
3. Case notes and Gmail form one chronological evidence stream, but latest-message recency and verbosity do not determine the primary problem or narrative weight.
4. Later evidence may establish current state or explicitly supersede an earlier interpretation; it does not erase the original objective, the reason work paused, or intermediate actions.
5. Source conflicts remain visible and disputed conclusions remain `unknown` until resolved.
6. Evidence entries are never split, duplicated, or invented to reach a target count.
7. A reference guide may explain case evidence but cannot replace it.
8. `standard` and `follow-up` render the complete dynamic Evidence Register; `compact`, `technical`, and `flow` contain no Evidence IDs. `Supports` reverse-maps each evidence row to exact structured conclusions.
9. The agent does not generate risk lists, scores, or directives. The agent does not generate recommendations. Evidence-backed commitments may be restated only as planned work or evidence-stated next checkpoints.
10. Any rendered list or table containing dates or timestamps is sorted ascending by normalized date/time; the freshness calculation still uses the newest dated evidence internally.
11. Build structured analysis before presentation; do not draft narrative prose and then attempt to compress it.
12. Distinguish `NOT OBSERVED`, `NOT COLLECTED`, `UNKNOWN`, and `NOT APPLICABLE`; never use numeric confidence percentages.
13. Existing prevention controls appear only when evidence confirms implementation. Planned work remains planned and is never an agent recommendation.
14. Milestones have no minimum count, remain chronological, and never pad or repeat evidence.

#### Durable Follow-up Record and Closed-Case Learning

After a successful evidence-gated review, `plugins/avaya-case-review/skills/case-review/scripts/case_record.py` atomically creates or updates one record under `%LOCALAPPDATA%\AvayaCaseReview\case-records\<CASE-ID>\`. `record.json` stores ReviewSnapshot v2 and deterministic state/history; `record.md` is the compact human view. `present --markdown-only` writes canonical `chat-output.md` and `chat-output.sha256`, and `verify-final` rejects a proposed final response that differs beyond line-ending or final-newline normalization. Detailed technical, visual, and full views are generated on demand. Duplicate completed snapshots are idempotent, and v1 records migrate without losing history or their legacy report.

The prior record is loaded only by the post-analysis comparison step. It is not evidence, does not alter source scope, and cannot satisfy the current coverage gate. The helper rejects incomplete coverage, mismatched counters, missing hashes/manifests, unsupported RCA or mitigation states, and empty evidence digests before any write.

Administrative state is derived separately from RCA, mitigation, and production outcome. Closed, Resolved, or Completed makes learning available but never changes an `unknown` technical outcome. On explicit request, the workflow drafts a customer-sanitized candidate with its evidence strength, activation conditions, diagnostic steps, disconfirming signals, and limitations. `apply-learning --approved-by-user` is required before the candidate is placed in `%LOCALAPPDATA%\AvayaCaseReview\domain-knowledge\<domain>.md`. Local overlays are loaded after packaged references and remain diagnostic guidance rather than case proof. A later reopened state automatically suspends the originating case's applied overlay entry until reclosure and reapproval.

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
5. **Data Minimization**: Raw Gmail corpora and attachment bodies are not persisted. The user-controlled follow-up record stores ReviewSnapshot v2, a decisive evidence digest, and compact longitudinal state under `%LOCALAPPDATA%\AvayaCaseReview`; approved learning must remove customer-specific data. Broker logs contain only sanitized counters.

---

## 5. Deployment & Installation Architecture

The cloud deployment is an explicit prerequisite: deploy and verify the existing Gmail MCP Apps Script with the Advanced Gmail Service named Gmail, API version v1, using `docs/GMAIL_CLOUD_BRIDGE.md`. Cloud deployment and verification must complete before any local install or local Agent SKILL activation. The checked-out repository then exposes two supported local installation modes; neither installer deploys the cloud source:

```powershell
# Codex: validate the acknowledgement, install dependencies, add the Git marketplace,
# install avaya-case-review@avaya-case-review-pack, and complete broker login if required.
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-codex.ps1 -CloudBridgeVerified

# Antigravity: install.bat invokes setup_env.ps1 to deploy the plugin and MCP runtime
# under %USERPROFILE%\.gemini\.
.\install.bat
```

The Antigravity setup path performs these local phases:

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
6. **Codex Packaging**: Run the plugin validator, `tests/test_codex_plugin_packaging.py`, the PowerShell parser, and a reversible local marketplace/plugin installation smoke test.
7. **Case Record Lifecycle**: `python -m unittest tests.test_case_record -v` verifies atomic creation/update, append-only history, delta computation, duplicate idempotency, incomplete-collection immutability, closure separation, and approval-gated learning overlays.
