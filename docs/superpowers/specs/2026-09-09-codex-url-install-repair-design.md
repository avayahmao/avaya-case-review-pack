# Codex GitHub URL Installation Repair Design

**Date:** 2026-09-09

**Status:** Approved for implementation planning

## Problem

The supported user request is:

```text
install this plugin: https://github.com/avayahmao/avaya-case-review-pack
```

On a fresh workstation, an AI agent can misclassify the repository as a
standalone skill and look for a root `SKILL.md`. After it discovers the
repository installation contract, it stops again because the contract requires
the user to perform the complete Gmail Apps Script deployment verification and
then assert `-CloudBridgeVerified`.

That behavior combines two responsibilities which belong to different owners:

- deploying and exhaustively verifying the shared Gmail Cloud Bridge is a
  release-maintainer responsibility;
- installing the plugin and authenticating a user's Managed Edge session is a
  workstation responsibility.

The current Codex package also supplies literal `${CLAUDE_PLUGIN_ROOT}` values
as MCP arguments. Codex registers those strings without expanding them, so the
plugin can appear installed while Gmail and CaseToMD fail to load.

## Confirmed Product Decisions

1. The Gmail Cloud Bridge is centrally deployed and verified by the release
   maintainer. End users and their AI agents do not deploy Apps Script.
2. An AI agent must be able to start from the GitHub repository URL, identify
   the repository as a Codex plugin marketplace, clone it safely, run the local
   installer without extra installation flags, and verify the result. In this
   contract, an installation-capable agent has web access, Git, PowerShell,
   permission to execute a checked-out local script, and a supported Codex CLI;
   an agent lacking one of those capabilities must report the missing
   prerequisite rather than claim installation.
3. The only expected interactive pause on a workstation is Google or Microsoft
   SSO/MFA when the Managed Edge profile is not already authorized.
4. Complete Context Before Analysis remains mandatory for every case review.
   Installation checks do not weaken or replace the per-case coverage ledger.
5. Codex and Antigravity continue to share one canonical case-review workflow.

## Goals

- Make the GitHub URL request deterministic for an AI agent.
- Prevent a generic skill installer from installing only part of the product.
- Move exhaustive Cloud Bridge deployment verification to release promotion.
- Keep workstation installation fail-closed against an unavailable or
  incompatible live bridge.
- Make bundled Gmail and CaseToMD MCP launch paths independent of Codex cache
  layout and plugin version directories.
- Provide sanitized, actionable errors and a clean-machine release test.

## Non-Goals

- Do not create a root `SKILL.md`; that would make an incomplete skill-only
  installation appear valid.
- Do not add Claude Code packaging.
- Do not migrate the local Python MCP servers to public remote HTTP services in
  this repair.
- Do not automate, bypass, or falsely attest SSO/MFA.
- Do not replace exhaustive Gmail collection with legacy `gmail_search` or
  `gmail_read` calls.

## Selected Approach

Use the existing Codex compatibility package and repository marketplace, with
three coordinated repairs:

1. Make the GitHub landing documentation an explicit agent bootstrap contract.
2. Replace the workstation's manual cloud-deployment assertion with a
   maintainer-produced release attestation plus a sanitized live compatibility
   check.
3. Install the uniquely named `avaya-case-review-runtime` Python distribution
   and launch its MCP servers with `python -m`, without placeholder expansion
   or post-install cache mutation.

This is preferred over retaining the manual switch because the manual switch
recreates the reported block on every fresh machine. It is preferred over a
portable-plugin migration because local stdio MCP support and the existing
compatibility package already work for this distribution model; that migration
would add risk without solving the immediate defect.

## GitHub URL Agent Bootstrap

The first screen of `README.md` and `README.html`, the URL-install section of
`AGENTS.md`, and `INSTALL.md` must state all of the following before any domain
workflow documentation:

- this repository is a Codex plugin marketplace, not a standalone skill;
- do not send the repository URL to a skill-only installer and do not search
  for a root `SKILL.md`;
- clone the repository into a unique temporary directory before executing any
  local script;
