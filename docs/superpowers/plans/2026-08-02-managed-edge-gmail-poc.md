# Managed Edge Gmail Authentication PoC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run an isolated Managed Edge CLI that measures whether enterprise Gmail Apps Script authentication survives repeated requests and process restarts without changing the production Gmail MCP.

**Architecture:** A standalone asynchronous Playwright CLI launches installed Edge with a dedicated PoC profile, classifies authentication state from non-sensitive response metadata, and exposes `status`, `login`, and `repeat` commands. Pure classification, path-safety, exit-code, and summary functions are unit tested; browser/network checks are explicit PoC experiments.

**Tech Stack:** Python 3.14, Playwright async API, Microsoft Edge channel, `unittest`, argparse, JSON diagnostics.

---

## File Responsibilities

- Create `tools/gmail/gmail_edge_poc.py`: isolated classifier, Edge session, CLI, and safe diagnostic output.
- Create `tests/test_gmail_edge_poc.py`: pure unit tests with no browser or network dependency.
- Create `docs/GMAIL_EDGE_POC.md`: operator runbook, experiment sequence, exit codes, and cleanup guidance.
- Modify `docs/superpowers/specs/2026-08-02-managed-edge-gmail-poc-design.md`: mark implemented and record experiment outcome.
- Modify this plan: mark completed steps.

### Task 1: Lock Authentication Classification and Safety with Failing Tests

**Files:**
- Create: `tests/test_gmail_edge_poc.py`
- Create later: `tools/gmail/gmail_edge_poc.py`

- [x] **Step 1: Write classifier and exit-code tests**

```python
from tools.gmail.gmail_edge_poc import AuthState, classify_response, exit_code_for

def test_classifies_microsoft_saml():
    state = classify_response(
        "https://login.microsoftonline.com/tenant/saml2",
        200,
        "<html>Sign in</html>",
    )
    assert state is AuthState.AUTH_REQUIRED_MICROSOFT

def test_classifies_google_login():
    state = classify_response(
        "https://accounts.google.com/v3/signin/identifier",
        200,
        "<html>Sign in</html>",
    )
    assert state is AuthState.AUTH_REQUIRED_GOOGLE

def test_classifies_apps_script_json():
    state = classify_response(
        "https://script.googleusercontent.com/macros/echo",
        200,
        '{"status":"success","messages":[]}',
    )
    assert state is AuthState.AUTHENTICATED

def test_maps_auth_required_to_exit_10():
    assert exit_code_for(AuthState.AUTH_REQUIRED_MICROSOFT) == 10
    assert exit_code_for(AuthState.AUTH_REQUIRED_GOOGLE) == 10
```

- [x] **Step 2: Write path-isolation and redaction tests**

```python
from pathlib import Path
import unittest
from tools.gmail.gmail_edge_poc import AuthState, ProbeResult, validate_profile_path

class PathAndRedactionTests(unittest.TestCase):
  def test_rejects_production_chrome_profile(self):
    with self.assertRaises(ValueError):
        validate_profile_path(
            Path(r"C:\Users\tester\.gemini\tools\gmail\chrome_profile"),
            Path(r"C:\Users\tester"),
        )

  def test_public_result_contains_no_sensitive_body(self):
    result = ProbeResult(
        state=AuthState.AUTHENTICATED,
        http_status=200,
        final_host="script.googleusercontent.com",
        final_path="/macros/echo",
        body_length=123,
        elapsed_ms=50,
    ).to_public_dict()
    assert set(result) == {
        "state", "http_status", "final_host", "final_path",
        "body_length", "elapsed_ms"
    }
    assert "body" not in result
    assert "cookie" not in result
    assert "token" not in result
```

- [x] **Step 3: Write repeat-summary test**

