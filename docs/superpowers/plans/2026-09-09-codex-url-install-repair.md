# Codex GitHub URL Installation Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `install this plugin: https://github.com/avayahmao/avaya-case-review-pack` a deterministic, fail-closed Codex installation flow in which the maintainer owns Cloud Bridge deployment and the workstation pauses only for SSO/MFA.

**Architecture:** Keep the existing repository marketplace and Codex compatibility manifest. Bind every release to a centrally verified Gmail Cloud Bridge identity, validate that identity through the Managed Edge broker before plugin activation, and install the unique `avaya-case-review-runtime` package so MCP servers launch with CWD-independent `python -m` commands. The installer uses bounded subprocesses and a reversible marketplace transaction; Antigravity consumes the same cloud identity without duplicating the case-review workflow.

**Tech Stack:** Windows PowerShell 5.1, Python 3 and `unittest`, Node.js `node:test`, Google Apps Script, Codex CLI `0.153.4+`, JSON-RPC/MCP stdio, Git/GitHub Releases.

**Spec:** `docs/superpowers/specs/2026-09-09-codex-url-install-repair-design.md`

## Global Constraints

- Cloud Bridge deployment and exhaustive verification are maintainer-owned; end users never deploy Apps Script or provide production Case IDs during installation.
- The canonical user input is only `install this plugin: https://github.com/avayahmao/avaya-case-review-pack`.
- The repository is a plugin marketplace, not a standalone skill. Never create a root `SKILL.md` or install only `skills/case-review`.
- SSO/MFA is the only supported intentional interactive pause. Every other blocked condition exits with a sanitized, actionable error.
- Minimum supported Codex CLI for this release is `0.153.4`; the Windows desktop build used for release must also pass host characterization.
- Preserve `edge_broker` as the default and `legacy_playwright` as explicit rollback only; never add automatic fallback.
- Preserve Complete Context Before Analysis, the one-primary-ID Gmail query rule, the Context Coverage Ledger, and durable case records.
- Keep root `skills/` as thin Codex entry points to the canonical workflows under `plugins/avaya-case-review/skills/`.
- Keep PowerShell, batch, and command files UTF-8 BOM plus CRLF. Never disable `.gitattributes` normalization.
- Do not disable corporate SSL globally. Git credential prompting must be disabled for the public repository.
- Do not construct, edit, or delete Codex private cache paths.
- The existing checkout contains unrelated uncommitted work. Execute this plan in an isolated worktree created from commit `274a23a`; do not reset, overwrite, stage, or commit the original checkout's changes.
- Distribution ZIP files remain untracked GitHub Release assets built only from `release-manifest.txt`.

## File Structure

### New files

- `tests/fixtures/codex-relative-mcp-probe/.agents/plugins/marketplace.json` — isolated probe marketplace.
- `tests/fixtures/codex-relative-mcp-probe/.codex-plugin/plugin.json` — minimal probe plugin manifest.
- `tests/fixtures/codex-relative-mcp-probe/.mcp.json` — relative-path MCP fixture.
- `tests/fixtures/codex-relative-mcp-probe/skills/path-probe/SKILL.md` — minimal invocable skill.
- `tests/fixtures/codex-relative-mcp-probe/probe/probe_mcp.py` — reports its script path and launch working directory.
- `tests/test_codex_host_characterization.py` — validates the fixture and isolated CLI marketplace semantics.
- `docs/CODEX_PLUGIN_HOST_COMPATIBILITY.md` — records the required CLI and desktop evidence.
- `tools/gmail/cloud/bridge_identity.py` — source stamping and attestation validation.
- `tools/gmail/cloud/bridge_release_attestation.json` — generated only after the maintainer verification gate passes.
- `tests/test_bridge_identity.py` — strict identity and attestation tests.
- `tests/test_codex_installer.py` — isolated fake-command installer transaction tests.
- `tests/fixtures/run_codex_clean_profile_smoke.ps1` — real CLI clean-profile harness.
- `tests/test_codex_clean_profile_smoke.py` — safe wrapper and fixture assertions for the smoke harness.

### Modified files

- `tools/gmail/cloud/GmailMcpBridge.gs` — source identity and `capabilities` action.
- `tests/js/gmail_cloud_bridge.test.mjs` — no-Gmail capability contract tests.
- `tools/gmail/gmail_broker_protocol.py` — allow control-only `bridge_capabilities`.
- `tools/gmail/gmail_edge_broker.py` — map and execute the capability request.
- `tools/gmail/gmail_brokerctl.py` — `verify-bridge` command and strict comparison.
- `tests/test_gmail_broker_protocol.py`, `tests/test_gmail_edge_adapter.py`, `tests/test_gmail_broker_integration.py`, `tests/test_gmail_brokerctl.py` — broker contract tests.
- `pyproject.toml`, `avaya_case_review_runtime/`, `.mcp.json` — packaged
  runtime and CWD-independent module launch arguments.
- `install-codex.ps1` — bounded commands, central gate, tagged transaction, rollback, and verification.
- `setup_env.ps1` — central-gate preflight before Antigravity replacement.
- `tests/test_codex_plugin_packaging.py`, `tests/test_setup_env_gmail_broker.py`, `tests/test_release_manifest.py` — packaging and installer contracts.
- `README.md`, `README.html`, `AGENTS.md`, `INSTALL.md` — GitHub URL bootstrap and ownership model.
- `docs/GMAIL_CLOUD_BRIDGE.md`, `docs/MANAGER_ONBOARDING_GUIDE.md`, `docs/MANAGER_ONBOARDING_GUIDE.html`, `docs/TECHNICAL_DESIGN_DOCUMENT.md`, `docs/TECHNICAL_DESIGN_DOCUMENT.html` — operator and architecture documentation.
- `.codex-plugin/plugin.json`, `plugins/avaya-case-review/plugin.json`, `docs/RELEASE_NOTES.md`, `docs/RELEASE_NOTES.html`, `release-manifest.txt` — `v1.10.1` release metadata.

### Removed file after Task 1 passes

- `tools/codex/materialize_mcp_manifest.py` — uncommitted cache-mutation workaround; do not import it into the implementation worktree.

---

### Task 1: Characterize Codex MCP and Marketplace Host Behavior

**Files:**
- Create: `tests/fixtures/codex-relative-mcp-probe/.agents/plugins/marketplace.json`
- Create: `tests/fixtures/codex-relative-mcp-probe/.codex-plugin/plugin.json`
- Create: `tests/fixtures/codex-relative-mcp-probe/.mcp.json`
- Create: `tests/fixtures/codex-relative-mcp-probe/skills/path-probe/SKILL.md`
- Create: `tests/fixtures/codex-relative-mcp-probe/probe/probe_mcp.py`
- Create: `tests/test_codex_host_characterization.py`
- Create: `docs/CODEX_PLUGIN_HOST_COMPATIBILITY.md`

**Interfaces:**
- Consumes: Codex plugin marketplace CLI and desktop plugin loader.
- Produces: the recorded relative-MCP failure decision and
  `marketplace add --ref` result for the tested Codex host.

- [ ] **Step 1: Write the failing fixture-contract test**

```python
class CodexHostProbeFixtureTests(unittest.TestCase):
    def test_probe_manifest_uses_one_relative_existing_script(self):
        manifest = json.loads((PROBE_ROOT / ".mcp.json").read_text(encoding="utf-8"))
        server = manifest["mcpServers"]["relative-path-probe"]
        self.assertEqual("python", server["command"])
        self.assertEqual(["probe/probe_mcp.py"], server["args"])
        self.assertTrue((PROBE_ROOT / server["args"][0]).is_file())
        self.assertNotIn("${", server["args"][0])
```

- [ ] **Step 2: Run the fixture test and confirm it fails because the fixture is absent**

Run:

```powershell
python -m unittest tests.test_codex_host_characterization -v
```

Expected: FAIL for missing probe manifest or script.

- [ ] **Step 3: Add the minimal probe marketplace and plugin manifests**

Use marketplace name `codex-relative-mcp-probe`, plugin name
`relative-path-probe`, version `1.0.0`, and this MCP declaration:

