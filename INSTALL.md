# Agent Installation Contract

This repository supports **Codex** and **Antigravity**. Claude Code is not an installation target.
It is a Codex plugin marketplace, not a standalone skill. Do not use a skill
installer or search for a root `SKILL.md`; the repository root is the plugin
selected by its marketplace manifest.

When a user says:

```text
install this plugin: https://github.com/avayahmao/avaya-case-review-pack
```

the agent should complete the applicable flow below. Do not execute a remote
script directly. Clone the published stable tag, inspect this file and the
selected installer, then run the local entry point.

## Stable release checkout

Install **v1.10.1**, not `main`, a branch, or an arbitrary commit. Use a unique
temporary directory so an existing checkout is never overwritten:

```powershell
$Checkout = Join-Path ([IO.Path]::GetTempPath()) ("avaya-case-review-pack-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 --branch v1.10.1 https://github.com/avayahmao/avaya-case-review-pack $Checkout
Set-Location $Checkout
if ((git describe --exact-match --tags HEAD) -ne "v1.10.1") { throw "Expected the v1.10.1 release tag." }
```

If the tag cannot be fetched or verified, stop with an actionable error; do not
fall back to `main`.

## Codex installation

Run the checked-out installer with no cloud-verification flag:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-codex.ps1
```

The installer installs the runtime package, performs local release-attestation
and live Gmail cloud compatibility checks, refreshes the marketplace at the
immutable release tag, installs `avaya-case-review@avaya-case-review-pack`,
and verifies both MCP definitions. It may pause only for Managed Edge SSO/MFA.
It does not require an end user to deploy Apps Script. Start a new Codex task
after installation.

## Antigravity installation

Run the checked-out installer:

```powershell
.\install.bat
```

The installer performs the same local attestation and live compatibility checks,
deploys the plugin and MCP tools under `%USERPROFILE%\.gemini\`, preserves
unrelated MCP configuration, and opens Managed Edge for SSO/MFA only when
required. It does not deploy the Gmail cloud source. Restart Antigravity after
installation.

Verify that these files exist and that the broker status succeeds:

```powershell
Test-Path "$env:USERPROFILE\.gemini\config\plugins\avaya-case-review\plugin.json"
Test-Path "$env:USERPROFILE\.gemini\config\mcp_config.json"
python "$env:USERPROFILE\.gemini\tools\gmail\gmail_brokerctl.py" status
```

## Completion criteria

Installation is complete only when:

1. The installer passed its local attestation and live Gmail cloud compatibility checks.
2. The selected host reports the plugin installed.
3. Both CaseToMD and Gmail MCP definitions are present.
4. The Gmail broker is healthy or the required interactive login completed.
5. The user was told to start a new Codex task or restart Antigravity.