- read the exact current stable install tag published in the same notice, clone
  that tag rather than the moving default branch, and verify that `HEAD` is
  exactly tagged before execution;
- on Codex, run the checked-out `install-codex.ps1` with no cloud-verification
  assertion;
- on Antigravity, run the checked-out `install.bat`;
- allow an explicit pause only if the installer opens Managed Edge for SSO/MFA;
- verify installation and start a new Codex task or restart Antigravity.

The Codex agent flow is:

1. Open the GitHub URL and read the top-level installation notice, including
   its exact stable tag (`v1.10.1` for this repair).
2. Clone that tag into a newly generated temporary directory with
   `git clone --depth 1 --branch v1.10.1`.
3. Verify `git describe --exact-match --tags HEAD` returns `v1.10.1`.
4. Read `INSTALL.md` and inspect the selected local installer.
5. Confirm that Codex CLI is at least `0.153.4` and that Python is available.
6. Run `install-codex.ps1` from the tagged checkout.
7. If requested, let the user complete SSO/MFA and then continue automatically.
8. Confirm the marketplace, plugin, live bridge compatibility, and both MCP
   server definitions.
9. Tell the user to start a new Codex task, as required by Codex plugin loading.

The stable-tag value is release metadata tested alongside the manifests and is
updated only as the final step of preparing a new release. If the tag is
missing, does not match `HEAD`, or cannot be fetched noninteractively, the agent
stops with an actionable error and does not fall back to `main`.

The installer remains the only complete Codex installation entry point. The
two lower-level `codex plugin marketplace add` and `codex plugin add` commands
may be documented as implementation details, not as an equivalent manual path.

The same central-cloud ownership statement appears in the Antigravity path.
`install.bat` remains its entry point; end users are never instructed to deploy
Apps Script themselves.

## Central Cloud Release Gate

### Maintainer verification

`docs/GMAIL_CLOUD_BRIDGE.md` remains the authoritative maintainer runbook. A
release cannot be promoted until its candidate `GmailMcpBridge.gs` has been
deployed to the existing Web App and the following checks pass:

- Advanced Gmail Service `Gmail v1` is enabled;
- zero-result enumeration reports complete coverage;
- a real case preserves one snapshot through every page token;
- a multi-message thread is read through cursor exhaustion;
- manifest, message, byte-count, and body-hash checks pass;
- no sensitive response data is printed or persisted.

Successful verification produces a repository-tracked, non-secret release
attestation at `tools/gmail/cloud/bridge_release_attestation.json`. The schema
is strict and contains these required fields:

- attestation schema version `1`;
- plugin release version `1.10.1`;
- Cloud Bridge protocol version `4`;
- compatibility contract revision `1`;
- SHA-256 identity of the exact `GmailMcpBridge.gs` source;
- an RFC 3339 UTC verification timestamp;
- a `checks` object containing exactly the required true boolean results:
  `advanced_gmail_v1`, `zero_result_complete`,
  `stable_snapshot_pagination`, `cursor_exhaustion`,
  `manifest_message_count_hashes`, and `sensitive_output_absent`.

The Cloud Bridge source contains one `GMAIL_BRIDGE_SOURCE_SHA256` assignment.
The source identity algorithm normalizes line endings to LF, replaces that
assignment's string value with 64 lowercase zeroes, encodes the result as
UTF-8 without a BOM, and calculates SHA-256. A source-controlled stamping and
validation helper at `tools/gmail/cloud/bridge_identity.py` performs that
operation and rejects a missing or duplicate assignment. Its `stamp` command
updates the source identity and its `validate` command checks the source and
attestation without mutation. The computed lowercase hexadecimal digest is
written into the source, copied into the attestation, and returned by the live
endpoint. This avoids a self-referential hash while binding all three surfaces
to one exact source revision. The helper, bridge source, and attestation are all
required entries in `release-manifest.txt` so Git and ZIP installations run the
same validation.

