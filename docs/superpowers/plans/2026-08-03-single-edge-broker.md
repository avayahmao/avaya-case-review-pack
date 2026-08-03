# Single Managed Edge Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Gmail MCP to a single authenticated local Edge broker that safely serves multiple MCP processes while preserving the existing Gmail tool contract and one-release legacy rollback.

**Architecture:** Thin MCP clients communicate with one per-user broker over authenticated loopback NDJSON. The broker owns one persistent Managed Edge context and serializes all browser work; platform/state helpers enforce singleton startup, atomic discovery, sanitized logging, and crash recovery.

**Tech Stack:** Python 3.14, MCP Python SDK, Playwright async API with Microsoft Edge, asyncio TCP streams, msvcrt cross-session file locking, unittest, Windows PowerShell 5.1 installer.

---

## File Responsibilities

- Create `tools/gmail/gmail_edge_common.py`: shared auth classifier, safe result model, URL builder, and profile guards.
- Modify `tools/gmail/gmail_edge_poc.py`: import shared common primitives; remain an isolated diagnostic CLI.
- Create `tools/gmail/gmail_broker_protocol.py`: strict request/response schemas, error codes, NDJSON framing, size limits, token comparison.
- Create `tools/gmail/gmail_broker_state.py`: state directory, atomic state file, stale-state checks, lifetime cross-session file lock, sanitized rotating log.
- Create `tools/gmail/gmail_edge_broker.py`: TCP server, single Edge owner, queue, auth state machine, login switching, idle shutdown, crash recovery.
- Create `tools/gmail/gmail_broker_client.py`: state discovery, health, lazy startup, request transport, typed client errors.
- Create `tools/gmail/gmail_brokerctl.py`: operator status/login/start/stop/diagnostics commands.
- Create `tools/gmail/gmail_legacy_backend.py`: existing Playwright-per-request implementation retained unchanged for rollback.
- Modify `tools/gmail/gmail_mcp_server.py`: backend selection and thin MCP adapter.
- Modify `setup_env.ps1`: deploy all modules, set backend mode, create/secure state directory, conditionally authenticate.
- Create `release-manifest.txt`: explicit distribution package contents including every broker module and guide.
- Modify `AGENTS.md`: build releases from the tracked manifest instead of copying the previous ZIP list.
- Modify `.gitignore`: ignore broker/profile/runtime state only if a repository-local test path is introduced.
- Create focused broker/common/client/backend/installer tests under `tests/`.
- Update README, Manager Guide, Technical Design, release notes, and paired HTML files.

### Task 1: Extract Shared Edge Authentication Primitives

**Files:**
- Create: `tools/gmail/gmail_edge_common.py`
- Modify: `tools/gmail/gmail_edge_poc.py`
- Create: `tests/test_gmail_edge_common.py`
- Modify: `tests/test_gmail_edge_poc.py`

- [ ] **Step 1: Write failing common-module tests**

```python
import unittest
from pathlib import Path
from tools.gmail.gmail_edge_common import (
    AuthState, ProbeResult, build_action_url, classify_response,
    validate_profile_path,
)

class CommonContractTests(unittest.TestCase):
    def test_mcas_is_auth_required(self):
        self.assertIs(
            classify_response(
                "https://tenant.access.mcas.ms/aad_login", 200, ""
            ),
            AuthState.AUTH_REQUIRED_MICROSOFT,
        )

    def test_build_action_url_encodes_params(self):
        url = build_action_url("search", {"q": "1-23508794022"})
        self.assertIn("action=search", url)
        self.assertIn("q=1-23508794022", url)

    def test_rejects_normal_edge_profile(self):
        home = Path(r"C:\Users\tester")
        with self.assertRaises(ValueError):
            validate_profile_path(
                home / "AppData/Local/Microsoft/Edge/User Data", home
            )
```

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_gmail_edge_common -v
```

Expected: import failure because `gmail_edge_common.py` does not exist.

- [ ] **Step 3: Move pure primitives into the common module**

The common module exports:

```python
class AuthState(str, Enum): ...

@dataclass(frozen=True)
class ProbeResult:
    state: AuthState
    http_status: int | None
    final_host: str
    final_path: str
    body_length: int
    elapsed_ms: int

