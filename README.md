# Avaya Case Review Suite for Support Managers

> **HTML Version Available**: Open **[README.html](README.html)** directly in your browser.

This package provides an automated **Case Review Suite** for Avaya Support & Operations Managers. It supports **Codex** and **Antigravity** and integrates **CaseToMD**, **Gmail**, and the **Embedded 10-Domain Avaya Debugger Knowledge Base** to produce executive-ready case reviews for Siebel SRs and ServiceNow INCs with evidence-grounded technical direction checks.

---

## How does it work

```mermaid
flowchart TD
    Request(["Manager requests a review for an SR, INC, or related record"])
    Request --> Host{"Run in"}
    Host --> Codex["Codex"]
    Host --> Antigravity["Antigravity"]
    Codex --> Workflow["Shared case-review workflow"]
    Antigravity --> Workflow
    Workflow --> CaseToMD["CaseToMD retrieves the official case record"]
    CaseToMD --> Scope["Process every case note and freeze the related record IDs"]
    Scope --> Gmail["Gmail enumerates every matching thread under one stable snapshot"]
    Gmail --> Verify["Read every message and body chunk; verify tokens, counts, and hashes"]
    Verify --> Gate{"Complete Context gate passed?"}
    Gate -->|No| Blocked["Stop: Context collection incomplete<br/>Return sanitized counts and the exact blocker"]
    Gate -->|Yes| Evidence["Build the evidence ledger and load only relevant Avaya references"]
    Evidence --> Storyline["Reconstruct the whole-case storyline<br/>Primary problem -> blocker -> correction -> outcome -> secondary problems"]
    Storyline --> Assess["Assess progress, ownership, technical direction, RCA state, and mitigation maturity"]
    Assess --> Report(["Generate the management review<br/>Executive Summary + Technical Assessment + Progress/Ownership + Evidence Register"])

    classDef host fill:#e0f2fe,stroke:#1e3a5f,color:#0f172a;
    classDef source fill:#fff7ed,stroke:#c2410c,color:#0f172a;
    classDef gate fill:#fef3c7,stroke:#d97706,color:#0f172a;
    classDef blocked fill:#fee2e2,stroke:#dc2626,color:#0f172a;
    classDef output fill:#dcfce7,stroke:#15803d,color:#0f172a;
    class Codex,Antigravity,Workflow host;
    class CaseToMD,Scope,Gmail,Verify source;
    class Gate gate;
    class Blocked blocked;
    class Evidence,Storyline,Assess,Report output;
```

---

## Evidence-Grounded Review Contract

- The executive body is citation-free; all supporting material appears in the final **Appendix A - Evidence Register**.
- Before drafting, the review reconstructs a **whole-case storyline and problem lineage**: original customer objective, intended action, blocker, intermediate working hypotheses, corrected finding, implemented action and primary outcome, then secondary problems in relationship to the primary problem. Latest-message recency or verbosity does not determine narrative weight.
- The report starts with one 6-8 sentence **Executive Summary** paragraph for management and technical readers. It is anchored in the primary problem and complete case lifecycle, then contains conclusion-level timing/location, affected scope, impact, response, RCA-state, mitigation, status, and next-checkpoint information.
- **Technical & Incident Assessment** supplies the technical reasoning: environment, findings, causal mechanism, validation, and unresolved gaps without restating the summary or promoting a secondary issue above the original problem.
- Future prevention is excluded from Executive Summary. **Existing prevention controls** appear only in the technical assessment when case evidence confirms they are implemented. Planned or committed preventive work remains planned work or an evidence-stated next checkpoint; it is never labeled an Existing prevention control or an agent recommendation.
- The appendix table contains Ref, Date, Source, **Verbatim evidence / data**, and **Supports**. The Supports column reverse-maps each row to the body conclusion it validates.
- Any rendered list or table containing dates or timestamps is ordered oldest to newest; undated entries follow dated entries.
- The agent answers only what case-specific evidence supports. With zero verifiable case evidence, it outputs exactly `unknown`.
- **Case record freshness** and **Last substantive progress age** are reported separately; Closed/Resolved records are not stale solely because they are old.
- Mitigation maturity is one of Proposed, Lab Validated, Production Deployed, Production Outcome Confirmed, or None Active.
- Risk and action judgments remain with the Manager. Ownership fields only restate commitments already present in evidence.