The attestation contains no deployment URL, account identity, case ID, thread
ID, message ID, page token, cursor, cookie, access token, or message-derived
hash. Trust comes from the GitHub repository and immutable release tag; the
attestation proves release coherence and audit history, not an independent
cryptographic identity. The threat model trusts the repository maintainers and
the Apps Script deployment owner; the identity check detects accidental stale
or mismatched deployment, not a malicious owner who deliberately forges an old
identity.

### Live compatibility endpoint

The Cloud Bridge gains a read-only `capabilities` action. It performs no Gmail
query. A successful response has HTTP status `200` and the following required
JSON fields and types:

- `success`: boolean `true`;
- `bridge_version`: integer `4`;
- `contract_revision`: integer `1`;
- `bridge_source_sha256`: 64-character lowercase hexadecimal string;
- `capabilities`: object with true boolean fields `stable_snapshots`,
  `thread_pagination`, `cursor_pagination`, `manifest_sha256`, `body_bytes`,
  and `body_sha256`.

Missing fields, wrong types, false required capabilities, non-JSON responses,
or a digest mismatch are incompatible. Unknown additional fields are ignored
for forward compatibility.

The response must never include account, deployment, query, message, or token
data. Existing `search`, `read`, `send`, `list_threads`, and
`read_thread_page` actions remain unchanged. The action is reached through the
existing authenticated Web App. A Microsoft or Google sign-in redirect is
classified as authentication-required, an HTTP or transport failure is
unavailable, and an authenticated nonconforming response is incompatible.

### Workstation preflight

`gmail_brokerctl.py` gains a control-only `verify-bridge` command. Through the
same Managed Edge path used at runtime, it compares the live `capabilities`
response with `bridge_release_attestation.json`. It returns sanitized outcomes:

The command requires explicit `--source`, `--attestation`, and
`--plugin-version` inputs so the packaged control module never derives
repository paths from its installed location. Invalid inputs map to the
sanitized incompatible result without echoing path or version values.

- exit `0`: authenticated and compatible;
- exit `10`: SSO/MFA is required;
- exit `20`: bridge or broker unavailable;
- exit `30`: malformed response, incompatible version/build/contract, or
  invalid local attestation.

The command is an installer/control operation and is not exposed as an agent
MCP tool. The capability request has a 60-second deadline. Interactive login
retains the existing 300-second browser deadline and 330-second broker request
deadline, reports that it is waiting for the user, and exits with a retryable
authentication error instead of waiting indefinitely.

## Codex MCP Packaging Repair

Codex CLI `0.154` established that relative script arguments are not portable:
from a working directory outside the installed plugin,
`args: ["probe/probe_mcp.py"]` failed before the probe started, while changing
only the argument to an absolute path registered and called the probe. The
selected repair is therefore the approved Python-package fallback:

```json
"args": ["-m", "avaya_case_review_runtime.gmail_mcp_server"]
```

```json
"args": ["-m", "avaya_case_review_runtime.casetomd_mcp_bridge"]
```

The distribution is named `avaya-case-review-runtime`; its only package is
`avaya_case_review_runtime`. Canonical runtime logic lives in that package and
uses package-relative imports. Existing `tools/` modules are thin aliases or
entry points so Antigravity paths and Python patch targets retain identity.
The broker starts by module name without injecting `PYTHONPATH`; the legacy
rollback profile remains under the per-user `.gemini/tools/gmail` tree rather
than site-packages. Installers own installation and rollback of the matching
versioned wheel. Cache-path construction, cache mutation, `${PLUGIN_ROOT}`, and
`${CLAUDE_PLUGIN_ROOT}` are not allowed.

The repair retains `.codex-plugin/plugin.json` and `.mcp.json`. Migration to the
portable root `plugin.json` and `mcp.json` format is deferred to a separate
project.

## Installer Transaction

`install-codex.ps1` performs these stages in order:

1. Validate repository manifests, release version, local bridge source hash,
   and every attestation result before network or installation work.
2. Confirm required commands and install the existing Python dependencies.
3. Start the Managed Edge broker and inspect authentication state.
4. If authentication is required, run the existing guarded interactive login
   flow and resume after it succeeds.