```json
{
  "mcpServers": {
    "relative-path-probe": {
      "command": "python",
      "args": ["probe/probe_mcp.py"]
    }
  }
}
```

The skill frontmatter is:

```markdown
---
name: path-probe
description: Invoke the relative-path probe tool for Codex host validation.
---

Call `report_launch_context` exactly once and return its JSON unchanged.
```

- [ ] **Step 4: Implement the dependency-free MCP probe**

`probe_mcp.py` must read newline-delimited JSON-RPC and support only
`initialize`, `notifications/initialized`, `tools/list`, and `tools/call`.
`report_launch_context` returns this object and no environment values:

```python
result = {
    "script_path": str(Path(__file__).resolve()),
    "cwd": str(Path.cwd().resolve()),
}
```

Unknown methods return JSON-RPC `-32601`; malformed requests return `-32600`.

- [ ] **Step 5: Run the fixture test and record the automated result**

```powershell
python -m unittest tests.test_codex_host_characterization -v
```

Expected: PASS with no network or user data access.

- [ ] **Step 6: Characterize Git marketplace SHA handling in an isolated profile**

Use task-specific variables and restore the caller's environment in `finally`:

```powershell
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ("avaya-codex-host-" + [guid]::NewGuid().ToString("N"))
$TestCodexHome = Join-Path $TestRoot ".codex"
$CandidateSha = (git rev-parse HEAD).Trim()
$PreviousCodexHome = $env:CODEX_HOME
try {
    $env:CODEX_HOME = $TestCodexHome
    codex plugin marketplace add https://github.com/avayahmao/avaya-case-review-pack --ref $CandidateSha
    codex plugin marketplace list --json
    codex plugin add avaya-case-review@avaya-case-review-pack --json
    codex plugin remove avaya-case-review@avaya-case-review-pack
    codex plugin marketplace remove avaya-case-review-pack
} finally {
    $env:CODEX_HOME = $PreviousCodexHome
}
```

Expected: the marketplace checkout resolves to `$CandidateSha`; remove and
re-add at the recorded SHA restores the same source and commit. If the CLI does
not accept the SHA or cannot restore state, stop and revise the transaction
design before Task 7.

- [ ] **Step 7: Characterize relative MCP launch on CLI and desktop**

Install the fixture in a disposable authenticated Windows account. Start Codex
from a directory outside the fixture and installed plugin roots. In CLI run:

```powershell
codex --version
codex exec --skip-git-repo-check --json "Use the relative-path-probe plugin. Call report_launch_context exactly once and return its JSON unchanged."
```

Repeat in a new Codex desktop task. Record the exact CLI/app versions,
marketplace source type, and the sanitized booleans
`script_under_installed_plugin_root=true` and
`cwd_outside_installed_plugin_root=true` in
`docs/CODEX_PLUGIN_HOST_COMPATIBILITY.md`. Do not commit absolute paths or the
local username. Both launches pass only when both booleans are true.

- [ ] **Step 8: Apply the decision gate**

The CLI `0.154` outside-CWD probe failed before process start with a relative
argument and succeeded when only the argument became absolute. Record
`RELATIVE_MCP_ARGS=UNSUPPORTED` and continue with the defined
`avaya-case-review-runtime` Python package fallback. Do not implement cache
discovery or cache mutation.

- [ ] **Step 9: Commit the characterization artifacts**

```powershell
git add tests/fixtures/codex-relative-mcp-probe tests/test_codex_host_characterization.py docs/CODEX_PLUGIN_HOST_COMPATIBILITY.md
git commit -m "test: characterize Codex plugin host behavior"
```

### Task 2: Add Deterministic Cloud Bridge Identity and Attestation Validation

**Files:**
- Create: `tools/gmail/cloud/bridge_identity.py`
- Create: `tests/test_bridge_identity.py`
- Modify: `tools/gmail/cloud/GmailMcpBridge.gs:1-2`

**Interfaces:**
- Produces: `compute_source_sha256(source: str) -> str`, `stamp_source(path: Path) -> str`, `write_attestation(source_path: Path, output_path: Path, plugin_version: str, verified_at_utc: str) -> dict[str, object]`, and `validate_attestation(source_path: Path, attestation_path: Path, expected_plugin_version: str) -> dict[str, object]`.
- Consumes later: `install-codex.ps1`, `setup_env.ps1`, `gmail_brokerctl.py`, and the release workflow.

- [ ] **Step 1: Write failing digest-normalization tests**

```python
class BridgeSourceIdentityTests(unittest.TestCase):
    def test_hash_normalizes_line_endings_and_zeroes_only_identity(self):
        lf = 'var GMAIL_BRIDGE_SOURCE_SHA256 = "' + "a" * 64 + '";\nvar X = 1;\n'
        crlf = lf.replace("\n", "\r\n").replace("a" * 64, "b" * 64)
        self.assertEqual(compute_source_sha256(lf), compute_source_sha256(crlf))

    def test_hash_rejects_missing_or_duplicate_identity_assignment(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            compute_source_sha256("var X = 1;\n")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            compute_source_sha256(IDENTITY_LINE + "\n" + IDENTITY_LINE + "\n")
```

- [ ] **Step 2: Write failing strict-attestation tests**

Build temporary attestations with plugin version `1.10.1`, bridge version `4`,
contract revision `1`, a real computed source digest, RFC 3339 UTC timestamp,
and all six required checks. Parameterize missing keys, extra check keys,
non-boolean checks, a false check, malformed timestamps, version mismatch, and
digest mismatch. Each case must raise `ValueError` without echoing the rejected
payload.

- [ ] **Step 3: Run the new tests and confirm the missing module failure**

```powershell
python -m unittest tests.test_bridge_identity -v
```

Expected: FAIL because `tools.gmail.cloud.bridge_identity` does not exist.

- [ ] **Step 4: Implement the identity helper**

Use these constants and signatures:

