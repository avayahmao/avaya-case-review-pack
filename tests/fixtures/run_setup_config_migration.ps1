$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SetupScript = Join-Path $RepoRoot "setup_env.ps1"
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("avaya-setup-config-" + [guid]::NewGuid().ToString("N"))
$ConfigPath = Join-Path $TempRoot "mcp_config.json"

$SetupSource = Get-Content -LiteralPath $SetupScript -Raw -Encoding UTF8
if ($SetupSource -notmatch "ConfigMigrationOnly") {
    throw "setup_env.ps1 does not expose the config migration test entry point."
}
$ManifestMatch = [regex]::Match(
    $SetupSource,
    '(?s)\$GmailDeploymentFiles\s*=\s*@\((?<body>.*?)\r?\n\)'
)
if (-not $ManifestMatch.Success) {
    throw "Gmail deployment allowlist was not found."
}
Invoke-Expression ("`$ExecutedGmailDeploymentFiles = @(" + $ManifestMatch.Groups["body"].Value + "`n)")
if (@($ExecutedGmailDeploymentFiles).Count -ne 10) {
    throw "Gmail deployment allowlist did not execute as ten entries."
}

try {
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    @'
{
  "top_level_key": "keep-top-level",
  "mcpServers": {
    "unrelated": {
      "command": "node",
      "args": ["server.js"],
      "env": {"KEEP_UNRELATED": "yes"}
    },
    "gmail": {
      "command": "old-python",
      "args": ["old-gmail.py"],
      "disabled": true,
      "custom_key": "keep-gmail",
      "env": {
        "KEEP_GMAIL_ENV": "yes",
        "GMAIL_BACKEND": "legacy_playwright"
      }
    },
    "CaseToMD": {
      "command": "old-python",
      "args": ["old-case.py"],
      "custom_case_key": "keep-case"
    }
  }
}
'@ | Set-Content -LiteralPath $ConfigPath -Encoding UTF8

    . $SetupScript `
        -ConfigMigrationOnly `
        -ConfigMigrationPath $ConfigPath `
        -ConfigMigrationGmailScript "C:/deployed/gmail_mcp_server.py" `
        -ConfigMigrationCaseToMdScript "C:/deployed/casetomd_mcp_bridge.py"

    $Updated = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Updated.top_level_key -ne "keep-top-level") {
        throw "Top-level config key was not preserved."
    }
    if ($Updated.mcpServers.unrelated.env.KEEP_UNRELATED -ne "yes") {
        throw "Unrelated MCP server was not preserved."
    }
    if ($Updated.mcpServers.gmail.disabled -ne $true -or $Updated.mcpServers.gmail.custom_key -ne "keep-gmail") {
        throw "Existing Gmail keys were not preserved."
    }
    if ($Updated.mcpServers.gmail.env.KEEP_GMAIL_ENV -ne "yes") {
        throw "Existing Gmail environment was not preserved."
    }
    if ($Updated.mcpServers.gmail.env.GMAIL_BACKEND -ne "edge_broker") {
        throw "Gmail backend was not migrated."
    }
    if ($Updated.mcpServers.gmail.command -ne "python") {
        throw "Gmail command was not updated."
    }
    if ($Updated.mcpServers.gmail.args[0] -ne "C:/deployed/gmail_mcp_server.py") {
        throw "Gmail script path was not updated."
    }
    if ($Updated.mcpServers.CaseToMD.custom_case_key -ne "keep-case") {
        throw "Existing CaseToMD keys were not preserved."
    }

    $ProfilePath = Join-Path $TempRoot "profile"
    New-Item -ItemType Directory -Path $ProfilePath -Force | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $ProfilePath "sentinel.bin"), [byte[]](1, 2, 3, 4))
    $ProfileBefore = Get-ProfileBaseline -Path $ProfilePath
    $ProfileAfter = Get-ProfileBaseline -Path $ProfilePath
    Assert-ProfileBaselineUnchanged `
        -Name "fixture profile" `
        -Before $ProfileBefore `
        -After $ProfileAfter

    $BuildId = Get-InstalledBrokerBuildId `
        -BrokerScriptPath (Join-Path $RepoRoot "tools\gmail\gmail_edge_broker.py")
    if ($BuildId -ne "source") {
        throw "Installed broker build ID extraction failed."
    }

    $StaleStateFile = Join-Path $TempRoot "stale-state.json"
    '{"pid":2147483647}' | Set-Content -LiteralPath $StaleStateFile -Encoding UTF8
    Wait-GmailBrokerExit `
        -BrokerProcessId 2147483647 `
        -StateFile $StaleStateFile `
        -EdgeProfileDir (Join-Path $TempRoot "unused-edge-profile") `
        -TimeoutSeconds 1

    [ordered]@{
        result = "CONFIG_MIGRATION_OK"
        unrelated_server_preserved = $true
        gmail_keys_preserved = $true
        gmail_env_preserved = $true
        backend = $Updated.mcpServers.gmail.env.GMAIL_BACKEND
        profile_baseline_verified = $true
        build_id = $BuildId
        stale_state_ignored = $true
        deployment_allowlist_count = @($ExecutedGmailDeploymentFiles).Count
    } | ConvertTo-Json -Compress
} finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
