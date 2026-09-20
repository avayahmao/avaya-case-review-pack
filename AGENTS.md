# AGENTS.md — Default Context for the Avaya Case Review Pack

> This file is read automatically by the coding agent when the working directory is inside this repo. It exists so an agent starting fresh does **not** have to rediscover what this project is, where the skill lives, or how the pieces fit together.

---

## 1. What this repo is

The **Avaya Case Review Suite** — a distributable pack for Avaya Support & Operations Managers. It supports both Codex and Antigravity and ships:

The Gmail Apps Script Web App is a maintainer-owned release dependency. End-user
installers validate the local release attestation and live cloud compatibility;
they never ask an end user to deploy the cloud source. The maintainer procedure
is in `docs/GMAIL_CLOUD_BRIDGE.md`.

- an Antigravity/Claude-style **skill** (`case-review`) that turns a raw Siebel SR / ServiceNow INC ID into an executive-ready management brief
- a Codex repository plugin (`.codex-plugin/plugin.json`) and repository marketplace (`.agents/plugins/marketplace.json`) that expose the same canonical workflow and bundled MCP servers
- two **MCP servers** the skill depends on:
  - **CaseToMD** — fetches the case JSON/Markdown from the internal endpoint `https://192.168.67.160:8000/mcp`
  - **Gmail** (single Managed Edge broker with a broker-owned persistent Edge profile; explicit legacy Chromium rollback only) — provides exhaustive case-bounded thread/message collection for `@avaya.com`