```python
import hashlib
import re

ATTESTATION_SCHEMA_VERSION = 1
BRIDGE_PROTOCOL_VERSION = 4
CONTRACT_REVISION = 1
IDENTITY_FIELD = "GMAIL_BRIDGE_SOURCE_SHA256"
ZERO_DIGEST = "0" * 64
REQUIRED_CHECKS = frozenset({
    "advanced_gmail_v1",
    "zero_result_complete",
    "stable_snapshot_pagination",
    "cursor_exhaustion",
    "manifest_message_count_hashes",
    "sensitive_output_absent",
})
REQUIRED_ATTESTATION_KEYS = frozenset({
    "schema_version",
    "plugin_version",
    "bridge_version",
    "contract_revision",
    "bridge_source_sha256",
    "verified_at_utc",
    "checks",
})

IDENTITY_RE = re.compile(
    r'(?m)^var GMAIL_BRIDGE_SOURCE_SHA256 = "([0-9a-f]{64})";$'
)

def compute_source_sha256(source: str) -> str:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(IDENTITY_RE.finditer(normalized))
    if len(matches) != 1:
        raise ValueError("bridge source must contain exactly one identity assignment")
    match = matches[0]
    canonical = normalized[: match.start(1)] + ZERO_DIGEST + normalized[match.end(1) :]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Normalize CRLF and CR to LF, replace exactly one quoted digest value with
`ZERO_DIGEST`, encode UTF-8 without BOM, and hash with `hashlib.sha256`. Parse
JSON with duplicate-key rejection. Require exactly the documented top-level and
check keys, exact integer versions, lowercase 64-hex digest, and a UTC timestamp
ending in `Z`. `stamp_source(path)` and `write_attestation(source_path,
output_path, plugin_version, verified_at_utc)` write through temporary siblings
and `os.replace`; the `attest` CLI requires `--all-checks-passed` and emits every
required check as boolean `true`.
`validate_attestation(source_path, attestation_path,
expected_plugin_version)` returns the validated object only after every check
and digest comparison succeeds.

- [ ] **Step 5: Add the source identity constant and stamp it**

Insert after `GMAIL_BRIDGE_VERSION`:

```javascript
var GMAIL_BRIDGE_CONTRACT_REVISION = 1;
var GMAIL_BRIDGE_SOURCE_SHA256 = "0000000000000000000000000000000000000000000000000000000000000000";
```

Run:

```powershell
python tools/gmail/cloud/bridge_identity.py stamp --source tools/gmail/cloud/GmailMcpBridge.gs
```

Expected: one lowercase 64-hex digest is printed and written; a second run
prints the same digest and makes no content change.

- [ ] **Step 6: Run identity tests**

```powershell
python -m unittest tests.test_bridge_identity -v
git diff --check -- tools/gmail/cloud/GmailMcpBridge.gs tools/gmail/cloud/bridge_identity.py tests/test_bridge_identity.py
```

Expected: all identity tests pass and the diff check is clean.

- [ ] **Step 7: Commit the identity implementation**

```powershell
git add tools/gmail/cloud/GmailMcpBridge.gs tools/gmail/cloud/bridge_identity.py tests/test_bridge_identity.py
git commit -m "feat: bind Gmail bridge to a source identity"
```

### Task 3: Add the Gmail-Free Cloud Capabilities Endpoint

**Files:**
- Modify: `tools/gmail/cloud/GmailMcpBridge.gs:13-25,1089-1102`
- Modify: `tests/js/gmail_cloud_bridge.test.mjs`
- Test: `tests/test_gmail_cloud_bridge.py`

**Interfaces:**
- Consumes: constants introduced in Task 2.
- Produces: `GET ?action=capabilities` with the strict public compatibility object from the spec.

- [ ] **Step 1: Write the failing Apps Script test**

```javascript
test("capabilities returns fixed metadata without touching Gmail", () => {
  const { context, calls } = loadBridge();
  const response = JSON.parse(
    context.doGet({ parameter: { action: "capabilities" } }).data,
  );
  assert.deepEqual(response, {
    success: true,
    bridge_version: 4,
    contract_revision: 1,
    bridge_source_sha256: context.GmailBridgeTestExports.bridgeSourceSha256,
    capabilities: {
      stable_snapshots: true,
      thread_pagination: true,
      cursor_pagination: true,
      manifest_sha256: true,
      body_bytes: true,
      body_sha256: true,
    },
  });
  assert.deepEqual(calls.list, []);
  assert.deepEqual(calls.get, []);
  assert.deepEqual(calls.messageGet, []);
  assert.deepEqual(calls.search, []);
  assert.deepEqual(calls.sent, []);
});
```

- [ ] **Step 2: Run the cloud test and confirm it fails on the unknown action**

```powershell
node --test tests/js/gmail_cloud_bridge.test.mjs
```

Expected: FAIL because `capabilities` is not dispatched.

- [ ] **Step 3: Implement and export `capabilities_()`**

Add before Gmail data actions:

```javascript
function capabilities_() {
  return {
    success: true,
    bridge_version: GMAIL_BRIDGE_VERSION,
    contract_revision: GMAIL_BRIDGE_CONTRACT_REVISION,
    bridge_source_sha256: GMAIL_BRIDGE_SOURCE_SHA256,
    capabilities: {
      stable_snapshots: true,
      thread_pagination: true,
      cursor_pagination: true,
      manifest_sha256: true,
      body_bytes: true,
      body_sha256: true,
    },
  };
}
```

Dispatch it with `if (action === "capabilities")` before `search`, and export
`capabilities`, `contractRevision`, and `bridgeSourceSha256` through
`GmailBridgeTestExports`.

- [ ] **Step 4: Restamp the changed source and rerun the tests**

```powershell
python tools/gmail/cloud/bridge_identity.py stamp --source tools/gmail/cloud/GmailMcpBridge.gs
node --test tests/js/gmail_cloud_bridge.test.mjs
python -m unittest tests.test_gmail_cloud_bridge tests.test_bridge_identity -v
```

Expected: all tests pass; the capability response contains no account or Gmail
data and all existing action tests remain green.

- [ ] **Step 5: Commit the capability endpoint**

```powershell
git add tools/gmail/cloud/GmailMcpBridge.gs tests/js/gmail_cloud_bridge.test.mjs tests/test_bridge_identity.py
git commit -m "feat(gmail): expose bridge compatibility capabilities"
```

### Task 4: Add the Control-Only `verify-bridge` Broker Contract

**Files:**
- Modify: `tools/gmail/gmail_broker_protocol.py:12-24`
- Modify: `tools/gmail/gmail_broker_client.py:64-105`
- Modify: `tools/gmail/gmail_edge_broker.py:92-100,217-240,385-428,864-1002`
- Modify: `tools/gmail/gmail_brokerctl.py:18-181`
- Modify: `tests/test_gmail_broker_protocol.py`
- Modify: `tests/test_gmail_broker_client.py`
- Modify: `tests/test_gmail_edge_adapter.py`
- Modify: `tests/test_gmail_broker_integration.py`
- Modify: `tests/test_gmail_brokerctl.py`

**Interfaces:**
- Consumes: `bridge_release_attestation.json` schema and Cloud Bridge `capabilities` response from Tasks 2–3.
- Produces: broker method `bridge_capabilities` and CLI command
  `gmail_brokerctl.py verify-bridge --source PATH --attestation PATH
  --plugin-version VERSION` with exit codes `0`, `10`, `20`, and `30`.
- Does not produce: an MCP tool named `bridge_capabilities` or `verify-bridge`.

- [ ] **Step 1: Add failing protocol and adapter mapping tests**

Extend the allowed-method test with `bridge_capabilities`. Add this adapter
assertion:

```python
def test_bridge_capabilities_maps_to_parameter_free_cloud_action(self):
    url = self.adapter._build_method_url("bridge_capabilities", {})
    self.assertEqual({"action": ["capabilities"]}, parse_qs(urlparse(url).query))
    with self.assertRaisesRegex(BrowserApplicationError, "parameters"):
        self.adapter._build_method_url("bridge_capabilities", {"q": "INC1"})
```

Add `bridge_capabilities` to the safe-read retry test and assert it receives at
most one retry after a browser transport failure.

- [ ] **Step 2: Add failing control-CLI success and sanitization tests**

Extend the existing `RecordingClient` fixture and call
`gmail_brokerctl.main(["verify-bridge", "--source", str(source),
"--attestation", str(path), "--plugin-version", version], client=client)`.
The success assertion is:

```python
self.assertEqual(exit_code, 0)
self.assertEqual(client.calls, [("request", "bridge_capabilities", {})])
self.assertEqual(
    payload,
    {"ok": True, "command": "verify-bridge", "result": {"compatible": True}},
)
```

Inject sentinel URL, identity, cookie, token, Case ID, body, and digest strings
in unknown live-response fields and assert none occur in serialized stdout or
stderr.

- [ ] **Step 3: Add failing negative CLI cases**

Parameterize these expected outcomes:

```python
cases = (
    (BrokerClientError("AUTH_REQUIRED"), 10, "AUTH_REQUIRED"),
    (BrokerClientError("REQUEST_TIMEOUT"), 20, "REQUEST_TIMEOUT"),
    (BrokerUnavailable(), 20, "BROKER_UNAVAILABLE"),
    ("malformed-json", 30, "BRIDGE_INCOMPATIBLE"),
    ({"bridge_version": 3}, 30, "BRIDGE_INCOMPATIBLE"),
)
```

Add one subtest for every missing, wrong-type, false, or mismatched required
field. Also assert `gmail_mcp_server.py` does not list either control method.

- [ ] **Step 4: Run the focused broker tests and observe failures**

```powershell
python -m unittest tests.test_gmail_broker_protocol tests.test_gmail_broker_client tests.test_gmail_edge_adapter tests.test_gmail_broker_integration tests.test_gmail_brokerctl -v
```

Expected: FAIL because the new method, parser command, and validator are absent.

- [ ] **Step 5: Implement broker transport for `bridge_capabilities`**

Add the method to `ALLOWED_METHODS` and `_SAFE_READ_METHODS`. Map only empty
parameters:

```python
elif method == "bridge_capabilities":
    if params:
        raise BrowserApplicationError("Gmail request parameters are invalid")
    action = "capabilities"
    mapped = {}
