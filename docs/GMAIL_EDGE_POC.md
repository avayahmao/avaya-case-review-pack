# Managed Edge Gmail Authentication PoC

This PoC checks whether installed Microsoft Edge can preserve the enterprise SSO session used by the Gmail Apps Script endpoint.

It does not replace the production Gmail MCP.

## Safety Boundary

- Uses `%USERPROFILE%\.gemini\tools\gmail\edge_poc_profile`.
- Does not use or modify production `chrome_profile`.
- Does not use the normal Edge `User Data\Default` profile.
- Uses a deliberately nonexistent Gmail search subject.
- Does not print response bodies, message metadata, account identifiers, cookies, or tokens.
- Does not send email.
- Does not bypass MFA or Conditional Access.

## Requirements

- Windows 10 or 11.
- Microsoft Edge installed.
- Python Playwright package installed.
- Network access to the Avaya Google Apps Script deployment.

## Commands

Run from the repository root.

### Check authentication state

```powershell
python tools/gmail/gmail_edge_poc.py status
```

### Complete one interactive login

```powershell
python tools/gmail/gmail_edge_poc.py login
```

Complete corporate SSO/MFA in the dedicated Edge window. The command reports success only after the Apps Script response is reached.

### Check repeated requests through one Edge context

```powershell
python tools/gmail/gmail_edge_poc.py repeat --count 5
```

The count must be between 1 and 20.

## Exit Codes

| Exit | Meaning |
|---|---|
| 0 | Authenticated Apps Script response |
| 10 | Microsoft or Google interactive authentication required |
| 20 | Edge/Playwright runtime failure |
| 30 | Apps Script error or unknown response |

## Diagnostic Output

The CLI emits JSON containing only:

- authentication state;
- HTTP status;
- final hostname and path;
- response length;
- elapsed time;
- repeat counts and per-probe safe metadata.

Response bodies are used only in memory for classification and are never emitted.

## Experiment Sequence

1. Run `status`.
2. If exit code is 10, run `login` and complete SSO/MFA once.
3. Run `status` twice in separate processes.
4. Run `repeat --count 5`.
5. Run one final `status` after the repeat process exits.
6. Compare production profile baselines to confirm they did not change.

## Success Criteria

- Login reaches `AUTHENTICATED`.
- Two standalone status checks remain authenticated.
- Five repeated probes remain authenticated through one context.
- A final post-restart status check remains authenticated.
- Production Chromium and normal Edge profiles remain unchanged.

## Failure Interpretation

- Repeated `AUTH_REQUIRED_MICROSOFT` after a successful login indicates that Conditional Access or enterprise session policy does not permit persistent headless use of this dedicated Edge profile.
- Repeated `AUTH_REQUIRED_GOOGLE` indicates the Google session is not retained or accepted.
- `BROWSER_ERROR` indicates Edge launch/runtime failure.
- `APP_ERROR` indicates the Apps Script endpoint responded but the application action failed.

A failed PoC is a valid result. It means this browser approach should not replace production authentication without an administrator-supported identity method.

## Cleanup

The PoC profile is sensitive. If cleanup is required, close all PoC Edge processes first, then remove only:

`%USERPROFILE%\.gemini\tools\gmail\edge_poc_profile`

Never remove `chrome_profile` or the normal Edge profile.

## PoC Result

**Date:** 2026-08-03
**Result:** Successful authentication persistence in the isolated Edge profile.

Observed sequence:

1. Initial headless status returned `AUTH_REQUIRED_MICROSOFT` at
   `avaya365-onmicrosoft-com.access.mcas.ms/aad_login`.
2. One interactive corporate SSO/MFA login was completed in the dedicated Edge profile.
3. The login window was closed before the CLI could report success, but the session was saved.
4. Two subsequent standalone status processes both returned `AUTHENTICATED`.
5. `repeat --count 5` returned five authenticated probes, zero authentication requests, and zero errors while reusing one context.
6. A final standalone status after process restart returned `AUTHENTICATED`.
7. A controlled before/after hash window confirmed that production Chromium Preferences/Cookies and normal Edge Local State/Preferences were unchanged by a PoC status request.

All successful probes reached `script.googleusercontent.com/a/macros/avaya.com/echo` with HTTP 200. Response bodies and account data were not printed.

Conclusion: Managed Edge with the isolated profile can retain the enterprise session across repeated requests and process restarts on this workstation. This validates the authentication premise only; production migration still requires a shared-browser or cross-process ownership design.