- a Windows installer (`install.bat` → `setup_env.ps1`) that deploys the local plugin, MCP, dependency, and broker components into `%USERPROFILE%\.gemini\`; the cloud bridge remains in the existing Apps Script Web App
- 10 embedded Avaya-domain reference guides used for progressive-disclosure knowledge loading

---

## URL-based Agent installation

Canonical request:

```text
install this plugin: https://github.com/avayahmao/avaya-case-review-pack
```

Follow [`INSTALL.md`](INSTALL.md). Do not execute a remote script directly: clone the repository into a unique temporary directory, inspect the checked-out installer, and select the current host's supported entry point.

- **Do not use a skill installer.** This is a Codex plugin marketplace, not a standalone skill; the repository root is the plugin selected by its marketplace manifest.
- **Stable checkout:** run `git clone --depth 1 --branch v1.11.0 https://github.com/avayahmao/avaya-case-review-pack <unique-temp-directory>`, then require `git describe --exact-match --tags HEAD` to return exactly `v1.11.0`. These are the release instructions published by this commit; they do not assert that the tag, GitHub release, release asset, or URL-only acceptance already succeeded.
- **Codex:** run the checked-out no-flag `install-codex.ps1`. It installs the runtime package, validates local attestation and live cloud compatibility, registers the Git-backed marketplace, installs `avaya-case-review@avaya-case-review-pack`, and completes Managed Edge login when required.
- **Antigravity:** run the checked-out no-flag `install.bat`; it validates the same release and retains the existing `setup_env.ps1` deployment into `%USERPROFILE%\.gemini\`.
- **Claude Code:** out of scope. Do not create or install a `.claude-plugin` package.

Interactive SSO/MFA is the only legitimate pause; never claim it succeeded without evidence. Never ask end users to deploy Apps Script or provide a production Case ID during installation. After installation, start a new Codex task or restart Antigravity.

---

## 2. When the user asks for a case review

**Do not reinvent the workflow.** Invoke the `case-review` skill and follow its `SKILL.md` verbatim.

Canonical trigger phrases from the user:
- "Provide a case review for SR 1-23659220672"
- "Status check INC7386572"
- "Where is CTASK0001234 stuck?"
- "Assess this Avaya case"
- Any Avaya case ID pattern: `INC…`, `1-…` (SR), `CTASK…`, `CHG…`, `PRJTASK…`

Skill definition (the source of truth for the workflow):

- **[`plugins/avaya-case-review/skills/case-review/SKILL.md`](plugins/avaya-case-review/skills/case-review/SKILL.md)** — the workflow (fetch CaseToMD → Complete Context Before Analysis → analyze → produce the brief)
- **[`plugins/avaya-case-review/skills/case-review/references/`](plugins/avaya-case-review/skills/case-review/references/)** — 10 domain guides. Read the relevant one(s) based on what the case mentions (AES/JTAPI, Contact Center, Recording/WFO, Analytics, Security, SIP, Certificates/Outage, Digital Channels, IP Office, Log Collection). The SKILL.md has the exact routing table.

Required MCP tools (the skill will call these; fail loudly if missing rather than fabricating a review):

| Tool | Server | Purpose |
|---|---|---|
| `get_case_markdown(report_id)` | CaseToMD | Fetch the case as structured Markdown |
| `gmail_collect_case.py collect/query` (plugin script) | Gmail broker (same backend as the MCP tools) | Primary exhaustive collection: corpus + digest + machine-verified Coverage Ledger manifest in one command |
| `gmail_list_threads(query, snapshot_before, page_token, max_results)` | Gmail | Underlying wire contract; explicit manual rollback when the collector is unavailable |
| `gmail_read_thread_page(thread_id, snapshot_before, cursor)` | Gmail | Underlying wire contract; explicit manual rollback when the collector is unavailable |
| `gmail_search(query)` / `gmail_read(message_id)` | Gmail | Backward-compatible APIs; not the completeness workflow |

If a required MCP server is not configured, tell the user which one and stop — do not invent case content.

For every case review, **Complete Context Before Analysis** is mandatory: process every Case note, retain note-derived related IDs as Case context, then run `plugins/avaya-case-review/skills/case-review/scripts/gmail_collect_case.py collect` for the primary raw Case ID only. The collector exhausts every `gmail_list_threads` page and every `gmail_read_thread_page` cursor under one snapshot, verifies reassembled body hashes and per-thread manifest stability, deduplicates by `thread_id`/`message_id`, and writes `corpus.json` (never loaded into context), `digest.json` (the routing index the agent reads), and `manifest.json` (the Gmail-side **Context Coverage Ledger**). Generate no review until the manifest reports `status: pass` and the case-note counters are equal; use `gmail_collect_case.py query` for budgeted targeted body pulls instead of dumping the corpus. If collection fails, return `Context collection incomplete` with only sanitized counts and the blocker; `--resume` continues an interrupted collection under its original snapshot. The `gmail_list_threads`/`gmail_read_thread_page` MCP tools remain the explicit manual rollback, and `gmail_search`/`gmail_read` remain backward-compatible APIs — never an alternate way to collect a complete review.

The exhaustive cloud endpoint is the existing Gmail MCP Apps Script Web App with the **Advanced Gmail Service** named Gmail, API version v1. Its tracked source is `tools/gmail/cloud/GmailMcpBridge.gs`; it is operational MCP code, not the optional governance example at `examples/optional-appsscript/Code.gs`. Deploy and verify the cloud version first using `docs/GMAIL_CLOUD_BRIDGE.md`, then deploy the local MCP modules and Agent SKILL. `setup_env.ps1` intentionally does not deploy the cloud source. Keep the Agent gate inactive if cloud authorization, stable snapshot/page coverage, cursor exhaustion, or hash/count verification fails.

After a successful evidence-gated review, create or update the durable per-Case-ID follow-up record with `plugins/avaya-case-review/skills/case-review/scripts/case_record.py`. The prior record is only a post-analysis comparison baseline: every follow-up must recollect a fresh CaseToMD/Gmail snapshot, and incomplete collection must leave the record unchanged. Default and material follow-up chat output is investigation-complete: Case Card/delta, progress flow, causal assessment, technical proof states, substantive Timeline, complete dynamic Evidence Register, and durable-record link. `compact` is explicit-only. Administrative closure remains separate from RCA and production outcome. Offer closed-case learning, but draft it only on explicit request and apply sanitized learning to the persistent local domain overlay only after explicit user approval.

---

## 3. Runtime layout vs repo layout

The local files in this repo are deployed by `install.bat` — the runtime paths that Antigravity actually reads are different from the repo paths. The Gmail cloud bridge is deployed separately to the existing Apps Script Web App and is not copied by the local installer.

| Concept | Repo (source of truth, edit here) | Runtime (deployed by installer) |
|---|---|---|
| Codex plugin | repository root: `.codex-plugin/plugin.json`, `.mcp.json`, `skills/`, `tools/` | Codex plugin cache managed by `codex plugin add` |
| Codex marketplace | `.agents/plugins/marketplace.json` | Git-backed marketplace snapshot managed by `codex plugin marketplace add` |
| Plugin | `plugins/avaya-case-review/` | `%USERPROFILE%\.gemini\config\plugins\avaya-case-review\` |
| Skill | `plugins/avaya-case-review/skills/case-review/` | same, under runtime plugin dir |
| Gmail MCP + Edge broker | `tools/gmail/` | `%USERPROFILE%\.gemini\tools\gmail\` (broker state is under `%LOCALAPPDATA%\AvayaCaseReview\gmail-broker`) |
| Gmail cloud bridge | `tools/gmail/cloud/GmailMcpBridge.gs` | Existing Apps Script Web App (manual deployment; not copied locally) |
| CaseToMD MCP | `tools/casetomd/` | `%USERPROFILE%\.gemini\tools\casetomd\` |
| MCP config | (n/a) | `%USERPROFILE%\.gemini\config\mcp_config.json` |
| Managed Edge broker profile (active, broker-owned) | (n/a) | `%USERPROFILE%\.gemini\tools\gmail\edge_broker_profile\` |
| Legacy Chromium rollback profile (rollback only) | (n/a) | `%USERPROFILE%\.gemini\tools\gmail\chrome_profile\` |

The installer sets `GMAIL_BACKEND=edge_broker`. `GMAIL_BACKEND=legacy_playwright` is an explicit rollback only; there is no automatic fallback.

**Debugging tip:** if a fix "isn't taking effect", the user probably edited the repo copy but Antigravity is running the deployed copy. Either re-run `install.bat` or replace the specific file under `%USERPROFILE%\.gemini\…`.

---

## 4. Repo map

```
avaya-case-review-pack/
├── .agents/plugins/marketplace.json ← Codex repository marketplace
├── .codex-plugin/plugin.json        ← Codex plugin manifest
├── .mcp.json                        ← Codex-bundled Gmail + CaseToMD servers
├── AGENTS.md                       ← you are here
├── INSTALL.md                      ← URL-driven Agent installation contract
├── README.md / README.html         ← human-facing quick-start
├── install.bat                     ← 1-click entry point (calls PowerShell w/ -ExecutionPolicy Bypass)
├── install-codex.ps1               ← Codex marketplace/plugin/dependency installer
├── setup_env.ps1                   ← does the actual installation (6 phases)
├── .gitattributes                  ← ENFORCES CRLF + UTF-8 BOM on *.ps1/*.bat/*.cmd
├── .gitignore                      ← ignores avaya-case-review-pack-v*.zip (release-only)
├── plugins/avaya-case-review/
│   ├── plugin.json
│   └── skills/
│       ├── case-review/
│       │   ├── SKILL.md                  ← the workflow
│       │   ├── references/               ← 10 domain guides + output/record contracts
│       │   └── scripts/                  ← durable record + exhaustive Gmail collector + deterministic presenter
│       └── gmail-capability/SKILL.md     ← tells the agent Gmail MCP is available
├── skills/                          ← thin Codex entry points to canonical plugin skills
├── tools/
│   ├── casetomd/casetomd_mcp_bridge.py   ← internal HTTPS MCP bridge
│   ├── gmail/gmail_mcp_server.py         ← async MCP entry point; defaults to GMAIL_BACKEND=edge_broker
│   ├── gmail/gmail_edge_broker.py        ← single Managed Edge browser owner
│   ├── gmail/gmail_brokerctl.py          ← status/diagnostics/start/login/stop control CLI
│   ├── gmail/cloud/GmailMcpBridge.gs     ← Advanced Gmail Service cloud endpoint source
│   └── gmail/gmail_playwright.py         ← legacy Chromium rollback support (not normal login bootstrap)
├── examples/
│   └── optional-appsscript/Code.gs       ← optional, manually deployed governance reference (not runtime)
└── docs/                                 ← guides, TDD, release notes, presentations
```

---

## 5. Non-negotiable conventions

These are enforced by `.gitattributes` / release process — please don't fight them:

1. **`*.ps1`, `*.bat`, `*.cmd` are CRLF + UTF-8 BOM.** LF-only .ps1 files break Windows PowerShell 5.1's here-string parser — this was the v1.2.0 bug. Git normalizes on check-in; do not override.
2. **Distribution zips (`avaya-case-review-pack-v*.zip`) are not tracked in git.** They live only on GitHub Releases. If you build one locally, `gh release create ...` it — do not `git add`.
3. **Never bypass corporate SSL globally.** The installer's `NODE_TLS_REJECT_UNAUTHORIZED=0` is scoped to the single `playwright install chromium` call and restored immediately. If you're adding new network operations that fail behind corp proxy, prefer honoring `NODE_EXTRA_CA_CERTS` first.
4. **Browser login recovery must survive early browser-window close.** The active Managed Edge broker restores and verifies its headless context after login interaction. Any legacy rollback code that reads a page after user interaction must guard with `page.is_closed()` and wrap `context.close()` in `try/except`.
5. **Keep Codex and Antigravity on one canonical workflow.** Root `skills/` files are thin Codex entry points; the full workflow remains under `plugins/avaya-case-review/skills/`. Do not fork the report contract.
6. **Keep the Codex installer centrally cloud-gated.** `install-codex.ps1` must validate local release attestation and live compatibility before state changes; `-CloudBridgeVerified` is a deprecated compatibility parameter and never bypasses validation.

---

## 6. Common tasks — where to look

| Task | Where |
|---|---|
| Change Codex packaging or URL installation | `.codex-plugin/plugin.json`, `.mcp.json`, `.agents/plugins/marketplace.json`, `install-codex.ps1`, and `INSTALL.md` |
| Change the case-review workflow or output modes | `plugins/avaya-case-review/skills/case-review/SKILL.md`, `references/output-modes.md`, `scripts/review_presenter.py`, and `scripts/case_record.py` |
| Change exhaustive Gmail collection | `plugins/avaya-case-review/skills/case-review/scripts/gmail_collect_case.py` (imports `tools/gmail/gmail_broker_client.py`; tests in `tests/test_gmail_collect_case.py`) |
| Add a new Avaya-domain reference | new `.md` in `plugins/avaya-case-review/skills/case-review/references/`, plus a row in the SKILL.md routing table |
| Change the installer | `setup_env.ps1` (invoked by `install.bat`) — verify with `powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './setup_env.ps1'),[ref]$null)|Out-Null"` |
| Change Gmail behavior | `tools/gmail/gmail_mcp_server.py`, `gmail_edge_broker.py`, `gmail_broker_client.py`, `gmail_brokerctl.py`, and `gmail_legacy_backend.py`; keep `edge_broker` as the default and the explicit `legacy_playwright` rollback path tested |
| Deploy the Gmail cloud bridge | Maintainers follow `docs/GMAIL_CLOUD_BRIDGE.md` as a release gate; do not route end users to deploy Apps Script |
| Change CaseToMD behavior | `tools/casetomd/casetomd_mcp_bridge.py` |
| Update docs | `docs/` — HTML and MD versions should be kept in sync, README top-level too |

## 7. Release workflow

The v1.11.0 publication gates are sequential. Do not skip or reorder them, and
never force a branch or tag update.

### 1. Push the candidate branch and verify its exact remote SHA

```powershell
$CandidateBranch = (git branch --show-current).Trim()
$CandidateSha = (git rev-parse HEAD).Trim()
git push origin "HEAD:refs/heads/$CandidateBranch"
$RemoteCandidateSha = ((git ls-remote origin "refs/heads/$CandidateBranch") -split '\s+')[0]
if ($RemoteCandidateSha -cne $CandidateSha) { throw "Remote candidate SHA mismatch" }
```

### 2. Run explicit-SHA clean-profile acceptance

Complete and record the supervised explicit-SHA install using `$CandidateSha`.

### 3. Fast-forward and verify the default branch

```powershell
git push origin HEAD:main
$RemoteMainSha = ((git ls-remote origin refs/heads/main) -split '\s+')[0]
if ($RemoteMainSha -cne $CandidateSha) { throw "Remote main SHA mismatch" }
$DefaultBranchCheckout = Join-Path ([IO.Path]::GetTempPath()) ("avaya-main-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 --branch main https://github.com/avayahmao/avaya-case-review-pack $DefaultBranchCheckout
$DefaultReadme = Get-Content -LiteralPath (Join-Path $DefaultBranchCheckout "README.md") -Raw
$StableBootstrap = "git clone --depth 1 --branch v1.11.0 https://github.com/avayahmao/avaya-case-review-pack <unique-temp-directory>"
if (-not $DefaultReadme.Contains($StableBootstrap) -or -not $DefaultReadme.Contains("git describe --exact-match --tags HEAD")) { throw "Default-branch README is missing the stable v1.11.0 bootstrap" }
```

Never force this update. Verify the default-branch README in a fresh checkout
exposes the exact stable v1.11.0 bootstrap before creating the tag.

### 4. Create and verify the immutable tag

```powershell
git tag -a v1.11.0 $CandidateSha -m "v1.11.0"
git push origin refs/tags/v1.11.0
$RemoteTagSha = ((git ls-remote origin "refs/tags/v1.11.0^{}") -split '\s+')[0]
if ($RemoteTagSha -cne $CandidateSha) { throw "Remote tag SHA mismatch" }
```

### 5. Run URL-only acceptance

Run the canonical GitHub-URL-only install in a second clean Windows profile.

### 6. Build and verify the release ZIP

Build outside Git only from a fresh, clean, detached checkout of `v1.11.0`.
Confirm the tag peels to `$CandidateSha`, use that checkout's
`release-manifest.txt`, require `git status --porcelain` to be empty, require
the ZIP entry list to equal the manifest exactly, and compare every ZIP member
byte-for-byte with the corresponding tagged-checkout file. Do not build from
the candidate worktree. The exact executable procedure is maintained in
`docs/CODEX_PLUGIN_RELEASE_CHECKLIST.md`.

```powershell
$ArchivePath = Join-Path ([IO.Path]::GetTempPath()) "avaya-case-review-pack-v1.11.0.zip"
git clone --no-checkout https://github.com/avayahmao/avaya-case-review-pack $ReleaseCheckout
git -C $ReleaseCheckout checkout --detach v1.11.0
git -C $ReleaseCheckout status --porcelain
```

### 7. Publish the GitHub Release

```powershell
gh release create v1.11.0 $ArchivePath --title "Codex URL installation repair" --notes-file NOTES-v1.11.0.md --latest
```

Release history (most recent first; entries are published on GitHub Releases only after their release gates complete):

- **v1.10.1 (2026-09-14)** — GitHub URL plugin bootstrap, Version-17 complete-response repair, and runtime-packaged Codex MCP launch repair
- **v1.11.0** — Deterministic exhaustive collection and payload assembly
- **v1.10.0** — Investigation-complete reviews, QA scoring, and alarm audit
- **v1.9.4** — Cloud bridge pagination speedup
- **v1.9.3** — Whole-case storyline and problem lineage
- **v1.9.2** — Primary Case ID-only Gmail collection
- **v1.9.1** — Large Gmail thread cursor pagination
- **v1.9.0** — Codex and Antigravity installation
- **v1.8.2** — Gmail body decoding for Apps Script byte-array payloads
- **v1.8.1** — Gmail Cloud Bridge correctness fixes

- **v1.8.0** — Exhaustive Context Collection
- **v1.7.0** — Layered Executive and Technical Reporting
- **v1.6.0** — Single Managed Edge Gmail Broker
- **v1.5.0** — Executive Report Readability Redesign
- v1.4.0 — Evidence-Grounded Workflow Hardening
- v1.3.0 — Technical & Incident Assessment and Bi-Level Recommendations
- v1.2.4 — Agent default context (`AGENTS.md`)
- v1.2.3 — Gmail SSO robustness (early-close guard)
- v1.2.2 — Corporate installer (install.bat + SSL bypass)  *(superseded)*
- v1.2.1 — Encoding hotfix (CRLF + BOM)  *(superseded)*
- v1.2.0 — Original release  *(superseded — installer would not run)*

---

## 8. What NOT to do

- **Do not** grep the whole repo to figure out "how a case review works" — read `plugins/avaya-case-review/skills/case-review/SKILL.md` first.
- **Do not** fetch case data via ad-hoc HTTP calls — use the `get_case_markdown` MCP tool. If it's unavailable, tell the user; do not invent case content.
- **Do not** edit `%USERPROFILE%\.gemini\…` files as if they're the source; they're deployment artifacts. Edit under `plugins/` or `tools/` here, then re-run `install.bat` (or copy the specific file across).
- **Do not** re-commit a zip. `.gitignore` will refuse; if you defeat it, the release process breaks.
- **Do not** disable Windows-script encoding normalization in `.gitattributes` — that's what stops the v1.2.0 bug from ever recurring.
- **Do not** add Claude Code packaging; the supported installation targets are Codex and Antigravity.