```python
def test_repeat_summary_counts_states_and_marks_context_reuse():
    summary = summarize_results([
        ProbeResult(AuthState.AUTHENTICATED, 200, "script.googleusercontent.com", "/a", 2, 10),
        ProbeResult(AuthState.AUTHENTICATED, 200, "script.googleusercontent.com", "/b", 2, 11),
    ])
    assert summary["total"] == 2
    assert summary["authenticated"] == 2
    assert summary["context_reused"] is True
```

- [x] **Step 4: Run tests and verify RED**

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_gmail_edge_poc -v
```

Expected: import failure because `gmail_edge_poc.py` does not exist.

### Task 2: Implement the Pure PoC Contract

**Files:**
- Create: `tools/gmail/gmail_edge_poc.py`
- Test: `tests/test_gmail_edge_poc.py`

- [x] **Step 1: Add states, safe result model, and classifier**

```python
class AuthState(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    AUTH_REQUIRED_MICROSOFT = "AUTH_REQUIRED_MICROSOFT"
    AUTH_REQUIRED_GOOGLE = "AUTH_REQUIRED_GOOGLE"
    APP_ERROR = "APP_ERROR"
    BROWSER_ERROR = "BROWSER_ERROR"
    UNKNOWN = "UNKNOWN"

def classify_response(final_url: str, http_status: int | None, body: str) -> AuthState:
    host = urlparse(final_url).netloc.lower()
    lower = body[:1000].lower()
    if host == "login.microsoftonline.com" or "/saml2" in final_url.lower():
        return AuthState.AUTH_REQUIRED_MICROSOFT
    if host == "accounts.google.com" or "servicelogin" in final_url.lower():
        return AuthState.AUTH_REQUIRED_GOOGLE
    if http_status and http_status >= 400:
        return AuthState.APP_ERROR
    if host.endswith("script.googleusercontent.com") or (
        host.endswith("script.google.com") and body.lstrip().startswith(("{", "["))
    ):
        return AuthState.APP_ERROR if '"status":"error"' in body.replace(" ", "").lower() else AuthState.AUTHENTICATED
    if "sign in" in lower:
        return AuthState.AUTH_REQUIRED_GOOGLE
    return AuthState.UNKNOWN
```

- [x] **Step 2: Add profile-path guard**

```python
def validate_profile_path(profile: Path, user_home: Path) -> Path:
    resolved = profile.expanduser().resolve()
    forbidden = {
        (user_home / ".gemini/tools/gmail/chrome_profile").resolve(),
        (user_home / "AppData/Local/Microsoft/Edge/User Data").resolve(),
    }
    if resolved in forbidden or any(parent in forbidden for parent in resolved.parents):
        raise ValueError("PoC profile must not use a production or normal Edge profile")
    return resolved
```

- [x] **Step 3: Add result and summary helpers**

Implement `ProbeResult.to_public_dict()`, `exit_code_for()`, and `summarize_results()` so output contains only approved diagnostic fields.

- [x] **Step 4: Run tests and verify GREEN**

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_gmail_edge_poc -v
```

Expected: all pure-contract tests pass.

### Task 3: Implement Managed Edge Commands

**Files:**
- Modify: `tools/gmail/gmail_edge_poc.py`
- Test: `tests/test_gmail_edge_poc.py`

- [x] **Step 1: Implement one-context probe session**

Create `ManagedEdgeSession` using:

```python
self._playwright = await async_playwright().start()
self._context = await self._playwright.chromium.launch_persistent_context(
    channel="msedge",
    user_data_dir=str(self.profile_dir),
    headless=self.headless,
)
```

Use one `asyncio.Lock` and a new page per probe. Wait for `networkidle`, classify the final response, and never expose body text outside the local method.

- [x] **Step 2: Implement `status`**

Launch one headless session, execute one probe, print `ProbeResult.to_public_dict()` as JSON, and return `exit_code_for(result.state)`.

- [x] **Step 3: Implement `repeat --count N`**

Validate `1 <= N <= 20`. Reuse one session for all probes and print `summarize_results()`.

- [x] **Step 4: Implement `login`**

Launch Edge headful, navigate to the probe URL, and poll for up to 300 seconds. Return success only after classification becomes `AUTHENTICATED`; return exit 10 on timeout or closed window.

- [x] **Step 5: Add argparse and import check**

```powershell
python -m py_compile tools/gmail/gmail_edge_poc.py
python tools/gmail/gmail_edge_poc.py --help
```

Expected: exit 0 and commands `status`, `login`, and `repeat` are listed.

### Task 4: Add the PoC Runbook

**Files:**
- Create: `docs/GMAIL_EDGE_POC.md`

- [x] **Step 1: Document safety boundary**

State that the PoC does not change production scripts, uses `edge_poc_profile`, does not print Gmail bodies, and may still be blocked by Conditional Access.

- [x] **Step 2: Document commands and exit codes**

```powershell
python tools/gmail/gmail_edge_poc.py status
python tools/gmail/gmail_edge_poc.py login
python tools/gmail/gmail_edge_poc.py repeat --count 5
```

Document exit codes 0, 10, 20, and 30.

- [x] **Step 3: Document success and failure criteria**

Include the exact experiment sequence from the approved design and instructions to preserve the production profile.

### Task 5: Offline Verification

**Files:**
- Verify all PoC files

- [x] **Step 1: Run PoC tests and existing contract tests**

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_gmail_edge_poc tests.test_case_review_contract -v
```

Expected: all tests pass.

- [x] **Step 2: Run syntax and whitespace checks**

```powershell
python -m py_compile tools/gmail/gmail_edge_poc.py
git diff --check
```

Expected: both exit 0.

- [x] **Step 3: Record production profile baselines**

Record size, last-write timestamp, and SHA-256 for production `Default/Preferences` and `Default/Network/Cookies`, plus equivalent non-sensitive metadata for normal Edge. Do not print cookies or account identifiers.

### Task 6: Execute the Live PoC

**Files:**
- Modify after experiment: `docs/GMAIL_EDGE_POC.md`
- Modify after experiment: `docs/superpowers/specs/2026-08-02-managed-edge-gmail-poc-design.md`

- [x] **Step 1: Run initial status**

```powershell
python tools/gmail/gmail_edge_poc.py status
```

Expected: `AUTHENTICATED` or a precise authentication-required state.

- [x] **Step 2: Pause for one user interaction if required**

If exit code is 10, run `login` in a visible browser and ask the user to complete SSO/MFA. Do not proceed unattended.

- [x] **Step 3: Run persistence sequence**

Run two standalone status commands, `repeat --count 5`, then one final standalone status.

- [x] **Step 4: Compare production profile baselines**

Confirm production Chromium and normal Edge profile baseline files did not change because of the PoC.

- [x] **Step 5: Record the result**

Update the runbook and spec with timestamps, classifications, counts, and final conclusion. Never include account identifiers, cookies, tokens, or message content.

### Task 7: Final Verification and Commit

**Files:**
- Verify all modified files

- [x] **Step 1: Run the complete test suite**

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONDONTWRITEBYTECODE='1'
python -m unittest tests.test_gmail_edge_poc tests.test_case_review_contract -v
```

- [x] **Step 2: Confirm production code is unchanged**

```powershell
git diff --name-only HEAD -- setup_env.ps1 tools/gmail/gmail_mcp_server.py tools/gmail/gmail_playwright.py
```

Expected: no output.

- [x] **Step 3: Commit completed PoC**

```powershell
git add tools/gmail/gmail_edge_poc.py tests/test_gmail_edge_poc.py docs/GMAIL_EDGE_POC.md docs/superpowers/specs/2026-08-02-managed-edge-gmail-poc-design.md docs/superpowers/plans/2026-08-02-managed-edge-gmail-poc.md
git commit -m "test(gmail): add managed Edge authentication PoC"
```

Do not push or modify the production MCP without explicit user authorization.