def build_action_url(action: str, params: dict[str, str]) -> str: ...
def classify_response(final_url: str, http_status: int | None, body: str) -> AuthState: ...
def validate_profile_path(profile: Path, user_home: Path) -> Path: ...
```

`gmail_edge_poc.py` imports these symbols and retains only PoC session/CLI logic.

- [ ] **Step 4: Run common and PoC tests**

```powershell
python -m unittest tests.test_gmail_edge_common tests.test_gmail_edge_poc -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add tools/gmail/gmail_edge_common.py tools/gmail/gmail_edge_poc.py tests/test_gmail_edge_common.py tests/test_gmail_edge_poc.py
git commit -m "refactor(gmail): share Edge authentication primitives"
```

### Task 2: Define the Authenticated Broker Protocol

**Files:**
- Create: `tools/gmail/gmail_broker_protocol.py`
- Create: `tests/test_gmail_broker_protocol.py`

- [ ] **Step 1: Write failing protocol tests**

```python
import unittest
from tools.gmail.gmail_broker_protocol import (
    BrokerErrorCode, BrokerRequest, ProtocolError,
    decode_request, encode_response,
)

class ProtocolTests(unittest.TestCase):
    def test_decodes_valid_request(self):
        raw = (
            b'{"version":1,"id":"abc","token":"secret",'
            b'"method":"gmail_search","params":{"query":"sr"}}\n'
        )
        request = decode_request(raw)
        self.assertEqual(request.method, "gmail_search")

    def test_rejects_unknown_method(self):
        with self.assertRaises(ProtocolError):
            decode_request(
                b'{"version":1,"id":"x","token":"t",'
                b'"method":"shell","params":{}}\n'
            )

    def test_rejects_oversize_frame(self):
        with self.assertRaises(ProtocolError):
            decode_request(b"x" * (8 * 1024 * 1024 + 1))
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_gmail_broker_protocol -v
```

Expected: missing module.

- [ ] **Step 3: Implement strict protocol models**

```python
PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 8 * 1024 * 1024
ALLOWED_METHODS = {
    "health", "gmail_search", "gmail_read", "gmail_send",
    "auth_login", "shutdown",
}