```

Keep serialization, one-at-a-time browser access, and retry rules unchanged.

- [ ] **Step 6: Implement strict CLI comparison**

Add these helpers to `gmail_brokerctl.py`:

`parse_capabilities_response(raw: object) -> dict[str, object]` accepts only a
JSON object with the required typed fields. `verify_bridge_compatibility(
attestation: dict[str, object], live: dict[str, object]) -> dict[str, bool]`
compares all required values and returns only `{"compatible": True}`. Both
raise `_InvalidResultError` on mismatch without placing rejected values in the
exception text.

For `verify-bridge`, construct `BrokerClient(request_timeout=60)`, load and
validate the local attestation with Task 2's helper, request
`bridge_capabilities`, parse duplicate-safe JSON, and compare protocol version,
contract revision, source digest, and all six true capabilities. Print only:

```json
{"command":"verify-bridge","ok":true,"result":{"compatible":true}}
```

Map local validation and live mismatch to code `BRIDGE_INCOMPATIBLE` with exit
`30`. Preserve existing exit `10` and `20` mappings.

- [ ] **Step 7: Run focused and MCP-surface regression tests**

```powershell
python -m unittest tests.test_gmail_broker_protocol tests.test_gmail_broker_client tests.test_gmail_edge_adapter tests.test_gmail_broker_integration tests.test_gmail_brokerctl tests.test_gmail_mcp_backend -v
```

Expected: all tests pass; the agent-facing Gmail tool list remains exactly five
tools and does not expose either control method.

- [ ] **Step 8: Commit the broker preflight**

```powershell
git add tools/gmail/gmail_broker_protocol.py tools/gmail/gmail_broker_client.py tools/gmail/gmail_edge_broker.py tools/gmail/gmail_brokerctl.py tests/test_gmail_broker_protocol.py tests/test_gmail_broker_client.py tests/test_gmail_edge_adapter.py tests/test_gmail_broker_integration.py tests/test_gmail_brokerctl.py tests/test_gmail_mcp_backend.py
git commit -m "feat(gmail): add attested bridge preflight"
```

### Task 5: Package the Codex MCP Runtime for CWD-Independent Launch

**Files:** `pyproject.toml`, `avaya_case_review_runtime/`, compatibility shims
under `tools/`, `.mcp.json`, package/broker/release tests, release manifest,
and host-compatibility documentation.

**Interfaces:**
- Consumes: `RELATIVE_MCP_ARGS=UNSUPPORTED` evidence from Codex CLI `0.154`.
- Produces: installable runtime modules and cache/CWD-independent Gmail and
  CaseToMD MCP launch definitions.

- [ ] **Step 1:** Write failing tests for exact module arguments, package
  metadata, installed-target MCP handshakes, shim identity, broker launch, and
  release contents.
- [ ] **Step 2:** Move canonical runtime logic into
  `avaya_case_review_runtime`, use relative imports, and leave thin `tools/`
  aliases/entry points.
- [ ] **Step 3:** Install the source into a temporary `--target` directory with
  `--no-deps --no-build-isolation`; from an unrelated CWD, complete
  `initialize`, `notifications/initialized`, and `tools/list` for both MCPs.
- [ ] **Step 4:** Require exactly five Gmail tools and only
  `get_case_markdown`, without invoking an external tool.
- [ ] **Step 5:** Verify compatibility shims, module broker launch without
  `PYTHONPATH` injection, compilation, focused tests, and `git diff --check`.
- [ ] **Step 6:** Commit with
  `fix(codex): package MCP runtime for cwd-independent launch`.

### Task 6: Add a Bounded, Sanitized PowerShell Command Runner

**Files:**
- Create: `tools/installer/windows_common.ps1`
- Modify: `install-codex.ps1:16-39`
- Create: `tests/test_codex_installer.py`
- Modify: `release-manifest.txt`

**Interfaces:**
- Produces: shared `Invoke-BoundedCommand(Stage, Command, Arguments, TimeoutSeconds, AllowFailure)` returning `{ Stage, ExitCode, TimedOut, StdOut, StdErr }`.
- Consumes later: every Python, Git, Codex, and bridge command in both Windows installers.

- [ ] **Step 1: Add a fake-command test harness**

In `tests/test_codex_installer.py`, create temporary `codex.ps1` and
`python.ps1` shims at runtime. They append sanitized event names to the path in
`AVAYA_INSTALL_TEST_LOG`; modes are selected by `AVAYA_INSTALL_TEST_MODE`.
Never commit generated logs or shims.

- [ ] **Step 2: Write failing timeout and argument-boundary tests**

```python
def test_marketplace_timeout_kills_only_started_child_tree(self):
    result, events = run_installer(mode="hang-marketplace")
    self.assertNotEqual(0, result.returncode)
    self.assertIn("marketplace", result.stderr.lower())
    self.assertIn("timed out", result.stderr.lower())
    self.assertNotIn("ancestor-killed", events)

def test_literal_arguments_are_not_reparsed_by_a_shell(self):
    result, events = run_installer(source="C:\\path with spaces\\repo")
    self.assertIn("source=C:\\path with spaces\\repo", events)
```

- [ ] **Step 3: Run the installer tests and confirm they fail**

```powershell
python -m unittest tests.test_codex_installer -v
```

Expected: FAIL because `Invoke-BoundedCommand` and injectable fake-command
resolution do not exist.

- [ ] **Step 4: Implement `Invoke-BoundedCommand` in the shared helper**

Use `System.Diagnostics.ProcessStartInfo` with `UseShellExecute = $false`,
literal argument-list construction, redirected stdout/stderr for noninteractive
commands, and these constants:

```powershell
$TimeoutLocalSeconds = 15
$TimeoutGitSeconds = 180
$TimeoutMarketplaceSeconds = 180
$TimeoutPluginSeconds = 120
$TimeoutPipSeconds = 300
$TimeoutBridgeSeconds = 60
```

On timeout, terminate only the spawned PID and its descendants, wait for exit,
and throw a stage-specific sanitized error. Set `GIT_TERMINAL_PROMPT=0` only in
the Git child environment. Resolve `.ps1` commands through
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File` so test shims and
real scripts retain literal arguments. Keep the existing visible browser login
outside the redirected runner. Dot-source this helper from `install-codex.ps1`.

- [ ] **Step 5: Add dry-run behavior tests**

```python
def test_dry_run_is_offline_and_has_no_state_events(self):
    result, events = run_installer("-DryRun")
    self.assertEqual(0, result.returncode, result.stderr)
    self.assertEqual([], events)
    self.assertIn("validate release attestation", result.stdout.lower())
    self.assertIn("verify-bridge", result.stdout)
    self.assertIn("plugin add", result.stdout)
```

- [ ] **Step 6: Run tests and PowerShell parser validation**

```powershell
python -m unittest tests.test_codex_installer -v
powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './install-codex.ps1'),[ref]$null)|Out-Null"
```

Expected: all focused tests pass and parser exits `0`.

- [ ] **Step 7: Commit the command runner**

```powershell
git add tools/installer/windows_common.ps1 install-codex.ps1 tests/test_codex_installer.py release-manifest.txt
git commit -m "feat(installer): bound noninteractive command stages"
```

### Task 7: Implement the Tagged Marketplace Transaction and Rollback

**Files:**
- Modify: `install-codex.ps1:5-13,41-65,135-188`
- Modify: `tests/test_codex_installer.py`
- Modify: `tests/test_codex_plugin_packaging.py:97-165`

**Interfaces:**
- Produces: `Get-CodexMarketplaceSnapshot`, `Set-CodexMarketplaceAtRef`, and `Restore-CodexMarketplaceSnapshot`.
- Consumes: `Invoke-BoundedCommand` from Task 6 and reads the target ref from the Codex manifest at runtime. Tests supply a temporary manifest whose version is `1.10.1`; Task 10 updates the production manifests.

- [ ] **Step 1: Write failing fresh-install and idempotence tests**