5. Run `verify-bridge`; stop before plugin activation on any nonzero result.
6. Register or refresh the GitHub marketplace at the immutable release tag
   derived from the plugin version. A local marketplace source remains
   available for development and clean-profile tests.
7. Install `avaya-case-review@avaya-case-review-pack`.
8. Verify the installed plugin identity and version and confirm that `codex mcp
   get` reports the Gmail and CaseToMD `python -m avaya_case_review_runtime.*`
   module arguments without unresolved variables.
9. Report success and require a new Codex task.

`-DryRun` performs only local parsing, manifest, attestation-schema, and source
digest validation. It prints the dependency, authentication, live-preflight,
marketplace, plugin, and verification commands it would run, but it does not
start the broker, open Edge, call the cloud endpoint, install dependencies, or
change Codex state.

`-CloudBridgeVerified` remains accepted for one patch release as a deprecated
compatibility parameter, but it never bypasses attestation validation or live
preflight. Documentation no longer instructs users or agents to supply it.

Production installation for this release defaults to the immutable `v1.10.1`
Git ref derived as the letter `v` followed by the manifest version. Using
`main`, a branch, or a commit SHA requires an explicit development or release-
candidate override. This prevents a production URL installation from silently
changing between verification and installation.

Before changing an existing marketplace, the installer records its normalized
remote URL, checked-out Git commit, and whether the plugin is installed. A
different source under the same marketplace name is never removed or
overwritten. The supported same-source ref change is an explicit transaction:

1. record the current marketplace root Git commit and plugin enabled/installed
   state;
2. remove the installed plugin only if it is currently installed;
3. remove the same-source marketplace;
4. add the same Git URL at the target release tag or candidate commit SHA;
5. verify the new marketplace root resolves to the requested commit;
6. add the plugin and verify its identity, version, MCP definitions, and state.

If step 2 fails, the marketplace is not removed. If a later step fails, the
installer removes only the newly added same-source plugin/marketplace, re-adds
the original URL at the recorded commit SHA, restores the previous plugin
installed/enabled state, and verifies the restored commit. If rollback also
fails, both failures are reported and no direct cache deletion or manual file
replacement is attempted. An isolated Codex profile must prove that CLI
`0.153.4` accepts commit SHAs for `marketplace add --ref` and supports this
remove/re-add sequence before production code adopts it.

If installation fails before plugin addition, no plugin is activated. If a
marketplace or plugin command fails after state changes begin, the recorded
state drives the rollback above. The installer reports the exact failed stage
and does not claim completion. It never silently falls back to the legacy
Chromium backend or legacy Gmail APIs.

All noninteractive subprocesses run with visible stage names and bounded
timeouts: 15 seconds for local version/configuration queries, 180 seconds for
Git and Codex marketplace operations, 120 seconds for Codex plugin operations,
300 seconds for Python dependency installation, and 60 seconds for the live
capability request. On timeout, the installer terminates only the child process
tree it started, records the failed stage, and invokes rollback only if Codex
marketplace/plugin state had already changed. A timed-out dependency install
may leave Python packages installed but cannot activate the plugin. Git
credential prompting is disabled for the public repository. Timeout, corporate
proxy, certificate, dependency, or Codex authentication conditions fail with
remediation text instead of becoming an undocumented interactive wait. SSO/MFA
is the only supported intentional interactive step.

### Antigravity parity

`setup_env.ps1` consumes the same attestation and invokes the same
`gmail_brokerctl.py verify-bridge` contract before replacing or activating the
deployed Antigravity plugin. Its existing copy and configuration backup logic
remains authoritative. A failed attestation, login, or live compatibility check
leaves the prior deployed plugin and MCP configuration unchanged. `install.bat`
continues to be a thin entry point and does not accept a cloud-verification
bypass.

## Error and Interaction Contract

Every failure must identify one actionable category without exposing sensitive
data:

- unsupported installer route: use the repository installer, not a skill
  installer;