class BrokerErrorCode(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INVALID_REQUEST = "INVALID_REQUEST"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    BROWSER_ERROR = "BROWSER_ERROR"
    APP_ERROR = "APP_ERROR"
```

`decode_request` rejects missing/extra top-level fields, unsupported versions/methods, non-object params, invalid IDs, and oversized/non-UTF-8 frames. Token validation uses `secrets.compare_digest`.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m unittest tests.test_gmail_broker_protocol -v
git add tools/gmail/gmail_broker_protocol.py tests/test_gmail_broker_protocol.py
git commit -m "feat(gmail): define broker wire protocol"
```

### Task 3: Implement Broker State and Windows Singleton

**Files:**
- Create: `tools/gmail/gmail_broker_state.py`
- Create: `tests/test_gmail_broker_state.py`

- [ ] **Step 1: Write failing atomic-state and stale-state tests**

```python
class BrokerStateTests(unittest.TestCase):
    def test_atomic_state_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BrokerStateStore(Path(tmp))
            state = BrokerState(1, 123, "127.0.0.1", 41000, "token", "now")
            store.write(state)
            self.assertEqual(store.read(), state)

    def test_missing_pid_marks_state_stale(self):
        state = BrokerState(1, 999999, "127.0.0.1", 1, "t", "now")
        self.assertTrue(is_stale_state(state, process_exists=lambda pid: False))
```

- [ ] **Step 2: Write failing cross-session owner-lock tests**

Test an injected lock backend for unit behavior, then run a real two-subprocess
test against a temporary `broker.lock`: the first process holds the
`msvcrt.locking` byte-range lock and the second must receive
`AlreadyRunning`. This is the authoritative owner test; a session-local mutex
alone is insufficient.

- [ ] **Step 3: Implement state store and platform helpers**

```python
@dataclass(frozen=True)
class BrokerState:
    protocol_version: int
    build_id: str
    instance_id: str
    pid: int
    host: str
    port: int
    token: str
    started_at: str

class BrokerStateStore:
    def write(self, state: BrokerState) -> None:
        # write UTF-8 JSON to sibling temp, flush/fsync, os.replace
        ...
```

Implement `LifetimeFileLock` by opening `broker.lock` and holding a
non-blocking one-byte `msvcrt.locking` lock until shutdown. State cleanup
must compare `instance_id` before removing `state.json`.

When creating the state directory/file on Windows, apply an ACL containing
only the current user and SYSTEM. Add a test around an injected ACL runner so
the exact `icacls` target and principals are verified without changing the
developer machine.

- [ ] **Step 4: Add sanitized rotating logger**

Allow only timestamp, level, event, request ID, method, result code, timing, queue depth, and lifecycle counters. Reject arbitrary structured fields.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m unittest tests.test_gmail_broker_state -v
git add tools/gmail/gmail_broker_state.py tests/test_gmail_broker_state.py
git commit -m "feat(gmail): add broker singleton and state"
```

### Task 4: Build the Serialized Broker with a Fake Browser

**Files:**
- Create: `tools/gmail/gmail_edge_broker.py`
- Create: `tests/test_gmail_broker_integration.py`

- [ ] **Step 1: Define a browser adapter seam**

```python
class BrowserAdapter(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def execute(self, method: str, params: dict[str, str]) -> str: ...
    async def interactive_login(self) -> AuthState: ...
```

Production uses `ManagedEdgeAdapter`; tests use `FakeBrowserAdapter`.

- [ ] **Step 2: Write failing four-client concurrency test**

Start the broker on port 0 with a fake adapter. Submit 20 requests from four concurrent clients. Assert:

```python
self.assertEqual(fake.start_count, 1)
self.assertEqual(fake.max_concurrency, 1)
self.assertEqual(len(responses), 20)
self.assertTrue(all(response["ok"] for response in responses))
```

- [ ] **Step 3: Write failing auth/error and queue tests**

Cover invalid token, malformed frame, response correlation, queue depth,
auth-required mapping, and send-not-retried behavior. Model separate
300-second queue wait and 60-second browser execution deadlines; the client
deadline is 370 seconds.

- [ ] **Step 4: Implement broker server**

Use `asyncio.start_server`, one request per accepted connection,
`asyncio.Lock` around browser execution, separate queue/execution deadlines,
and strict protocol helpers.

`health` returns only:

```json
{
  "protocol_version": 1,
  "pid": 123,
  "edge_state": "AUTHENTICATED",
  "queue_depth": 0,
  "request_count": 20,
  "browser_start_count": 1,
  "browser_crash_count": 0,
  "current_browser_concurrency": 0,
  "max_browser_concurrency": 1,
  "build_id": "test-build",
  "instance_id": "test-instance",
  "uptime_seconds": 60
}
```

Add a representative-latency test for 20 serialized requests and assert the
later requests do not hit the client deadline. Send a sentinel value such as
`SENTINEL_SECRET_7b91` through success, error, and timeout paths and assert
it never appears in the broker log.

- [ ] **Step 5: Implement two-hour idle shutdown**

Inject the clock in tests. Prove active work prevents shutdown and idle broker closes browser before state cleanup.

- [ ] **Step 6: Run tests and commit**

```powershell
python -m unittest tests.test_gmail_broker_integration -v
git add tools/gmail/gmail_edge_broker.py tests/test_gmail_broker_integration.py
git commit -m "feat(gmail): add serialized Edge broker"
```

### Task 5: Implement Client Discovery and Lazy Startup

**Files:**
- Create: `tools/gmail/gmail_broker_client.py`
- Create: `tests/test_gmail_broker_client.py`

- [ ] **Step 1: Write failing healthy-state request test**

With a fake loopback broker and temporary state file, verify `BrokerClient.request()` sends token/version/ID and returns the correlated result.

- [ ] **Step 2: Write failing stale-state and startup-race tests**

Inject process launcher and sleep functions. Simulate four clients starting simultaneously; assert one ready broker response and no client launches a browser.

- [ ] **Step 3: Implement typed client errors**

```python
class BrokerClientError(RuntimeError):
    code: str

class BrokerStartTimeout(BrokerClientError): ...
class BrokerUnavailable(BrokerClientError): ...
class BrokerProtocolMismatch(BrokerClientError): ...
```

- [ ] **Step 4: Implement hidden broker startup**

Derive the interpreter from `sys.executable`; do not search PATH for a
different Python. Launch the absolute broker script path with
`CREATE_NO_WINDOW` as the single Windows hidden-process strategy, set an
explicit state-directory working directory, and pass no token or Gmail params
on the command line. Poll atomic state and health for up to 15 seconds.

Test startup from an unrelated working directory and from an injected virtual
environment interpreter path.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m unittest tests.test_gmail_broker_client -v
git add tools/gmail/gmail_broker_client.py tests/test_gmail_broker_client.py
git commit -m "feat(gmail): add broker client autostart"
```

### Task 6: Add the Managed Edge Adapter and Login Switching

**Files:**
- Modify: `tools/gmail/gmail_edge_broker.py`
- Create: `tests/test_gmail_edge_adapter.py`

- [ ] **Step 1: Write adapter tests with a fake Playwright facade**

Verify one persistent context, one page per request, early auth redirect classification, body non-logging, safe read retry after one crash, and no send retry.

- [ ] **Step 2: Implement Managed Edge execution**

Use `edge_broker_profile`, `channel="msedge"`, one headless context, and the shared classifier. Supported methods map to the existing Apps Script action/parameter names.

- [ ] **Step 3: Implement broker-owned interactive login**

Set `LOGIN_IN_PROGRESS` before waiting for the operation lock. New Gmail
requests must fail fast with that code instead of waiting behind a five-minute
login. Under the lock: close headless, launch headful, poll authenticated
state, close headful, and always restore headless Edge in `finally`.

Add regression tests for success, timeout, cancellation, browser crash, and
early browser-window close. Perform one verification probe and return success
only when that probe is authenticated.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m unittest tests.test_gmail_edge_adapter -v
git add tools/gmail/gmail_edge_broker.py tests/test_gmail_edge_adapter.py
git commit -m "feat(gmail): connect broker to managed Edge"
```

### Task 7: Add Broker Control CLI

**Files:**
- Create: `tools/gmail/gmail_brokerctl.py`
- Create: `tests/test_gmail_brokerctl.py`

- [ ] **Step 1: Write failing CLI dispatch tests**

Mock `BrokerClient`; verify status, diagnostics, login, start, and stop call only their corresponding broker methods and emit sanitized JSON.

- [ ] **Step 2: Implement commands**

```powershell
python tools/gmail/gmail_brokerctl.py status
python tools/gmail/gmail_brokerctl.py login
python tools/gmail/gmail_brokerctl.py diagnostics
python tools/gmail/gmail_brokerctl.py stop
```

- [ ] **Step 3: Run tests and commit**

```powershell
python -m unittest tests.test_gmail_brokerctl -v
git add tools/gmail/gmail_brokerctl.py tests/test_gmail_brokerctl.py
git commit -m "feat(gmail): add broker control CLI"
```

### Task 8: Migrate Gmail MCP with Explicit Legacy Rollback

**Files:**
- Create: `tools/gmail/gmail_legacy_backend.py`
- Modify: `tools/gmail/gmail_mcp_server.py`
- Create: `tests/test_gmail_mcp_backend.py`

- [ ] **Step 1: Freeze legacy behavior in tests**

Move the existing query function without semantic changes. Test backend selection:

- default `edge_broker`;
- explicit `legacy_playwright`;
- unknown value rejected;
- broker errors become explicit text and never login HTML;
- tool names and input schemas remain unchanged.
- direct CLI modes `search`, `read`, and `send` route through the selected backend;
- stdio initialization behavior remains unchanged.

- [ ] **Step 2: Implement thin broker adapter**

```python
BACKEND = os.getenv("GMAIL_BACKEND", "edge_broker")

async def query_backend(method: str, params: dict[str, str]) -> str:
    if BACKEND == "edge_broker":
        return await asyncio.to_thread(BrokerClient().request, method, params)
    if BACKEND == "legacy_playwright":
        return await legacy_query(method, params)
    raise RuntimeError(f"Unsupported GMAIL_BACKEND: {BACKEND}")
```

Do not automatically fall back after an error.

- [ ] **Step 3: Run focused and existing contract tests**

```powershell
python -m unittest tests.test_gmail_mcp_backend tests.test_case_review_contract -v
```

- [ ] **Step 4: Commit**

```powershell
git add tools/gmail/gmail_legacy_backend.py tools/gmail/gmail_mcp_server.py tests/test_gmail_mcp_backend.py
git commit -m "feat(gmail): route MCP through Edge broker"
```

### Task 9: Update Installer and Deployment

**Files:**
- Modify: `setup_env.ps1`
- Create: `tests/test_setup_env_gmail_broker.py`
- Create: `tests/fixtures/run_setup_config_migration.ps1`

- [ ] **Step 1: Write failing installer contract tests**

Assert the installer:

- gracefully stops and waits for any running broker before file replacement;
- deploys an explicit script allowlist and never wildcard-copies profiles or runtime state;
- preserves byte-for-byte legacy and Edge profile baselines;
- preserves unrelated MCP servers and existing Gmail keys under Windows
  PowerShell 5.1;
- sets `GMAIL_BACKEND=edge_broker`;
- creates the state directory and ACL;
- invokes broker status and login only on exit code 10;
- verifies the running `build_id` matches installed source.

- [ ] **Step 2: Implement installer changes**

Keep Chromium installation for legacy rollback. Replace unconditional SSO bootstrap with:

```powershell
python $BrokerCtlPath status
if ($LASTEXITCODE -eq 10) {
    python $BrokerCtlPath login
} elseif ($LASTEXITCODE -ne 0) {
    Write-Warning "Gmail broker is not ready; legacy rollback remains available."
}
```

Set MCP environment:

```powershell
$ExistingConfig["mcpServers"]["gmail"]["env"] = @{
    "GMAIL_BACKEND" = "edge_broker"
}
```

Replace `ConvertFrom-Json -AsHashtable` with a Windows PowerShell 5.1-safe
PSCustomObject update helper using `Add-Member` when properties are absent.
Before copying, run brokerctl stop and wait for broker/Edge exit. Copy only the
named Python modules in the release manifest; never copy `chrome_profile`,
`edge_poc_profile`, `edge_broker_profile`, cache, state, or log folders.

- [ ] **Step 3: Validate PowerShell parsing and tests**

```powershell
powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './setup_env.ps1'),[ref]$null)|Out-Null"
powershell.exe -NoProfile -File tests/fixtures/run_setup_config_migration.ps1
python -m unittest tests.test_setup_env_gmail_broker -v
```

- [ ] **Step 4: Commit**

```powershell
git add setup_env.ps1 tests/test_setup_env_gmail_broker.py
git commit -m "feat(setup): deploy Gmail Edge broker"
```

### Task 10: Documentation and Release Notes

**Files:**
- Modify: `README.md`
- Modify: `README.html`
- Modify: `docs/MANAGER_ONBOARDING_GUIDE.md`
- Modify: `docs/MANAGER_ONBOARDING_GUIDE.html`
- Modify: `docs/TECHNICAL_DESIGN_DOCUMENT.md`
- Modify: `docs/TECHNICAL_DESIGN_DOCUMENT.html`
- Modify: `docs/RELEASE_NOTES.md`
- Modify: `docs/RELEASE_NOTES.html`
- Create: `docs/GMAIL_EDGE_BROKER.md`
- Create: `release-manifest.txt`
- Modify: `AGENTS.md`

- [ ] **Step 1: Document broker operation**

Cover architecture, status/login/diagnostics, lazy start, idle shutdown, sanitized logging, state/profile paths, backend rollback, and troubleshooting.

- [ ] **Step 2: Synchronize MD/HTML**

Replace Playwright-per-request production descriptions with broker architecture while keeping v1.5.0 history unchanged.

- [ ] **Step 3: Add an Unreleased release-note entry**

Describe single broker ownership, multi-MCP concurrency, structured auth errors, and legacy rollback.

- [ ] **Step 4: Run link/HTML/contract validation**

```powershell
python -m unittest tests.test_case_review_contract -v
git diff --check
```

- [ ] **Step 5: Add and validate the release manifest**

Create a tracked manifest containing all v1.5.0 distribution files plus every
new broker/common/client/control/legacy module and
`docs/GMAIL_EDGE_BROKER.md`. Update AGENTS.md release commands to build from
this manifest rather than the previous ZIP list. Add a test that builds a clean
temporary ZIP, extracts it, and runs broker/client/MCP import/help checks from
the extracted tree.

- [ ] **Step 6: Commit**

```powershell
git add README.md README.html AGENTS.md release-manifest.txt docs/MANAGER_ONBOARDING_GUIDE.md docs/MANAGER_ONBOARDING_GUIDE.html docs/TECHNICAL_DESIGN_DOCUMENT.md docs/TECHNICAL_DESIGN_DOCUMENT.html docs/RELEASE_NOTES.md docs/RELEASE_NOTES.html docs/GMAIL_EDGE_BROKER.md
git commit -m "docs(gmail): document single Edge broker"
```

### Task 11: Four-Client Concurrency and Recovery Soak

**Files:**
- Create: `tests/test_gmail_broker_soak.py`
- Modify after results: `docs/GMAIL_EDGE_BROKER.md`

- [ ] **Step 1: Run fake-browser 4-client/20-request soak**

Assert one broker, one adapter, maximum concurrency one, 20 correlated successes, no unauthorized logs, and no profile lock errors.

Use representative fake-browser latency and assert all requests fit the
300-second queue, 60-second execution, and 370-second client deadlines. Send a
sentinel secret through success/error/timeout paths and assert it is absent
from captured logs.

- [ ] **Step 2: Deploy broker mode locally**

Back up current MCP configuration, deploy source modules, set broker mode, and authenticate `edge_broker_profile` through brokerctl.

- [ ] **Step 3: Start four actual MCP processes**

Send case-bounded requests concurrently and verify:

- one broker PID;
- one Edge root PID identified with
  `Get-CimInstance Win32_Process` and exact
  `--user-data-dir=<edge_broker_profile>` filtering;
- all responses complete;
- diagnostics report maximum browser concurrency one.

- [ ] **Step 4: Restart broker**

Stop broker, issue a new MCP request to lazy-start it, and confirm authentication persists.

- [ ] **Step 5: Validate rollback**

Set `GMAIL_BACKEND=legacy_playwright`, restart one MCP process, perform a read-only search, then restore broker mode. Do not send mail.

- [ ] **Step 6: Record evidence**

Document timestamps, process counts, request totals, auth states, and errors without queries or email content.

### Task 12: Full Verification and Completion

**Files:**
- Verify all modified files

- [ ] **Step 1: Run all tests**

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest discover -s tests -v
```