```python
def test_fresh_install_uses_version_derived_tag(self):
    result, events = run_stateful_installer(plugin_version="1.10.1")
    self.assertEqual(0, result.returncode, result.stderr)
    self.assertIn("marketplace-add:v1.10.1", events)
    self.assertIn("plugin-add:avaya-case-review@avaya-case-review-pack", events)

def test_matching_install_is_idempotent(self):
    result, events = run_stateful_installer(existing_sha="new-sha", target_sha="new-sha")
    self.assertEqual(0, result.returncode, result.stderr)
    self.assertNotIn("marketplace-remove", events)
    self.assertNotIn("plugin-remove", events)
```

- [ ] **Step 2: Write failing conflict, ref-change, and rollback tests**

Cover these exact event contracts:

```python
def test_conflicting_source_is_never_removed(self):
    result, events = run_stateful_installer(existing_source="https://example.invalid/other")
    self.assertNotEqual(0, result.returncode)
    self.assertNotIn("plugin-remove", events)
    self.assertNotIn("marketplace-remove", events)

def test_failed_new_plugin_add_restores_old_sha_and_enabled_state(self):
    result, state = run_stateful_installer(
        existing_sha="old-sha",
        target_sha="new-sha",
        plugin_installed=True,
        plugin_enabled=True,
        fail_stage="new-plugin-add",
    )
    self.assertNotEqual(0, result.returncode)
    self.assertEqual("old-sha", state.marketplace_sha)
    self.assertTrue(state.plugin_installed)
    self.assertTrue(state.plugin_enabled)
```

Also test plugin-remove failure leaves the marketplace untouched, resolved-SHA
mismatch triggers rollback, and rollback failure reports both the primary and
rollback stage without cache deletion.

- [ ] **Step 3: Run the transaction tests and confirm failure**

```powershell
python -m unittest tests.test_codex_installer -v
```

Expected: new transaction tests fail against the current upgrade-only logic.

- [ ] **Step 4: Implement snapshot and transaction helpers**

Use these PowerShell contracts:

```powershell
function Get-CodexMarketplaceSnapshot {
    param([string]$MarketplaceName, [string]$PluginName)
    # PSCustomObject: Exists, Source, Root, Commit, PluginInstalled, PluginEnabled
}

function Set-CodexMarketplaceAtRef {
    param([pscustomobject]$Before, [string]$TargetSource, [string]$TargetRef)
    # PSCustomObject: PluginRemoved, MarketplaceRemoved, MarketplaceAdded, PluginAdded
}

function Restore-CodexMarketplaceSnapshot {
    param([pscustomobject]$Before, [pscustomobject]$Transaction)
}
```

Derive the production ref as `"v$($CodexManifest.version)"`. Permit another ref
only when `-AllowUnreleasedRef` is present. Verify the marketplace root's
`git rev-parse HEAD` against the commit resolved by `git ls-remote` before
adding the plugin.

- [ ] **Step 5: Implement the exact same-source transaction**

Run, through the bounded runner, in this order when the recorded commit differs:

```text
codex plugin remove avaya-case-review@avaya-case-review-pack
codex plugin marketplace remove avaya-case-review-pack
codex plugin marketplace add SOURCE --ref TARGET_REF
git -C RESOLVED_MARKETPLACE_ROOT rev-parse HEAD
codex plugin add avaya-case-review@avaya-case-review-pack --json
```

Skip the first command when the plugin was not installed. Reject a different
normalized source before any remove command.

- [ ] **Step 6: Implement rollback from the recorded snapshot**

On a post-mutation failure, remove only state created by this transaction,
re-add the original source with `--ref` set to the recorded commit SHA, restore
the plugin only when it was previously installed, restore its enabled state,
and verify the final commit. Throw one sanitized exception containing both
stage names if rollback also fails.

- [ ] **Step 7: Run transaction and packaging tests**

```powershell
python -m unittest tests.test_codex_installer tests.test_codex_plugin_packaging -v
powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './install-codex.ps1'),[ref]$null)|Out-Null"
```

Expected: all tests pass; no source contains a direct Codex cache deletion.

- [ ] **Step 8: Commit the marketplace transaction**

```powershell
git add install-codex.ps1 tests/test_codex_installer.py tests/test_codex_plugin_packaging.py
git commit -m "feat(installer): transact tagged Codex plugin updates"
```

### Task 8: Integrate Attestation and Live Preflight into the Codex Installer

**Files:**
- Modify: `install-codex.ps1:5-16,67-98,100-188`
- Modify: `tests/test_codex_installer.py`
- Modify: `tests/test_codex_plugin_packaging.py:97-165`

**Interfaces:**
- Consumes: `bridge_identity.py validate`, `gmail_brokerctl.py verify-bridge`, `Invoke-BoundedCommand`, and the marketplace transaction.
- Produces: no-flag production installation with an optional deprecated `-CloudBridgeVerified` parameter that cannot bypass validation.

- [ ] **Step 1: Write the failing gate-order tests**

```python
def test_attestation_and_live_preflight_precede_codex_mutation(self):
    result, events = run_installer(mode="success")
    self.assertEqual(0, result.returncode, result.stderr)
    self.assertLess(events.index("attestation-validate"), events.index("pip-install"))
    self.assertLess(events.index("verify-bridge"), events.index("marketplace-add"))
    self.assertLess(events.index("marketplace-add"), events.index("plugin-add"))

def test_incompatible_bridge_leaves_codex_state_unchanged(self):
    result, events = run_installer(mode="bridge-incompatible")
    self.assertNotEqual(0, result.returncode)
    self.assertNotIn("marketplace-add", events)
    self.assertNotIn("plugin-add", events)
```

- [ ] **Step 2: Write the failing authentication-resume tests**

```python
def test_auth_required_runs_one_login_then_retries_preflight(self):
    result, events = run_installer(mode="auth-then-success")
    self.assertEqual(0, result.returncode, result.stderr)
    self.assertEqual(2, events.count("verify-bridge"))
    self.assertEqual(1, events.count("broker-login"))

def test_deprecated_switch_never_skips_preflight(self):
    result, events = run_installer("-CloudBridgeVerified", mode="bridge-incompatible")
    self.assertNotEqual(0, result.returncode)
    self.assertIn("deprecated", result.stdout.lower())
    self.assertEqual(1, events.count("verify-bridge"))
```

Test login failure and the existing 330-second timeout contract as nonzero,
retryable authentication outcomes. Assert no marketplace event occurs.

- [ ] **Step 3: Run the new installer tests and confirm failure**

```powershell
python -m unittest tests.test_codex_installer tests.test_codex_plugin_packaging -v
```

Expected: FAIL because the current installer exits on the Boolean cloud switch
before it invokes a live preflight.

- [ ] **Step 4: Add local attestation validation**

Resolve the default attestation beside the checkout's bridge source. Invoke:

```powershell
python tools/gmail/cloud/bridge_identity.py validate `
  --source tools/gmail/cloud/GmailMcpBridge.gs `
  --attestation tools/gmail/cloud/bridge_release_attestation.json `
  --plugin-version $CodexManifest.version