**Complete Context Before Analysis** uses the Advanced Gmail Service cloud bridge to process every Case note, query Gmail using the primary raw Case ID only, and process every message in every primary-ID-matched Gmail thread under one stable snapshot. Note-derived related IDs remain available for Case analysis but do not trigger Gmail queries; attachment bodies are excluded. If any source, page-token, cursor, count, hash, manifest, or snapshot check fails, the only result is `Context collection incomplete` with sanitized coverage counts and the blocker. `gmail_search`, `gmail_read`, and `gmail_send` remain backward-compatible APIs, but search and read cannot satisfy this exhaustive gate.

---

## Cloud Prerequisite (Complete Before Local Setup)

Before unpacking or running the local installer, open the existing Gmail MCP Apps Script project and follow [`docs/GMAIL_CLOUD_BRIDGE.md`](docs/GMAIL_CLOUD_BRIDGE.md). Enable the Advanced Gmail Service named Gmail, API version v1; deploy the new Web App version at the existing URL; and verify the zero-result, real-case snapshot/page-token, and multi-message cursor checks. Cloud deployment and verification must complete before any `install-codex.ps1`, `install.bat`, `setup_env.ps1`, or local Agent SKILL activation. If the gate is not satisfied, keep the exhaustive Agent gate inactive.

## Install Directly from the GitHub URL

Codex and Antigravity agents can follow this request:

```text
install this plugin: https://github.com/avayahmao/avaya-case-review-pack
```

The normative machine-actionable steps are in [`INSTALL.md`](INSTALL.md). The agent clones the repository into a unique temporary directory, verifies the cloud prerequisite above, selects the current host, runs the checked-out installer, completes SSO/MFA when requested, and verifies the installed plugin. Remote scripts are never executed without first checking out and inspecting them.

### Codex

