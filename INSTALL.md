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

## Release-preparation status

`v1.10.1` is an **unreleased release candidate**. Do not clone a presumed
`v1.10.1` tag or run the candidate as a URL-only installation. `v1.10.0`
remains the latest published release. URL-only stable installation becomes
active only after maintainers complete the cloud attestation, create the
immutable `v1.10.1` tag, and publish the release. The published bootstrap will
then require a unique temporary checkout and exact-tag verification before any
local script runs.

## Codex installation

After the release gate, the checked-out no-flag `install-codex.ps1` installer
will install the runtime package, perform local release-attestation and live
Gmail cloud compatibility checks, refresh the marketplace at the immutable
release tag, install `avaya-case-review@avaya-case-review-pack`, and verify
both MCP definitions. It may pause only for Managed Edge SSO/MFA. It does not
require an end user to deploy Apps Script. Start a new Codex task after a
published installation.

## Antigravity installation

After the release gate, the checked-out `install.bat` installer will perform
the same local attestation and live compatibility checks, deploy the plugin and
MCP tools under `%USERPROFILE%\.gemini\`, preserve unrelated MCP configuration,
and open Managed Edge for SSO/MFA only when required. It does not deploy the
Gmail cloud source. Restart Antigravity after a published installation.

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