```

Use the bounded 15-second local-command deadline. A missing or invalid file
must fail before pip, broker, marketplace, or plugin operations. Retain
`-BridgeAttestationPath` only as an explicit test/release-candidate input; a
production invocation uses the packaged path.

- [ ] **Step 5: Replace the Boolean gate with the broker preflight loop**

After dependencies are available, run `verify-bridge`. If it exits `10`, print
one visible SSO/MFA instruction, invoke `gmail_brokerctl.py login`, and retry
`verify-bridge` exactly once. Exit `20` or `30`, a second exit `10`, or login
failure terminates installation before `Set-CodexMarketplaceAtRef`.

- [ ] **Step 6: Add post-install identity and MCP-definition validation**

Require `codex plugin list --json` to contain one enabled
`avaya-case-review@avaya-case-review-pack` with the manifest version. Require
`codex mcp get gmail --json` and `codex mcp get CaseToMD --json` to report the
two exact module arguments from Task 5 and no string containing `${`.

- [ ] **Step 7: Run focused tests, dry-run, and parser checks**

```powershell
python -m unittest tests.test_codex_installer tests.test_codex_plugin_packaging -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-codex.ps1 -DryRun
powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './install-codex.ps1'),[ref]$null)|Out-Null"
```

Expected: tests pass; dry-run performs no fake-command event; parser exits `0`.

- [ ] **Step 8: Commit the Codex preflight flow**

```powershell
git add install-codex.ps1 tests/test_codex_installer.py tests/test_codex_plugin_packaging.py
git commit -m "fix(codex): preflight bridge before plugin activation"
```

### Task 9: Apply the Central Gate to Antigravity Without Replacing Healthy State Early

**Files:**
- Modify: `setup_env.ps1:321-530`
- Modify: `tests/test_setup_env_gmail_broker.py`
- Modify: `release-manifest.txt`

**Interfaces:**
- Consumes: `tools/installer/windows_common.ps1`, bridge attestation validation, and `gmail_brokerctl.py verify-bridge`.
- Produces: an Antigravity install that validates the central bridge before replacing deployed plugin or MCP files.

- [ ] **Step 1: Write failing phase-order tests**

```python
def test_bridge_preflight_precedes_plugin_and_mcp_replacement(self):
    verify = self.script.index("verify-bridge")
    plugin_copy = self.script.index("Copy-Item -Path $SourcePluginDir")
    config_update = self.script.index("Update-McpConfiguration `")
    self.assertLess(verify, plugin_copy)
    self.assertLess(verify, config_update)
```

Add a fixture case where `verify-bridge` exits `30` and assert the prior plugin
directory and `mcp_config.json` byte content remain unchanged.

- [ ] **Step 2: Write failing authentication and timeout tests**

Use the existing setup fixture to simulate exit sequence `10, 0, 0` for
verify/login/retry. Assert exactly one login. Simulate exits `20`, `30`, and a
330-second login timeout; each must stop before any copy or config update.

- [ ] **Step 3: Run the Antigravity installer tests and confirm failure**

```powershell
python -m unittest tests.test_setup_env_gmail_broker -v
```

Expected: FAIL because current deployment begins before cloud compatibility is
verified.

- [ ] **Step 4: Reorder `setup_env.ps1` into preflight and commit phases**

Use source-checkout scripts to perform local attestation validation, dependency
installation, broker status/login, and `verify-bridge`. Stop the source broker
with the existing safe stop/wait logic before replacing deployed Gmail files.
Only after all preflight steps pass may the script copy the plugin, copy the
explicit Gmail/CaseToMD allowlists, and update MCP configuration.

- [ ] **Step 5: Reuse the bounded runner and preserve rollback behavior**

Dot-source `tools/installer/windows_common.ps1`. Keep source and destination
paths literal. On a deployment failure after copying starts, restore the
existing backups and verify their content hashes. Never stop, delete, or mutate
an unrelated broker/profile.

- [ ] **Step 6: Run installer, migration, parser, and encoding tests**

```powershell
python -m unittest tests.test_setup_env_gmail_broker -v
powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './setup_env.ps1'),[ref]$null)|Out-Null"
python -m unittest tests.test_release_manifest.ReleaseManifestTests.test_windows_entry_points_preserve_utf8_bom_and_crlf -v
```

Expected: all tests pass; PowerShell parses and BOM/CRLF checks pass.

- [ ] **Step 7: Commit Antigravity parity**

```powershell
git add setup_env.ps1 tools/installer/windows_common.ps1 tests/test_setup_env_gmail_broker.py release-manifest.txt
git commit -m "fix(installer): gate Antigravity on bridge compatibility"
```

### Task 10: Publish the GitHub URL Bootstrap and `v1.10.1` Metadata

**Files:**
- Modify: `README.md:1-100`
- Modify: `README.html`
- Modify: `AGENTS.md:8-37,146`
- Modify: `INSTALL.md:1-53`
- Modify: `docs/GMAIL_CLOUD_BRIDGE.md:1-26,247-266`
- Modify: `docs/MANAGER_ONBOARDING_GUIDE.md`, `docs/MANAGER_ONBOARDING_GUIDE.html`
- Modify: `docs/TECHNICAL_DESIGN_DOCUMENT.md`, `docs/TECHNICAL_DESIGN_DOCUMENT.html`
- Modify: `.codex-plugin/plugin.json:3`
- Modify: `plugins/avaya-case-review/plugin.json:3`
- Modify: `docs/RELEASE_NOTES.md`, `docs/RELEASE_NOTES.html`
- Modify: `tests/test_codex_plugin_packaging.py:167-238`

**Interfaces:**
- Produces: a first-screen GitHub instruction contract pinned to `v1.10.1` and synchronized version metadata.
- Consumes: the no-flag installers and central-gate behavior from Tasks 8–9.

- [ ] **Step 1: Write failing documentation-contract tests**

```python
def test_github_bootstrap_is_first_and_rejects_skill_installer(self):
    readme = README_MD.read_text(encoding="utf-8")
    bootstrap = readme.index("AI Agent Installation")
    overview = readme.index("Overview")
    self.assertLess(bootstrap, overview)
    self.assertIn("Codex plugin marketplace, not a standalone skill", readme)
    self.assertIn("git clone --depth 1 --branch v1.10.1", readme)
    self.assertNotIn("install-codex.ps1 -CloudBridgeVerified", readme)

def test_docs_share_stable_tag_and_no_end_user_cloud_deployment(self):
    for path in URL_INSTALL_DOCS:
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("v1.10.1", text)
        self.assertIn("install-codex.ps1", text)
        self.assertNotIn("Before either local installation, deploy", text)
```

Add assertions that no root `SKILL.md` exists and no document recommends a
skill-only install for the full product.

- [ ] **Step 2: Run documentation and manifest tests and confirm failure**

```powershell
python -m unittest tests.test_codex_plugin_packaging -v
```

Expected: FAIL on the old cloud switch, `main` ref, and version `1.10.0` text.

- [ ] **Step 3: Add the first-screen AI agent bootstrap**

The first README notice must include the exact user prompt, exact stable tag,
safe unique-directory clone, exact-tag verification, host selection, and the
no-flag installer commands. State explicitly: “Do not use a skill installer;
the repository root is the plugin selected by its marketplace manifest.”

- [ ] **Step 4: Rewrite cloud ownership and operator documentation**

Move the full Apps Script deployment/check procedure in
`docs/GMAIL_CLOUD_BRIDGE.md` under “Maintainer release gate.” Replace end-user
deployment steps everywhere else with the automatic local attestation and live
compatibility check. Preserve the full verification script and all existing
data-sanitization warnings.

- [ ] **Step 5: Synchronize Markdown and HTML documents**

Update README, manager onboarding, technical design, and release notes in both
formats. Preserve existing navigation, styling, and content outside the
installation sections. The release note must describe the two defects:
incorrect skill-installer routing/manual cloud gate and unresolved Codex MCP
paths.

- [ ] **Step 6: Bump both plugin manifests to `1.10.1`**

Require equality between `.codex-plugin/plugin.json` and
`plugins/avaya-case-review/plugin.json`. Update current-version references in
README and release notes. Do not change the case-review workflow version or
content.

- [ ] **Step 7: Run documentation, packaging, and version tests**

```powershell
python -m unittest tests.test_codex_plugin_packaging tests.test_release_manifest -v
```

Expected: all focused documentation, packaging, and version tests pass. The
production attestation is added and validated by Task 12.

- [ ] **Step 8: Commit documentation and version metadata**

```powershell
git add README.md README.html AGENTS.md INSTALL.md docs/GMAIL_CLOUD_BRIDGE.md docs/MANAGER_ONBOARDING_GUIDE.md docs/MANAGER_ONBOARDING_GUIDE.html docs/TECHNICAL_DESIGN_DOCUMENT.md docs/TECHNICAL_DESIGN_DOCUMENT.html docs/RELEASE_NOTES.md docs/RELEASE_NOTES.html .codex-plugin/plugin.json plugins/avaya-case-review/plugin.json tests/test_codex_plugin_packaging.py
git commit -m "docs: publish GitHub URL plugin bootstrap"
```

### Task 11: Add Isolated Installer and Installed-MCP Smoke Coverage

**Files:**
- Create: `tests/fixtures/run_codex_clean_profile_smoke.ps1`
- Create: `tests/test_codex_clean_profile_smoke.py`
- Modify: `tests/test_codex_installer.py`
- Modify: `tests/test_release_manifest.py`
- Create: `docs/CODEX_PLUGIN_RELEASE_CHECKLIST.md`

**Interfaces:**
- Consumes: complete installers, fake attestation/bridge fixtures, relative MCP package, and rollback transaction.
- Produces: automated isolated tests plus supervised real GitHub/SSO release steps.

- [ ] **Step 1: Write the failing clean-profile harness contract test**

```python
def test_smoke_script_isolated_and_non_destructive(self):
    script = SMOKE_SCRIPT.read_text(encoding="utf-8-sig")
    self.assertIn("$TestCodexHome", script)
    self.assertIn("$PreviousCodexHome", script)
    self.assertIn("finally", script)
    self.assertIn("-SkipLogin", script)
    self.assertNotIn("Remove-Item -Recurse -Force $env:CODEX_HOME", script)
