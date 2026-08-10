# Agent Installation Contract

This repository supports **Codex** and **Antigravity**. Claude Code is not an installation target.

When a user says:

```text
install this plugin: https://github.com/avayahmao/avaya-case-review-pack
```

the agent should complete the applicable flow below. Do not execute a remote script directly. Clone the repository, inspect this file and the installer, then run the local entry point.

## Mandatory cloud gate

Before either local installation, deploy and verify the existing Gmail Apps Script Web App by following [`docs/GMAIL_CLOUD_BRIDGE.md`](docs/GMAIL_CLOUD_BRIDGE.md). The Advanced Gmail Service must be named **Gmail**, API version **v1**. Do not activate the local skill if the snapshot, pagination, cursor, manifest, count, or hash checks fail.

This step may require the user to complete Google/Microsoft authorization. An agent must pause for that interaction and must not claim the gate passed without the documented evidence.

## Safe checkout

Use a unique temporary directory so an existing checkout is never overwritten:

```powershell
$Checkout = Join-Path ([IO.Path]::GetTempPath()) ("avaya-case-review-pack-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 https://github.com/avayahmao/avaya-case-review-pack $Checkout
Set-Location $Checkout
```

## Codex installation

After the cloud gate passes, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-codex.ps1 -CloudBridgeVerified
```

The installer performs the supported Codex sequence:

```powershell
codex plugin marketplace add https://github.com/avayahmao/avaya-case-review-pack --ref main
codex plugin add avaya-case-review@avaya-case-review-pack
```

It also installs the required Python packages and completes the shared Managed Edge Gmail login when required. Use `-IncludeLegacyChromium` only when the explicit one-release `legacy_playwright` rollback runtime is required.

Verify with:

```powershell
codex plugin list --json
python .\tools\gmail\gmail_brokerctl.py status
```

The plugin list must contain `avaya-case-review@avaya-case-review-pack`, and broker status must succeed without exposing credentials. Start a new Codex task after installation.

## Antigravity installation

After the same cloud gate passes, run:

```powershell
.\install.bat
```

The installer deploys the plugin and MCP tools under `%USERPROFILE%\.gemini\`, preserves unrelated MCP configuration, and opens Managed Edge for SSO/MFA only when required. Restart Antigravity after installation.

Verify that these files exist and that the broker status succeeds:

```powershell
Test-Path "$env:USERPROFILE\.gemini\config\plugins\avaya-case-review\plugin.json"
Test-Path "$env:USERPROFILE\.gemini\config\mcp_config.json"
python "$env:USERPROFILE\.gemini\tools\gmail\gmail_brokerctl.py" status
```

## Completion criteria

Installation is complete only when:

1. The Gmail cloud bridge verification passed.
2. The selected host reports the plugin installed.
3. Both CaseToMD and Gmail MCP definitions are present.
4. The Gmail broker is healthy or the required interactive login completed.
5. The user was told to start a new Codex task or restart Antigravity.
