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

## Stable v1.11.0 bootstrap

Create a unique temporary directory and use this exact stable clone command:

```text
git clone --depth 1 --branch v1.11.0 https://github.com/avayahmao/avaya-case-review-pack <unique-temp-directory>
```

In that checkout, run `git describe --exact-match --tags HEAD` and require the
exact output `v1.11.0`. Inspect this `INSTALL.md` and the selected installer
before running any local script. If the exact tag cannot be resolved or
verified, stop without installing. These instructions are the release contract
published by this commit; they do not assert that the tag, GitHub release,
release asset, or URL-only acceptance run has already succeeded.

## Codex installation

Run the checked-out no-flag `install-codex.ps1` installer. It installs the
runtime package, performs local release-attestation and live Gmail cloud
compatibility checks, refreshes the marketplace at the immutable release tag,
installs `avaya-case-review@avaya-case-review-pack`, and verifies
both MCP definitions. It may pause only for Managed Edge SSO/MFA. End users do not deploy Apps Script or provide a production Case ID.
Start a new Codex task after installation.

## Antigravity installation

Run the checked-out no-flag `install.bat` installer. It performs the same local
attestation and live compatibility checks, deploys the plugin and MCP tools
under `%USERPROFILE%\.gemini\`, preserves unrelated MCP configuration, and
opens Managed Edge for SSO/MFA only when required. It does not deploy the Gmail
cloud source or require a production Case ID. Restart Antigravity after
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
