# AGENTS.md — Default Context for the Avaya Case Review Pack

> This file is read automatically by the coding agent when the working directory is inside this repo. It exists so an agent starting fresh does **not** have to rediscover what this project is, where the skill lives, or how the pieces fit together.

---

## 1. What this repo is

The **Avaya Case Review Suite** — a distributable pack for Avaya Support & Operations Managers. It ships:

- an Antigravity/Claude-style **skill** (`case-review`) that turns a raw Siebel SR / ServiceNow INC ID into an executive-ready management brief
- two **MCP servers** the skill depends on:
  - **CaseToMD** — fetches the case JSON/Markdown from the internal endpoint `https://192.168.67.160:8000/mcp`
  - **Gmail** (single Managed Edge broker with a broker-owned persistent Edge profile; explicit legacy Chromium rollback only) — provides exhaustive case-bounded thread/message collection for `@avaya.com`
- a Windows installer (`install.bat` → `setup_env.ps1`) that deploys everything into `%USERPROFILE%\.gemini\`
- 10 embedded Avaya-domain reference guides used for progressive-disclosure knowledge loading

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
| `gmail_list_threads(query, snapshot_before, page_token, max_results)` | Gmail | Exhaustively enumerate case-bounded threads under one snapshot |
| `gmail_read_thread_page(thread_id, snapshot_before, cursor)` | Gmail | Exhaustively read every eligible message/body chunk |
| `gmail_search(query)` / `gmail_read(message_id)` | Gmail | Backward-compatible APIs; not the completeness workflow |

If a required MCP server is not configured, tell the user which one and stop — do not invent case content.

For every case review, **Complete Context Before Analysis** is mandatory: process every Case note, freeze the primary and note-derived related IDs, exhaust every `gmail_list_threads` page, and exhaust every `gmail_read_thread_page` cursor for every unique matched thread. Maintain the **Context Coverage Ledger** and generate no review until its equalities pass. If collection fails, return `Context collection incomplete` with only sanitized counts and the blocker. `gmail_search` and `gmail_read` remain backward-compatible APIs and explicit legacy rollback surfaces, never an alternate way to collect a complete review.

---

## 3. Runtime layout vs repo layout

The files in this repo get **deployed** by `install.bat` — the runtime paths that Antigravity actually reads are different from the repo paths.

| Concept | Repo (source of truth, edit here) | Runtime (deployed by installer) |
|---|---|---|
| Plugin | `plugins/avaya-case-review/` | `%USERPROFILE%\.gemini\config\plugins\avaya-case-review\` |
| Skill | `plugins/avaya-case-review/skills/case-review/` | same, under runtime plugin dir |
| Gmail MCP + Edge broker | `tools/gmail/` | `%USERPROFILE%\.gemini\tools\gmail\` (broker state is under `%LOCALAPPDATA%\AvayaCaseReview\gmail-broker`) |
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
├── AGENTS.md                       ← you are here
├── README.md / README.html         ← human-facing quick-start
├── install.bat                     ← 1-click entry point (calls PowerShell w/ -ExecutionPolicy Bypass)
├── setup_env.ps1                   ← does the actual installation (6 phases)
├── .gitattributes                  ← ENFORCES CRLF + UTF-8 BOM on *.ps1/*.bat/*.cmd
├── .gitignore                      ← ignores avaya-case-review-pack-v*.zip (release-only)
├── plugins/avaya-case-review/
│   ├── plugin.json
│   └── skills/
│       ├── case-review/
│       │   ├── SKILL.md                  ← the workflow
│       │   └── references/               ← 10 domain guides
│       └── gmail-capability/SKILL.md     ← tells the agent Gmail MCP is available
├── tools/
│   ├── casetomd/casetomd_mcp_bridge.py   ← internal HTTPS MCP bridge
│   ├── gmail/gmail_mcp_server.py         ← async MCP entry point; defaults to GMAIL_BACKEND=edge_broker
│   ├── gmail/gmail_edge_broker.py        ← single Managed Edge browser owner
│   ├── gmail/gmail_brokerctl.py          ← status/diagnostics/start/login/stop control CLI
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

---

## 6. Common tasks — where to look

| Task | Where |
|---|---|
| Change the case-review workflow | `plugins/avaya-case-review/skills/case-review/SKILL.md` |
| Add a new Avaya-domain reference | new `.md` in `plugins/avaya-case-review/skills/case-review/references/`, plus a row in the SKILL.md routing table |
| Change the installer | `setup_env.ps1` (invoked by `install.bat`) — verify with `powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './setup_env.ps1'),[ref]$null)|Out-Null"` |
| Change Gmail behavior | `tools/gmail/gmail_mcp_server.py`, `gmail_edge_broker.py`, `gmail_broker_client.py`, `gmail_brokerctl.py`, and `gmail_legacy_backend.py`; keep `edge_broker` as the default and the explicit `legacy_playwright` rollback path tested |
| Change CaseToMD behavior | `tools/casetomd/casetomd_mcp_bridge.py` |
| Update docs | `docs/` — HTML and MD versions should be kept in sync, README top-level too |

## 7. Release workflow

```bash
# 1. Build the zip locally from the tracked release manifest (never mirror a prior ZIP)
python -c "
import zipfile
from pathlib import Path
manifest = [line.strip() for line in Path('release-manifest.txt').read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')]
with zipfile.ZipFile('avaya-case-review-pack-vNEW.zip','w',zipfile.ZIP_DEFLATED,9) as z:
    for name in manifest: z.write(name)
"
# 2. Commit code changes (NOT the zip — it's gitignored)
git add <changed files>
git commit -m "..."
git push origin main
# 3. Publish the release + attach the zip
gh release create vNEW ./avaya-case-review-pack-vNEW.zip --title "..." --notes-file NOTES.md --latest
# 4. If it fixes bugs from the prior release, edit that release's notes with a superseded banner
gh release edit vPREV --notes-file SUPERSEDED.md
```

Version history (all on GitHub Releases, most recent first):

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