After cloud verification, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-codex.ps1 -CloudBridgeVerified
```

This uses the native Codex marketplace flow (`codex plugin marketplace add` followed by `codex plugin add`), installs the bundled Gmail and CaseToMD MCP definitions, and shares the existing per-user Managed Edge broker. Start a new Codex task after installation.

## Antigravity Quick Setup (1-Click)

**Recommended (works under corporate Group Policy):**
1. Unzip the pack.
2. **Double-click `install.bat`** (or from a terminal: `.\install.bat`).
3. The installer deploys the single Managed Edge broker and checks authentication. If its status exits `10`, run `python %USERPROFILE%\.gemini\tools\gmail\gmail_brokerctl.py login` and complete SSO/MFA in the opened Edge window.
4. Restart **Antigravity**.

`install.bat` is a thin wrapper that runs `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_env.ps1`, which is required because Windows PowerShell's default execution policy (`Restricted` / `AllSigned`) blocks unsigned `.ps1` files *before* any code inside the script can adjust the policy.

**Manual (if you prefer to invoke PowerShell yourself):**
```powershell
cd Path\To\avaya-case-review-pack
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_env.ps1
```

### Behind a corporate SSL-inspecting proxy?

The installer automatically works around common corporate SSL inspection (Zscaler / Netskope / Blue Coat) for:
- **pip** - via `--trusted-host pypi.org files.pythonhosted.org ...`
- **Playwright Chromium download** - via `NODE_TLS_REJECT_UNAUTHORIZED=0`, applied only to that single command and restored immediately afterwards.

If your org supplies a corporate CA bundle, prefer setting `NODE_EXTRA_CA_CERTS` to the `.pem` path *before* running `install.bat`:
```powershell
$env:NODE_EXTRA_CA_CERTS = "C:\path\to\corp-ca-bundle.pem"
.\install.bat
```
When that variable is set, the installer uses your CA bundle instead of the bypass. Chromium remains installed for the explicit one-release `legacy_playwright` rollback; normal Gmail traffic uses the Edge broker.

### Gmail broker operations

The broker owns one dedicated Edge context and serializes requests from all Gmail MCP processes. Use `status`, `diagnostics`, `start`, `login`, and `stop` from `gmail_brokerctl.py`; see [`docs/GMAIL_EDGE_BROKER.md`](docs/GMAIL_EDGE_BROKER.md). The rollback switch is explicit (`GMAIL_BACKEND=legacy_playwright`) and there is no automatic fallback. After the cloud gate above passes, the local installer deploys the Python broker modules; it intentionally does not deploy the cloud source.

---

## Complete Documentation Suite (`docs/`)

All project documentation, release notes, installation guides, design specifications, and presentation decks are organized in the **[`docs/`](docs/)** directory:

- **Release Notes & Version Track**:
  - **[docs/RELEASE_NOTES.html](docs/RELEASE_NOTES.html)** / **[docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md)** - v1.9.3 - latest release
- **Executive Presentation**:
  - **[docs/PRESENTATION.html](docs/PRESENTATION.html)** - Interactive Browser Slide Deck
  - **[docs/Avaya_Case_Review_Suite_Presentation.pptx](docs/Avaya_Case_Review_Suite_Presentation.pptx)** - PowerPoint Presentation Deck
- **Technical Architecture & Design**:
  - **[docs/TECHNICAL_DESIGN_DOCUMENT.html](docs/TECHNICAL_DESIGN_DOCUMENT.html)** / **[docs/TECHNICAL_DESIGN_DOCUMENT.md](docs/TECHNICAL_DESIGN_DOCUMENT.md)** - Complete Technical Design Document (TDD)
- **Manager Onboarding & Operational Usage**:
  - **[docs/MANAGER_ONBOARDING_GUIDE.html](docs/MANAGER_ONBOARDING_GUIDE.html)** / **[docs/MANAGER_ONBOARDING_GUIDE.md](docs/MANAGER_ONBOARDING_GUIDE.md)** - Support Manager Setup & Usage Guide
- **Desktop App Installation**:
  - **[docs/ANTIGRAVITY_INSTALLATION_GUIDE.html](docs/ANTIGRAVITY_INSTALLATION_GUIDE.html)** / **[docs/ANTIGRAVITY_INSTALLATION_GUIDE.md](docs/ANTIGRAVITY_INSTALLATION_GUIDE.md)** - Antigravity App Installation & Login Guide

---

## Package Structure

- **`setup_env.ps1`**: Automated environment installer script.
- **`install-codex.ps1`**: Cloud-gated Codex marketplace, plugin, dependency, and Gmail login installer.
- **`INSTALL.md`**: Agent-readable GitHub URL installation contract for Codex and Antigravity.
- **`.codex-plugin/plugin.json` / `.agents/plugins/marketplace.json` / `.mcp.json`**: Codex plugin, marketplace, and bundled MCP metadata.
- **`docs/GMAIL_EDGE_BROKER.md`**: Managed Edge broker operation, authentication, diagnostics, and rollback guide.
- **`docs/GMAIL_CLOUD_BRIDGE.md`**: Advanced Gmail Service deployment, verification, sequencing, and rollback runbook.
- **`docs/`**: Centralized documentation suite (Release Notes, Guides, TDD, Presentations, PowerPoint).
- **`plugins/avaya-case-review/`**: The Case Review plugin containing the `case-review` skill, `gmail-capability` skill, and **10 embedded Avaya product domain reference guides** (`aes-cti-jtapi.md`, `contact-center.md`, `recording-wfo.md`, `analytics-kubernetes.md`, `security-vulnerability.md`, `sip-voice-quality.md`, `certificates-login-outage.md`, `digital-channels.md`, `ip-office.md`, `log-collection.md`).
- **`tools/casetomd/`**: Python bridge for the CaseToMD server (`https://192.168.67.160:8000/mcp`).
- **`tools/gmail/`**: Advanced Gmail Service cloud source, Single Managed Edge broker, thin Gmail MCP adapter, and explicit legacy Playwright rollback backend. `setup_env.ps1` deploys only the local Python modules.
- **`examples/optional-appsscript/`**: Optional, manually deployed Google Apps Script reference for Sheets/Docs/Email digest governance. It is not installed or invoked by the active runtime.