- [ ] **Step 2: Run syntax and installer checks**

```powershell
Get-ChildItem tools/gmail/*.py | ForEach-Object {
    python -m py_compile $_.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
powershell -NoProfile -Command "[PSParser]::Tokenize((Get-Content -Raw './setup_env.ps1'),[ref]$null)|Out-Null"
git diff --check
```

- [ ] **Step 3: Audit sensitive logging and browser ownership**

Run sentinel-secret integration tests across successful, rejected, timed-out,
and browser-error requests and assert the exact sentinel is absent from every
broker log. Review source matches for token/params/query/body/subject/sender/
recipient/cookie; only defensive redaction, tests, or documentation may remain.
Verify one Edge root with the exact profile command-line filter.

- [ ] **Step 4: Confirm acceptance criteria**

Record pass/fail for four MCP processes, 20 requests, one broker, one Edge owner, max concurrency one, restart persistence, structured auth failure, installer conditional login, and legacy rollback.

- [ ] **Step 5: Commit final test evidence**

```powershell
git add tests/test_gmail_broker_soak.py docs/GMAIL_EDGE_BROKER.md docs/superpowers/plans/2026-08-03-single-edge-broker.md docs/superpowers/specs/2026-08-03-single-edge-broker-design.md
git commit -m "test(gmail): verify single Edge broker migration"
```

Do not push or publish a release without explicit user authorization.