```

- [ ] **Step 2: Implement the safe smoke harness**

The script creates a GUID-named temporary root, assigns its `.codex` child to
`$env:CODEX_HOME`, records the previous value, and restores it in `finally`.
It accepts `-RepositoryRoot`, `-MarketplaceRef`, and
`-BridgeAttestationPath`. It must never delete or stop the production broker;
automated mode supplies fake command adapters and skips interactive login.

- [ ] **Step 3: Add MCP stdio handshake assertions**

For each installed launch command, send these newline-delimited messages:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"release-smoke","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

Assert Gmail exposes exactly `gmail_search`, `gmail_read`, `gmail_send`,
`gmail_list_threads`, and `gmail_read_thread_page`; CaseToMD exposes exactly
`get_case_markdown`. Do not call any tool.

- [ ] **Step 4: Cover the full state and error matrix**

Add isolated cases for fresh install, identical reinstall, same-source upgrade,
different-source conflict, missing tag, resolved-SHA mismatch, invalid
attestation, capability mismatch, auth-required, dependency timeout, plugin-add
failure, successful rollback, and rollback failure. Assert the final synthetic
marketplace/plugin state and sanitized output for every case.

- [ ] **Step 5: Run the smoke and complete local suites**

```powershell
python -m unittest tests.test_codex_clean_profile_smoke tests.test_codex_installer -v
python -m unittest discover -s tests -p "test_*.py" -v
node --test tests/js/gmail_cloud_bridge.test.mjs tests/js/rollback_bridge_v3.test.mjs
```

Expected: all automated tests pass without accessing production Gmail,
CaseToMD, the normal Codex profile, or the production broker.

- [ ] **Step 6: Document the supervised Windows checks**

`docs/CODEX_PLUGIN_RELEASE_CHECKLIST.md` must capture exact versions, candidate
commit SHA, Cloud Bridge digest, CLI relative-path result, desktop
relative-path result, SSO result, six discovered tools, reinstall result, and
rollback result. It must prohibit recording identities, URLs, case IDs, tokens,
cursors, bodies, or message-derived hashes.

- [ ] **Step 7: Commit the smoke harness**

```powershell
git add tests/fixtures/run_codex_clean_profile_smoke.ps1 tests/test_codex_clean_profile_smoke.py tests/test_codex_installer.py tests/test_release_manifest.py docs/CODEX_PLUGIN_RELEASE_CHECKLIST.md
git commit -m "test: cover clean-profile plugin installation"
```

### Task 12: Deploy, Attest, Validate, and Publish `v1.10.1`

**Files:**
- Create: `tools/gmail/cloud/bridge_release_attestation.json`
- Modify: `release-manifest.txt`
- Modify: `tests/test_release_manifest.py`
- Modify: `docs/RELEASE_NOTES.md`, `docs/RELEASE_NOTES.html`
- Create outside Git: `NOTES-v1.10.1.md`
- Create outside Git: `avaya-case-review-pack-v1.10.1.zip`

**Interfaces:**
- Consumes: all prior tasks and the maintainer's authorized Apps Script deployment.
- Produces: immutable tag and GitHub Release `v1.10.1` with a verified ZIP asset.

- [ ] **Step 1: Run the complete pre-deployment suite**

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
node --test tests/js/gmail_cloud_bridge.test.mjs tests/js/rollback_bridge_v3.test.mjs
python -m compileall tools plugins
powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './install-codex.ps1'),[ref]$null)|Out-Null"
powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './setup_env.ps1'),[ref]$null)|Out-Null"
git diff --check
```

Expected: every command exits `0`; no release ZIP exists in the Git index.

- [ ] **Step 2: Restamp and validate the final Cloud Bridge source**

```powershell
python tools/gmail/cloud/bridge_identity.py stamp --source tools/gmail/cloud/GmailMcpBridge.gs
git diff --check -- tools/gmail/cloud/GmailMcpBridge.gs
```

Expected: a second stamp is idempotent and the displayed digest is retained for
the verification record.

- [ ] **Step 3: Pause for maintainer-authorized cloud deployment**

Follow `docs/GMAIL_CLOUD_BRIDGE.md` to update the existing Apps Script Web App,
enable Gmail v1, preserve the deployment URL, and authorize the designated test
account. This is an external deployment gate; do not proceed on missing access,
failed authorization, or an unverified deployment version.

- [ ] **Step 4: Run exhaustive cloud verification**

Execute the documented zero-result, stable page-token chain, cursor exhaustion,
manifest/message count, body byte count, body hash, and no-sensitive-output
checks. Also call `capabilities` through Managed Edge and compare its protocol,
contract, and source digest with the stamped local source. Every check must
print `PASS`.

- [ ] **Step 5: Generate the real release attestation**

```powershell
$VerifiedAtUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
python tools/gmail/cloud/bridge_identity.py attest `
  --source tools/gmail/cloud/GmailMcpBridge.gs `
  --plugin-version 1.10.1 `
  --verified-at-utc $VerifiedAtUtc `
  --all-checks-passed `
  --output tools/gmail/cloud/bridge_release_attestation.json
python tools/gmail/cloud/bridge_identity.py validate `
  --source tools/gmail/cloud/GmailMcpBridge.gs `
  --attestation tools/gmail/cloud/bridge_release_attestation.json `
  --plugin-version 1.10.1
```

Expected: validation exits `0`. Inspect the JSON and confirm it contains none
of the prohibited identifiers or content classes.

- [ ] **Step 6: Add the attestation to the release manifest and rerun everything**

Add exactly these new runtime paths if not already present:

```text
tools/installer/windows_common.ps1
tools/gmail/cloud/bridge_identity.py
tools/gmail/cloud/bridge_release_attestation.json
```

Run the complete Step 1 suite again plus:

```powershell
python -m unittest tests.test_release_manifest -v
```

Expected: all tests pass and extracted-archive validation can run the identity
validator from the packaged files.

- [ ] **Step 7: Push the candidate branch and verify its exact remote SHA**

Stage only intended files; inspect staged names before committing:

```powershell
git add tools/gmail/cloud/bridge_release_attestation.json release-manifest.txt tests/test_release_manifest.py docs/RELEASE_NOTES.md docs/RELEASE_NOTES.html
git diff --cached --name-status
git commit -m "chore(release): prepare v1.10.1"
$CandidateBranch = (git branch --show-current).Trim()
$CandidateSha = (git rev-parse HEAD).Trim()
git push origin "HEAD:refs/heads/$CandidateBranch"
$RemoteCandidateSha = ((git ls-remote origin "refs/heads/$CandidateBranch") -split '\s+')[0]
if ($RemoteCandidateSha -cne $CandidateSha) { throw "Remote candidate SHA mismatch" }
```

