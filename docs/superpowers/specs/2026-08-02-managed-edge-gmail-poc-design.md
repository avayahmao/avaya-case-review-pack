# Managed Edge Gmail Authentication PoC Design

**Date:** 2026-08-02
**Status:** Approved concept; written specification awaiting final review

## Context

The current Gmail MCP opens a fresh Playwright Chromium process for every request and relies on cookies stored in `chrome_profile`. Live probes show that the profile and cookies persist, but the Apps Script request still redirects to `login.microsoftonline.com/.../saml2`. The installer also opens an authentication window unconditionally.

An Avaya-approved Google OAuth Desktop Client is unavailable, so direct Gmail API refresh-token authentication cannot be deployed. The proposed alternative is to test whether installed, signed-in Microsoft Edge can use the workstation's enterprise identity more reliably than Playwright Chromium.

## Objective

Build an isolated proof of concept that determines whether a dedicated, managed Edge session can:

1. authenticate to the existing Gmail Apps Script endpoint;
2. reuse one long-lived browser context across repeated requests;
3. survive PoC process restart without another interactive sign-in;
4. distinguish authenticated responses from Microsoft/Google login redirects;
5. avoid touching the production Gmail MCP or the user's daily Edge profile.

## Non-Goals

- Do not replace `gmail_mcp_server.py` during the PoC.
- Do not modify `setup_env.ps1`, MCP registrations, or deployed runtime scripts.
- Do not read or print real email content.
- Do not send email.
- Do not use the user's normal Edge `Default` profile directly.
- Do not copy or export authentication cookies.
- Do not bypass MFA, Conditional Access, or corporate sign-in policy.
- Do not claim the approach is production-ready until restart and repeated-request tests pass.

## PoC Architecture

Create `tools/gmail/gmail_edge_poc.py` as a standalone diagnostic CLI.

### Browser

- Use Playwright with `channel="msedge"`.
- Use a dedicated profile at:
  `%USERPROFILE%\.gemini\tools\gmail\edge_poc_profile`
- Never use:
  - the user's normal Edge profile;
  - the existing production `chrome_profile`.
- Keep one persistent Edge context alive for the entire command.
- Serialize all page operations through one asynchronous lock.

### Probe Target

Use the existing Apps Script endpoint with a deliberately nonexistent Gmail query:

`subject:__avaya_gmail_edge_poc__`

The probe records only:

- launch result;
- HTTP status;
- final hostname and path;
- authentication-state classification;
- response length;
- elapsed time.

It must not print response bodies, message metadata, account identifiers, cookies, or tokens.

## Authentication-State Classifier

The classifier returns one of:

- `AUTHENTICATED`: response is an Apps Script application response.
- `AUTH_REQUIRED_MICROSOFT`: final URL is Microsoft login/SAML.
- `AUTH_REQUIRED_GOOGLE`: final URL is Google account login.
- `APP_ERROR`: Apps Script returns an application error.
- `BROWSER_ERROR`: Edge launch, navigation, or context failure.
- `UNKNOWN`: response cannot be classified safely.

Classification must be based on URL host/path, HTTP status, and limited non-sensitive structural markers. Login HTML must never be returned as Gmail data.

## CLI Commands

### `status`

Launch Edge headless with the dedicated profile, execute one probe, print a JSON diagnostic record, then close cleanly.

Exit codes:

- `0`: authenticated;
- `10`: interactive authentication required;
- `20`: browser/runtime error;
- `30`: application/unknown response.

### `login`

Launch Edge headful with the dedicated profile and navigate to the probe endpoint.

- Explain that the user should complete corporate SSO/MFA if prompted.
- Wait for the authenticated Apps Script response.
- Do not declare success merely because the browser window opened.
- Save the profile only after `AUTHENTICATED` is observed.
- Close the context cleanly.

### `repeat --count N`

Launch one headless persistent context and execute N sequential probes through the same context.

Default: `N=5`.

Report:

- total probes;
- authenticated count;
- authentication-required count;
- error count;
- whether one context was reused;
- per-probe elapsed time.

Do not print Gmail response content.

## Experiment Sequence

1. Run unit tests for classifier and CLI validation.
2. Run `status` against a new dedicated profile.
   - Expected first result: authentication required or silent enterprise authentication.
3. If required, run `login` and complete SSO/MFA once.
4. Run `status` twice in separate processes.
5. Run `repeat --count 5`.
6. Close the PoC process completely.
7. Run `status` again to validate persistence across restart.
8. Record final hostname, classification, timing, and whether another login was required.

## Success Criteria

The PoC succeeds only if:

- installed Edge launches through Playwright;
- interactive login reaches an authenticated Apps Script response;
- two subsequent standalone `status` runs return `AUTHENTICATED`;
- all five probes in one `repeat` run return `AUTHENTICATED`;
- the final post-restart status remains authenticated;
- no real email content, cookies, tokens, or account identifiers are printed;
- the existing production `chrome_profile` and normal Edge profile remain unchanged.

## Failure Criteria

The PoC fails if:

- Edge cannot launch with the dedicated profile;
- every new process requires SSO/MFA;
- headless Edge is consistently redirected to Microsoft or Google login after successful headful login;
- Conditional Access blocks the dedicated Edge profile;
- authentication persistence requires using the user's normal Edge profile;
- the probe exposes sensitive response content.

A failed PoC is still a valid result. It demonstrates that enterprise browser identity cannot replace an approved OAuth or policy change.

## Concurrency Boundary

The PoC validates one long-lived context in one process. It does not claim to solve the currently observed multiple-MCP-process problem.

If authentication persistence succeeds, the production design must choose one of:

- a single local Edge broker shared by MCP processes;
- explicit cross-process locking plus one active Gmail MCP owner.

That decision belongs to the production migration design, not this PoC.

## Security

- Store the dedicated profile only under the current user's `.gemini\tools\gmail` directory.
- Never commit the profile.
- Do not weaken Edge security flags or TLS validation.
- Do not expose a remote-debugging port in this PoC.
- Redact account identifiers from diagnostic output.
- Treat the dedicated profile as sensitive authentication material.

## Test Design

Create `tests/test_gmail_edge_poc.py` covering:

1. Microsoft login URL classification.
2. Google login URL classification.
3. Apps Script response classification.
4. Unknown/error classification.
5. Exit-code mapping.
6. Probe output excludes body, cookie, token, and account fields.
7. Repeat summary counts and context-reuse marker.
8. Profile path is dedicated and never resolves to production Chrome or normal Edge profile.

Browser and network tests remain explicit PoC commands rather than unit tests.

## Documentation Impact

During the PoC:

- add a short PoC runbook under `docs/`;
- do not change README claims or production Gmail architecture diagrams;
- record observed results as PoC evidence;
- do not update release version metadata.

If the PoC succeeds, create a separate production migration specification covering MCP lifecycle, multi-process ownership, installer changes, rollout, and fallback.

## Acceptance Criteria

The PoC implementation is complete when:

- classifier and CLI unit tests pass;
- `git diff --check` passes;
- Edge syntax/import checks pass;
- the isolated experiment sequence is executed or explicitly blocked awaiting one user SSO interaction;
- results clearly state success, failure, or the exact external policy blocker;
- no production Gmail MCP behavior has changed.