- missing prerequisite: install or expose Python/Codex in `PATH`;
- authentication required: complete the visible SSO/MFA flow;
- cloud bridge unavailable: retry or contact the bridge maintainer;
- cloud bridge incompatible: maintainer must deploy the build named by the
  release;
- invalid release attestation: use an intact tagged release;
- plugin registration failure: inspect the reported Codex command and exit
  status;
- MCP discovery failure: reinstall the tagged release and start a new task.

The installer must not print the Web App URL, redirected URLs, user identity,
cookies, tokens, case identifiers, Gmail response bodies, or message hashes.

## Test Strategy

### Unit and contract tests

- Apps Script tests validate the exact `capabilities` schema and prove it does
  not call Gmail services. They also validate the normalized self-digest
  algorithm and reject missing, malformed, or mismatched digest values.
- Broker protocol, client, and control-CLI tests validate `verify-bridge`, all
  four exit categories, strict response validation, and output sanitization.
- Packaging tests require exact `python -m avaya_case_review_runtime...`
  arguments, an installable source distribution, compatibility-module identity,
  and no plugin-root placeholders or private Codex cache assumptions.
- Black-box tests install the package into a temporary target and complete MCP
  `initialize` and `tools/list` from an unrelated working directory. The
  Windows desktop release build remains an installed-package release gate.
- Installer tests prove the cloud preflight occurs before marketplace or plugin
  commands, every subprocess deadline terminates only its child process tree,
  rollback restores recorded state, and deprecated `-CloudBridgeVerified`
  cannot bypass the gate.
- Antigravity installer tests prove the same attestation and live-preflight
  contract runs before deployed plugin or MCP configuration replacement.
- Documentation tests require the GitHub URL bootstrap wording and reject a
  root `SKILL.md` or skill-only installation command.

### Installed-artifact smoke tests

Using a unique temporary Codex profile and local marketplace source:

1. install the runtime package into an isolated target;
2. install the plugin without touching the developer's normal Codex profile;
3. inspect the installed plugin and both MCP definitions;
4. start each installed MCP server and complete MCP `initialize` and
   `tools/list` without calling external case or Gmail data;
5. require the five Gmail tools and `get_case_markdown`;
6. repeat installation to prove idempotence;
7. exercise conflicting marketplace, existing same-source marketplace,
   successful and failed ref changes, rollback restoration, invalid
   attestation, incompatible bridge, tag-not-found, resolved-SHA mismatch,
   missing dependency, and plugin-command failure paths.

A second isolated test uses the real GitHub URL and an explicit pushed
candidate commit SHA. It proves repository fetch, marketplace discovery,
plugin selection, and installed MCP launch without relying on an unpublished
final tag. The final `v1.10.1` tag must resolve to that exact tested commit.

Automated clean-profile tests skip interactive login because broker state is
stored under `%LOCALAPPDATA%`, outside the Codex profile. A separate supervised
Windows release check validates the real SSO/MFA flow without altering or
stopping another user's broker. The bridge URL is injectable only in test
processes, allowing redirect, timeout, malformed response, stale digest, and
capability mismatch cases to use a local fake endpoint without changing the
production URL.

### Full regression and release checks

- Run the complete Python and JavaScript test suites.
- Parse-check PowerShell with Windows PowerShell 5.1.
- Verify UTF-8 BOM and CRLF for PowerShell and batch files.
- Run `git diff --check`.
- Build the release ZIP strictly from `release-manifest.txt`.
- Install the release tag on a clean Windows profile from the GitHub URL.
- Start a new Codex task and confirm all six required MCP tools are available.
- Perform one evidence-gated non-production case review with complete coverage.

## File Impact

Expected modifications:

- `README.md`, `README.html`
- `AGENTS.md`
- `INSTALL.md`
- `install-codex.ps1`
- `setup_env.ps1`
- `install.bat` only if its argument forwarding or status text changes
- `.mcp.json`
- `tools/gmail/cloud/GmailMcpBridge.gs`
- `tools/gmail/gmail_edge_broker.py`
- `tools/gmail/gmail_broker_protocol.py`
- `tools/gmail/gmail_broker_client.py`
- `tools/gmail/gmail_brokerctl.py`
- `docs/GMAIL_CLOUD_BRIDGE.md`
- `docs/MANAGER_ONBOARDING_GUIDE.md`, `.html`
- `docs/TECHNICAL_DESIGN_DOCUMENT.md`, `.html`
- `docs/RELEASE_NOTES.md`, `.html`
- relevant Gmail, broker, packaging, and release-manifest tests
- both Codex and Antigravity plugin version manifests
- `release-manifest.txt`

Expected new file:

- `tools/gmail/cloud/bridge_identity.py`
- `tools/gmail/cloud/bridge_release_attestation.json`

Expected removal after preserving and reviewing the current uncommitted work:

- `tools/codex/materialize_mcp_manifest.py`

## Rollout and Rollback

This repair ships as `v1.10.1` because it corrects installation and runtime
loading without changing the case-review output contract.

Rollout order is mandatory:

1. complete the Codex host characterization and marketplace ref/rollback tests;
2. finalize and stamp the candidate Cloud Bridge source identity;
3. deploy the candidate Cloud Bridge to the existing Web App;
4. run the complete maintainer verification suite;
5. create the release attestation bound to that source identity;
6. run local-source clean-profile Codex and Antigravity validation;
7. commit and push code, documentation, tests, and attestation;
8. install from the real GitHub URL at that exact pushed commit SHA in a clean
   Windows profile and record the tested SHA;
9. create protected immutable tag `v1.10.1` at the tested SHA and verify the tag
   resolves to it;
10. repeat the clean-profile installation from only the public GitHub page and
    its advertised `v1.10.1` tag;
11. build the ZIP from the tracked manifest and publish the release;
12. mark affected prior release notes with the appropriate upgrade guidance.

If cloud verification or the live compatibility probe fails, do not publish or
activate the new plugin. Cloud rollback uses the existing documented deployment
procedure. Client rollback follows the recorded same-source transaction above:
remove only the new plugin/marketplace, re-add the previous commit, restore the
previous installed/enabled state, verify it, and start a new Codex task. A
rollback failure is reported without direct cache deletion. Distribution ZIP
files remain release assets and are never committed.

## Acceptance Criteria

1. Giving a capable AI agent only the canonical GitHub URL is sufficient for it
   to identify and execute the correct Codex plugin installation workflow.
2. The agent never asks for a root `SKILL.md` and never installs only
   `skills/case-review` as the complete product.
3. A fresh workstation does not deploy Apps Script, supply a real case ID, or
   assert that maintainer verification occurred.
4. Missing SSO/MFA is the only supported intentional interactive installation
   pause. Other environment or network conditions fail within a documented
   timeout and provide noninteractive remediation.
5. Missing, malformed, or mismatched release attestation or live bridge
   capability data blocks plugin activation with a sanitized action message.
6. `codex plugin list --json` reports
   `avaya-case-review@avaya-case-review-pack` at version `1.10.1` and enabled.
7. Gmail and CaseToMD MCP definitions contain no unresolved plugin-root
   placeholders or hard-coded Codex cache locations.
8. A new Codex task exposes `gmail_search`, `gmail_read`, `gmail_send`,
   `gmail_list_threads`, `gmail_read_thread_page`, and `get_case_markdown`.
9. Reinstallation and upgrade are idempotent, and a failure never reports
   completion or silently enables a partial workflow.
10. The exhaustive per-case collection gate and durable-record behavior remain
    unchanged.
11. Antigravity consumes the same centrally verified cloud identity and does
    not ask an end user to deploy Apps Script.

## Sources

- OpenAI Docs: <https://developers.openai.com/codex/plugins>
- OpenAI Docs: <https://developers.openai.com/plugins/build/plugins>
- Repository installation contract: `INSTALL.md`
- Cloud deployment runbook: `docs/GMAIL_CLOUD_BRIDGE.md`