Do not stage the ZIP or any pre-existing unrelated file, and never force the
candidate-branch update.

- [ ] **Step 8: Run explicit-SHA clean-profile acceptance**

On a clean Windows account, give an installation-capable AI agent only the
GitHub URL and the explicit release-candidate SHA override. Require it to clone
that SHA, inspect `INSTALL.md`, run the installer, complete SSO/MFA when
`verify-bridge` returns exit `10`,
verify the marketplace checkout SHA, and expose all six MCP tools in a new
Codex task. Record only sanitized results in the release checklist.

- [ ] **Step 9: Fast-forward and verify the default branch**

Only after explicit-SHA acceptance succeeds, fast-forward `origin/main` to the
accepted candidate and verify its exact identity:

```powershell
git push origin HEAD:main
$RemoteMainSha = ((git ls-remote origin refs/heads/main) -split '\s+')[0]
if ($RemoteMainSha -cne $CandidateSha) { throw "Remote main SHA mismatch" }
$DefaultBranchCheckout = Join-Path ([IO.Path]::GetTempPath()) ("avaya-main-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 --branch main https://github.com/avayahmao/avaya-case-review-pack $DefaultBranchCheckout
$DefaultReadme = Get-Content -LiteralPath (Join-Path $DefaultBranchCheckout "README.md") -Raw
$StableBootstrap = "git clone --depth 1 --branch v1.10.1 https://github.com/avayahmao/avaya-case-review-pack <unique-temp-directory>"
if (-not $DefaultReadme.Contains($StableBootstrap) -or -not $DefaultReadme.Contains("git describe --exact-match --tags HEAD")) { throw "Default-branch README is missing the stable v1.10.1 bootstrap" }
```

Never force this update. Verify the default-branch README in a new shallow
`main` checkout exposes the exact stable v1.10.1 clone command and exact-tag
check before creating the tag.

- [ ] **Step 10: Create and verify the immutable release tag**

After the default branch and candidate SHA checks pass:

```powershell
git tag -a v1.10.1 $CandidateSha -m "v1.10.1"
git push origin refs/tags/v1.10.1
$RemoteTagSha = ((git ls-remote origin "refs/tags/v1.10.1^{}") -split '\s+')[0]
if ($RemoteTagSha -cne $CandidateSha) { throw "Remote tag SHA mismatch" }
```

Expected: the remote tag resolves to `$CandidateSha`. Repository protection
must prevent moving or deleting `v*` tags.

- [ ] **Step 11: Run URL-only acceptance**

In a second clean Windows profile, give the AI agent only:

```text
install this plugin: https://github.com/avayahmao/avaya-case-review-pack
```

It must select `v1.10.1` from the GitHub landing page, verify the tag, complete
installation without `-CloudBridgeVerified`, pause only for SSO/MFA, start a
new task, discover all six MCP tools, and perform one non-production
evidence-complete case review.

- [ ] **Step 12: Build and verify the release ZIP**

Do not build from the candidate worktree. Create a fresh, clean, detached
checkout of the immutable tag, verify that the tag peels to the accepted
candidate SHA, and keep the archive outside Git:

```powershell
$ReleaseCheckout = Join-Path ([IO.Path]::GetTempPath()) ("avaya-v1.10.1-" + [guid]::NewGuid().ToString("N"))
$ArchivePath = Join-Path ([IO.Path]::GetTempPath()) "avaya-case-review-pack-v1.10.1.zip"
git clone --no-checkout https://github.com/avayahmao/avaya-case-review-pack $ReleaseCheckout
git -C $ReleaseCheckout checkout --detach v1.10.1
$TaggedSha = (git -C $ReleaseCheckout rev-parse HEAD).Trim()
if ($TaggedSha -cne $CandidateSha) { throw "Tagged checkout SHA mismatch" }
if (@(git -C $ReleaseCheckout status --porcelain).Count -ne 0) { throw "Tagged checkout is not clean" }
@'
import sys
import zipfile
from pathlib import Path

checkout = Path(sys.argv[1])
archive_path = Path(sys.argv[2])
manifest = [
    line.strip()
    for line in (checkout / "release-manifest.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]
with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for name in manifest:
        archive.write(checkout / name, name)
with zipfile.ZipFile(archive_path) as archive:
    actual = archive.namelist()
    if actual != manifest:
        raise SystemExit("ZIP entry list does not exactly equal release-manifest.txt")
    for name in manifest:
        if archive.read(name) != (checkout / name).read_bytes():
            raise SystemExit(f"ZIP member bytes differ from tagged checkout: {name}")
'@ | python - $ReleaseCheckout $ArchivePath
if ($LASTEXITCODE -ne 0) { throw "Release ZIP verification failed" }
if (@(git -C $ReleaseCheckout status --porcelain).Count -ne 0) { throw "Tagged checkout changed during ZIP build" }
```

The ZIP entry list must equal that checkout's manifest exactly and every ZIP
member must equal the corresponding tagged file byte-for-byte. Confirm it
includes the bridge identity helper and attestation and excludes profiles,
state, credentials, and temporary test evidence. Do not add the ZIP to Git.

- [ ] **Step 13: Publish and verify the GitHub Release**

After explicit release authorization:

```powershell
gh release create v1.10.1 .\avaya-case-review-pack-v1.10.1.zip --title "Codex URL installation repair" --notes-file NOTES-v1.10.1.md --latest
gh release view v1.10.1
```

Expected: release `v1.10.1` is latest, the ZIP is attached, and prior affected
release notes contain upgrade guidance. If any release gate fails, do not
publish; use the existing Cloud Bridge rollback procedure and the recorded
same-source client rollback transaction.

## Final Verification Matrix

Before declaring the repair complete, record all of these results in
`docs/CODEX_PLUGIN_RELEASE_CHECKLIST.md`:

| Gate | Required result |
|---|---|
| Relative MCP path, CLI | PASS on Codex CLI `0.153.4` from non-plugin CWD |
| Relative MCP path, desktop | PASS on recorded Windows desktop build |
| Marketplace commit ref | PASS for add, remove/re-add, SHA verification, rollback |
| Cloud source identity | Local source, attestation, and live digest identical |
| Cloud exhaustive checks | Every documented zero/page/cursor/count/hash check PASS |
| Codex clean install | Plugin `1.10.1` enabled; six MCP tools discovered |
| Codex reinstall | No unintended state churn; still six tools |
| Antigravity install | Preflight before replacement; prior state preserved on failure |
| Windows scripts | Parser success, UTF-8 BOM, CRLF |
| Full tests | Python and Node suites exit `0` |
| Distribution | ZIP equals release manifest and is not tracked |
| GitHub URL-only flow | Fresh AI agent completes installation with only SSO/MFA interaction |

## Spec Coverage Map

| Design requirement | Implemented and verified by |
|---|---|
| GitHub URL routes to the complete plugin installer | Tasks 1, 10, 12 |
| Maintainer-owned Cloud Bridge verification | Tasks 2, 3, 10, 12 |
| Non-secret release identity and live compatibility gate | Tasks 2, 3, 4, 8, 9 |
| No unresolved or cache-bound MCP paths | Tasks 1, 5, 11 |
| Bounded noninteractive execution | Tasks 6, 8, 9, 11 |
| Safe marketplace upgrade and rollback | Tasks 1, 7, 11, 12 |
| Codex and Antigravity parity | Tasks 8, 9, 10, 12 |
| SSO/MFA as the only intentional pause | Tasks 4, 8, 9, 11, 12 |
| Complete Context Before Analysis unchanged | Tasks 3, 4, 11, 12 |
| Immutable versioned distribution | Tasks 7, 10, 11, 12 |

## Execution Notes

- Use one focused commit per task. Before every commit, run the task's focused
  tests and inspect `git diff --cached --name-status`.
- After each task, review both requirements compliance and code quality before
  moving to the next task.
- Do not claim a cloud check, desktop-host check, GitHub URL test, tag, push, or
  release succeeded without fresh command output from that exact environment.
- External deployment, tag push, and GitHub Release publication remain explicit
  maintainer authorization gates even when all local tests pass.
