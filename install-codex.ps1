# ==============================================================================
# Avaya Case Review Suite - Codex installer
# ==============================================================================

[CmdletBinding()]
param(
    [string]$MarketplaceSource = "https://github.com/avayahmao/avaya-case-review-pack",
    [string]$MarketplaceRef,
    [switch]$AllowUnreleasedRef,
    [switch]$CloudBridgeVerified,
    [switch]$SkipDependencyInstall,
    [switch]$SkipLogin,
    [switch]$IncludeLegacyChromium,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "tools\installer\windows_common.ps1")

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [switch]$AllowFailure
    )

    Write-Host "  $Description" -ForegroundColor Yellow
    Write-Host "  > $Stage" -ForegroundColor DarkGray
    if ($DryRun) {
        return [pscustomobject]@{
            Stage = $Stage
            ExitCode = 0
            TimedOut = $false
            StdOut = ""
            StdErr = ""
        }
    }

    return Invoke-BoundedCommand `
        -Stage $Stage `
        -Command $Command `
        -Arguments $Arguments `
        -TimeoutSeconds $TimeoutSeconds `
        -AllowFailure:$AllowFailure
}

function Normalize-GitSource {
    param([Parameter(Mandatory = $true)][string]$Value)

    $Normalized = $Value.Trim().TrimEnd('/')
    if ($Normalized.EndsWith('.git', [StringComparison]::OrdinalIgnoreCase)) {
        $Normalized = $Normalized.Substring(0, $Normalized.Length - 4)
    }
    return $Normalized.ToLowerInvariant()
}

function Test-LocalMarketplaceSource {
    param([Parameter(Mandatory = $true)][string]$Value)

    return Test-Path -LiteralPath $Value
}

function Normalize-LocalPath {
    param([Parameter(Mandatory = $true)][string]$Value)

    $Resolved = (Resolve-Path -LiteralPath $Value).Path
    if ($Resolved.StartsWith('\\?\', [StringComparison]::Ordinal)) {
        $Resolved = $Resolved.Substring(4)
    }
    return $Resolved.TrimEnd([char[]]@('\', '/'))
}

function ConvertFrom-CommandJson {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Result,
        [Parameter(Mandatory = $true)][string]$Stage
    )

    try {
        return $Result.StdOut | ConvertFrom-Json
    } catch {
        throw "Stage '$Stage' returned invalid JSON."
    }
}

function Test-VersionAtLeast {
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][version]$Minimum,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $Match = [regex]::Match($Actual, '(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)')
    if (-not $Match.Success) {
        throw "Stage '$Label version' returned an unrecognized version."
    }
    if ([version]$Match.Groups[1].Value -lt $Minimum) {
        throw "$Label $Minimum or newer is required."
    }
}

function Assert-ExactPropertyNames {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $Actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $Wanted = @($Expected | Sort-Object)
    if (@(Compare-Object -ReferenceObject $Wanted -DifferenceObject $Actual).Count -ne 0) {
        throw "Local bridge attestation $Label does not match the required contract."
    }
}

function Test-LocalBridgeAttestation {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$AttestationPath,
        [Parameter(Mandatory = $true)][string]$PluginVersion
    )

    try {
        $Utf8 = New-Object System.Text.UTF8Encoding($false)
        $Source = [IO.File]::ReadAllText($SourcePath, $Utf8).Replace("`r`n", "`n").Replace("`r", "`n")
        $IdentityPattern = '(?m)^var GMAIL_BRIDGE_SOURCE_SHA256 = "([0-9a-f]{64})";$'
        $IdentityMatches = [regex]::Matches($Source, $IdentityPattern)
        if ($IdentityMatches.Count -ne 1) {
            throw "identity"
        }
        $IdentityMatch = $IdentityMatches[0]
        $EmbeddedDigest = $IdentityMatch.Groups[1].Value
        $Canonical = $Source.Substring(0, $IdentityMatch.Groups[1].Index) + ('0' * 64) +
            $Source.Substring($IdentityMatch.Groups[1].Index + $IdentityMatch.Groups[1].Length)
        $Hasher = [Security.Cryptography.SHA256]::Create()
        try {
            $ComputedDigest = ([BitConverter]::ToString($Hasher.ComputeHash($Utf8.GetBytes($Canonical)))).Replace('-', '').ToLowerInvariant()
        } finally {
            $Hasher.Dispose()
        }
        if ($EmbeddedDigest -ne $ComputedDigest) {
            throw "digest"
        }

        $Attestation = Get-Content -LiteralPath $AttestationPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-ExactPropertyNames -Value $Attestation -Expected @(
            'schema_version', 'plugin_version', 'bridge_version', 'contract_revision',
            'bridge_source_sha256', 'verified_at_utc', 'checks'
        ) -Label 'schema'
        if (
            [int]$Attestation.schema_version -ne 1 -or
            [int]$Attestation.bridge_version -ne 4 -or
            [int]$Attestation.contract_revision -ne 1 -or
            [string]$Attestation.plugin_version -cne $PluginVersion -or
            [string]$Attestation.bridge_source_sha256 -cne $ComputedDigest -or
            [string]$Attestation.verified_at_utc -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$'
        ) {
            throw "values"
        }
        Assert-ExactPropertyNames -Value $Attestation.checks -Expected @(
            'advanced_gmail_v1', 'zero_result_complete', 'stable_snapshot_pagination',
            'cursor_exhaustion', 'manifest_message_count_hashes', 'sensitive_output_absent'
        ) -Label 'checks'
        foreach ($Property in $Attestation.checks.PSObject.Properties) {
            if ($Property.Value -isnot [bool] -or -not $Property.Value) {
                throw "checks"
            }
        }
    } catch {
        throw "Local bridge attestation validation failed. Use an intact verified release checkout."
    }
}

function Test-McpManifestContract {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        $Manifest = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-ExactPropertyNames -Value $Manifest -Expected @('mcpServers') -Label 'MCP manifest'
        Assert-ExactPropertyNames `
            -Value $Manifest.mcpServers `
            -Expected @('gmail', 'CaseToMD') `
            -Label 'MCP server set'
        $Expected = @{
            gmail = [pscustomobject]@{
                Module = 'avaya_case_review_runtime.gmail_mcp_server'
                Environment = [ordered]@{
                    GMAIL_BACKEND = 'edge_broker'
                    PYTHONIOENCODING = 'utf-8'
                }
            }
            CaseToMD = [pscustomobject]@{
                Module = 'avaya_case_review_runtime.casetomd_mcp_bridge'
                Environment = [ordered]@{ PYTHONIOENCODING = 'utf-8' }
            }
        }
        foreach ($Name in $Expected.Keys) {
            $Server = $Manifest.mcpServers.$Name
            Assert-ExactPropertyNames `
                -Value $Server `
                -Expected @('command', 'args', 'env') `
                -Label "$Name MCP definition"
            Assert-ExactPropertyNames `
                -Value $Server.env `
                -Expected @($Expected[$Name].Environment.Keys) `
                -Label "$Name MCP environment"
            if (
                $null -eq $Server -or
                [string]$Server.command -cne 'python' -or
                @($Server.args).Count -ne 2 -or
                [string]$Server.args[0] -cne '-m' -or
                [string]$Server.args[1] -cne $Expected[$Name].Module
            ) {
                throw "definition"
            }
            foreach ($Variable in $Expected[$Name].Environment.Keys) {
                if ([string]$Server.env.$Variable -cne $Expected[$Name].Environment[$Variable]) {
                    throw "environment"
                }
            }
        }
        if ((Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Contains('${')) {
            throw "placeholder"
        }
    } catch {
        throw "Codex MCP definitions do not match the packaged runtime contract."
    }
}

function Get-CodexMarketplaceSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$MarketplaceName,
        [Parameter(Mandatory = $true)][string]$PluginName
    )

    $MarketplaceListResult = Invoke-CheckedCommand `
        -Stage "marketplace list" `
        -Command "codex" `
        -Arguments @("plugin", "marketplace", "list", "--json") `
        -Description "Listing configured Codex marketplaces" `
        -TimeoutSeconds $TimeoutMarketplaceSeconds
    $MarketplaceList = ConvertFrom-CommandJson `
        -Result $MarketplaceListResult `
        -Stage "marketplace list"
    $ExistingMarketplace = @(
        $MarketplaceList.marketplaces | Where-Object { $_.name -eq $MarketplaceName }
    ) | Select-Object -First 1

    $PluginListResult = Invoke-CheckedCommand `
        -Stage "plugin list" `
        -Command "codex" `
        -Arguments @("plugin", "list", "--json") `
        -Description "Listing installed Codex plugins" `
        -TimeoutSeconds $TimeoutPluginSeconds
    $PluginList = ConvertFrom-CommandJson -Result $PluginListResult -Stage "plugin list"
    $PluginId = "$PluginName@$MarketplaceName"
    $ExistingPlugin = @(
        $PluginList.installed | Where-Object {
            $_.pluginId -eq $PluginId -or
            ($_.name -eq $PluginName -and $_.marketplaceName -eq $MarketplaceName)
        }
    ) | Select-Object -First 1

    $Source = ""
    $SourceType = ""
    $Root = ""
    $Commit = ""
    if ($null -ne $ExistingMarketplace) {
        $Root = [string]$ExistingMarketplace.root
        $SourceType = [string]$ExistingMarketplace.marketplaceSource.sourceType
        $Source = [string]$ExistingMarketplace.marketplaceSource.source
        if ([string]::IsNullOrWhiteSpace($Source)) {
            $Source = $Root
        }
        if (
            -not [string]::IsNullOrWhiteSpace($Root) -and
            $SourceType -ne "local"
        ) {
            $CommitResult = Invoke-CheckedCommand `
                -Stage "marketplace commit snapshot" `
                -Command "git" `
                -Arguments @("-C", $Root, "rev-parse", "HEAD") `
                -Description "Recording the current marketplace commit" `
                -TimeoutSeconds $TimeoutLocalSeconds
            $Commit = $CommitResult.StdOut.Trim()
            if ([string]::IsNullOrWhiteSpace($Commit)) {
                throw "Stage 'marketplace commit snapshot' returned an empty commit."
            }
        }
    }

    return [pscustomobject]@{
        Exists = $null -ne $ExistingMarketplace
        Source = $Source
        SourceType = $SourceType
        Root = $Root
        Commit = $Commit
        PluginInstalled = $null -ne $ExistingPlugin -and [bool]$ExistingPlugin.installed
        PluginEnabled = $null -ne $ExistingPlugin -and [bool]$ExistingPlugin.enabled
        PluginVersion = if ($null -ne $ExistingPlugin) { [string]$ExistingPlugin.version } else { "" }
    }
}

function Resolve-GitRefCommit {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Ref,
        [switch]$RequireTag
    )

    $RefIsCommit = $Ref -match '^[0-9a-fA-F]{40}$'
    $Arguments = @("ls-remote", "--exit-code", $Source)
    if ($RequireTag) {
        $TagRef = "refs/tags/$Ref"
        $Arguments += @($TagRef, "$TagRef^{}")
    } elseif (-not $RefIsCommit) {
        $Arguments += @($Ref, "$Ref^{}")
    }
    $Result = Invoke-CheckedCommand `
        -Stage "target ref resolve" `
        -Command "git" `
        -Arguments $Arguments `
        -Description "Resolving the requested marketplace ref" `
        -TimeoutSeconds $TimeoutMarketplaceSeconds
    $Lines = @($Result.StdOut -split "`r?`n" | Where-Object { $_.Trim() })
    if ($Lines.Count -eq 0) {
        throw "Stage 'target ref resolve' returned no commit."
    }
    $ResolvedLine = if ($RequireTag) {
        $PeeledLine = @($Lines | Where-Object {
            @($_ -split "\s+")[1] -eq "$TagRef^{}"
        }) | Select-Object -First 1
        if ($null -ne $PeeledLine) {
            $PeeledLine
        } else {
            @($Lines | Where-Object {
                @($_ -split "\s+")[1] -eq $TagRef
            }) | Select-Object -First 1
        }
    } elseif ($RefIsCommit) {
        @($Lines | Where-Object { @($_ -split "\s+")[0] -eq $Ref }) | Select-Object -First 1
    } else {
        @($Lines | Where-Object { $_ -match '\^\{\}\s*$' }) | Select-Object -First 1
    }
    if ($null -eq $ResolvedLine) {
        if ($RequireTag) {
            throw "Stage 'target ref resolve' did not return the required release tag."
        } elseif ($RefIsCommit) {
            throw "Stage 'target ref resolve' did not advertise the requested commit."
        }
        $ResolvedLine = $Lines[0]
    }
    $Commit = @($ResolvedLine -split "\s+")[0].Trim()
    if ([string]::IsNullOrWhiteSpace($Commit)) {
        throw "Stage 'target ref resolve' returned no commit."
    }
    return $Commit
}

function Add-CodexMarketplace {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$Source,
        [string]$Ref
    )

    $Arguments = @("plugin", "marketplace", "add", $Source)
    if (-not (Test-LocalMarketplaceSource -Value $Source) -and -not [string]::IsNullOrWhiteSpace($Ref)) {
        $Arguments += @("--ref", $Ref)
    }
    Invoke-CheckedCommand `
        -Stage $Stage `
        -Command "codex" `
        -Arguments $Arguments `
        -Description "Adding the Codex marketplace" `
        -TimeoutSeconds $TimeoutMarketplaceSeconds | Out-Null
}

function Test-CodexMarketplaceIdentity {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Snapshot,
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$SourceType,
        [string]$Commit
    )

    if (-not $Snapshot.Exists -or $Snapshot.SourceType -ne $SourceType) {
        return $false
    }
    if ($SourceType -eq "local") {
        return (Normalize-LocalPath -Value $Snapshot.Root).Equals(
            (Normalize-LocalPath -Value $Source),
            [StringComparison]::OrdinalIgnoreCase
        )
    }
    return (
        (Normalize-GitSource -Value $Snapshot.Source) -eq
        (Normalize-GitSource -Value $Source) -and
        ([string]::IsNullOrWhiteSpace($Commit) -or $Snapshot.Commit -eq $Commit)
    )
}

function Restore-CodexMarketplaceSnapshot {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Before,
        [Parameter(Mandatory = $true)][pscustomobject]$Transaction
    )

    $Current = Get-CodexMarketplaceSnapshot `
        -MarketplaceName $script:MarketplaceName `
        -PluginName $script:PluginName
    $CurrentIsBefore = if ($Before.Exists) {
        Test-CodexMarketplaceIdentity `
            -Snapshot $Current `
            -Source $Before.Source `
            -SourceType $Before.SourceType `
            -Commit $Before.Commit
    } else {
        -not $Current.Exists
    }
    $CurrentIsTarget = Test-CodexMarketplaceIdentity `
        -Snapshot $Current `
        -Source $Transaction.TargetSource `
        -SourceType $Transaction.TargetSourceType `
        -Commit ""

    if (
        $Current.PluginInstalled -and
        (
            -not $Before.PluginInstalled -or
            -not $CurrentIsBefore -or
            $Current.PluginEnabled -ne $Before.PluginEnabled
        )
    ) {
        Invoke-CheckedCommand `
            -Stage "rollback plugin remove" `
            -Command "codex" `
            -Arguments @("plugin", "remove", $script:PluginSelector) `
            -Description "Removing the plugin added by the failed transaction" `
            -TimeoutSeconds $TimeoutPluginSeconds | Out-Null
        $Current.PluginInstalled = $false
        $Current.PluginEnabled = $false
    }
    if ($Current.Exists -and -not $CurrentIsBefore) {
        if (-not $CurrentIsTarget) {
            throw "Stage 'rollback marketplace identity verification' failed."
        }
        Invoke-CheckedCommand `
            -Stage "rollback marketplace remove" `
            -Command "codex" `
            -Arguments @("plugin", "marketplace", "remove", $script:MarketplaceName) `
            -Description "Removing the marketplace added by the failed transaction" `
            -TimeoutSeconds $TimeoutMarketplaceSeconds | Out-Null
        $Current.Exists = $false
    }
    if ($Before.Exists -and -not $Current.Exists) {
        Add-CodexMarketplace `
            -Stage "rollback marketplace add" `
            -Source $Before.Source `
            -Ref $Before.Commit
        $Current.Exists = $true
    }
    if ($Before.PluginInstalled -and -not $Current.PluginInstalled) {
        Invoke-CheckedCommand `
            -Stage "rollback plugin add" `
            -Command "codex" `
            -Arguments @("plugin", "add", $script:PluginSelector, "--json") `
            -Description "Restoring the previously installed Codex plugin" `
            -TimeoutSeconds $TimeoutPluginSeconds | Out-Null
    }

    $Restored = Get-CodexMarketplaceSnapshot `
        -MarketplaceName $script:MarketplaceName `
        -PluginName $script:PluginName
    if ($Before.Exists) {
        if (-not $Restored.Exists -or $Restored.Commit -ne $Before.Commit) {
            throw "Stage 'rollback commit verification' failed."
        }
    } elseif ($Restored.Exists) {
        throw "Stage 'rollback marketplace absence verification' failed."
    }
    if (
        $Restored.PluginInstalled -ne $Before.PluginInstalled -or
        $Restored.PluginEnabled -ne $Before.PluginEnabled
    ) {
        throw "Stage 'rollback plugin state verification' failed."
    }
}

function Test-InstalledCodexPlugin {
    param(
        [Parameter(Mandatory = $true)][string]$MarketplaceName,
        [Parameter(Mandatory = $true)][string]$PluginName,
        [Parameter(Mandatory = $true)][string]$PluginVersion
    )

    $Installed = Get-CodexMarketplaceSnapshot `
        -MarketplaceName $MarketplaceName `
        -PluginName $PluginName
    if (
        -not $Installed.PluginInstalled -or
        -not $Installed.PluginEnabled -or
        $Installed.PluginVersion -cne $PluginVersion
    ) {
        throw "Stage 'installed plugin verification' failed."
    }
    if ([string]::IsNullOrWhiteSpace($Installed.Root)) {
        throw "Stage 'installed MCP manifest verification' returned no marketplace root."
    }
    Test-McpManifestContract -Path (Join-Path $Installed.Root '.mcp.json')

    $ExpectedModules = @{
        gmail = [pscustomobject]@{
            Module = 'avaya_case_review_runtime.gmail_mcp_server'
            Environment = [ordered]@{
                GMAIL_BACKEND = 'edge_broker'
                PYTHONIOENCODING = 'utf-8'
            }
        }
        CaseToMD = [pscustomobject]@{
            Module = 'avaya_case_review_runtime.casetomd_mcp_bridge'
            Environment = [ordered]@{ PYTHONIOENCODING = 'utf-8' }
        }
    }
    foreach ($Name in $ExpectedModules.Keys) {
        $Result = Invoke-CheckedCommand `
            -Stage "installed MCP verification ($Name)" `
            -Command "codex" `
            -Arguments @("mcp", "get", $Name, "--json") `
            -Description "Verifying the installed $Name MCP definition" `
            -TimeoutSeconds $TimeoutLocalSeconds
        $Definition = ConvertFrom-CommandJson `
            -Result $Result `
            -Stage "installed MCP verification ($Name)"
        $Transport = if ($null -ne $Definition.transport) { $Definition.transport } else { $Definition }
        Assert-ExactPropertyNames `
            -Value $Transport.env `
            -Expected @($ExpectedModules[$Name].Environment.Keys) `
            -Label "installed $Name MCP environment"
        if (
            [string]$Transport.command -cne 'python' -or
            @($Transport.args).Count -ne 2 -or
            [string]$Transport.args[0] -cne '-m' -or
            [string]$Transport.args[1] -cne $ExpectedModules[$Name].Module -or
            ($Result.StdOut).Contains('${')
        ) {
            throw "Stage 'installed MCP verification ($Name)' failed."
        }
        foreach ($Variable in $ExpectedModules[$Name].Environment.Keys) {
            if ([string]$Transport.env.$Variable -cne $ExpectedModules[$Name].Environment[$Variable]) {
                throw "Stage 'installed MCP verification ($Name)' failed."
            }
        }
    }
}

function Set-CodexMarketplaceAtRef {
    param(
        [Parameter(Mandatory = $true)][pscustomobject]$Before,
        [Parameter(Mandatory = $true)][string]$TargetSource,
        [Parameter(Mandatory = $true)][string]$TargetRef
    )

    $Transaction = [pscustomobject]@{
        PluginRemoved = $false
        MarketplaceRemoved = $false
        MarketplaceAdded = $false
        PluginAdded = $false
        TargetSource = $TargetSource
        TargetSourceType = ""
        TargetCommit = ""
    }

    $TargetIsLocal = Test-LocalMarketplaceSource -Value $TargetSource
    if ($Before.Exists) {
        $ExistingIsLocal = $Before.SourceType -eq "local"
        if ($TargetIsLocal -ne $ExistingIsLocal) {
            $SameSource = $false
        } elseif ($TargetIsLocal) {
            $SameSource = (Normalize-LocalPath -Value $Before.Root).Equals(
                (Normalize-LocalPath -Value $TargetSource),
                [StringComparison]::OrdinalIgnoreCase
            )
        } else {
            $SameSource = -not [string]::IsNullOrWhiteSpace($Before.Source) -and
                (Normalize-GitSource -Value $Before.Source) -eq
                (Normalize-GitSource -Value $TargetSource)
        }
        if (-not $SameSource) {
            throw "Marketplace '$script:MarketplaceName' already exists with a different source."
        }
    }

    $TargetCommit = ""
    if (-not $TargetIsLocal) {
        $TargetCommit = Resolve-GitRefCommit `
            -Source $TargetSource `
            -Ref $TargetRef `
            -RequireTag:($TargetRef -eq $script:ReleaseRef)
    }
    $Transaction.TargetSourceType = if ($TargetIsLocal) { "local" } else { "git" }
    $Transaction.TargetCommit = $TargetCommit
    $MarketplaceAtTarget = (
        $Before.Exists -and
        (($TargetIsLocal -and $Before.Root) -or ($Before.Commit -eq $TargetCommit))
    )
    if ($Before.PluginInstalled -and -not $Before.PluginEnabled) {
        throw "The installed plugin is disabled; this Codex CLI cannot safely preserve disabled state. No changes were made."
    }
    if ($MarketplaceAtTarget -and $Before.PluginInstalled) {
        Test-InstalledCodexPlugin `
            -MarketplaceName $script:MarketplaceName `
            -PluginName $script:PluginName `
            -PluginVersion $script:PluginVersion
        return $Transaction
    }

    try {
        if (-not $MarketplaceAtTarget) {
            if ($Before.PluginInstalled) {
                $Transaction.PluginRemoved = $true
                Invoke-CheckedCommand `
                    -Stage "plugin remove" `
                    -Command "codex" `
                    -Arguments @("plugin", "remove", $script:PluginSelector) `
                    -Description "Removing the installed Codex plugin before marketplace replacement" `
                    -TimeoutSeconds $TimeoutPluginSeconds | Out-Null
            }
            if ($Before.Exists) {
                $Transaction.MarketplaceRemoved = $true
                Invoke-CheckedCommand `
                    -Stage "marketplace remove" `
                    -Command "codex" `
                    -Arguments @("plugin", "marketplace", "remove", $script:MarketplaceName) `
                    -Description "Removing the existing same-source Codex marketplace" `
                    -TimeoutSeconds $TimeoutMarketplaceSeconds | Out-Null
            }

            $Transaction.MarketplaceAdded = $true
            Add-CodexMarketplace `
                -Stage "new marketplace add" `
                -Source $TargetSource `
                -Ref $TargetRef
            $Added = Get-CodexMarketplaceSnapshot `
                -MarketplaceName $script:MarketplaceName `
                -PluginName $script:PluginName
            if (-not $TargetIsLocal -and $Added.Commit -ne $TargetCommit) {
                throw "Stage 'resolved marketplace commit verification' failed."
            }
        }

        $Transaction.PluginAdded = $true
        Invoke-CheckedCommand `
            -Stage "new plugin add" `
            -Command "codex" `
            -Arguments @("plugin", "add", $script:PluginSelector, "--json") `
            -Description "Installing the Codex plugin" `
            -TimeoutSeconds $TimeoutPluginSeconds | Out-Null
        Test-InstalledCodexPlugin `
            -MarketplaceName $script:MarketplaceName `
            -PluginName $script:PluginName `
            -PluginVersion $script:PluginVersion
        return $Transaction
    } catch {
        $PrimaryMessage = $_.Exception.Message
        if (
            $Transaction.PluginRemoved -or
            $Transaction.MarketplaceRemoved -or
            $Transaction.MarketplaceAdded -or
            $Transaction.PluginAdded
        ) {
            try {
                Restore-CodexMarketplaceSnapshot -Before $Before -Transaction $Transaction
            } catch {
                throw "Marketplace transaction failed: $PrimaryMessage Rollback failed: $($_.Exception.Message)"
            }
        }
        throw $PrimaryMessage
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$CodexManifestPath = Join-Path $ScriptDir ".codex-plugin\plugin.json"
$MarketplaceManifestPath = Join-Path $ScriptDir ".agents\plugins\marketplace.json"
$McpManifestPath = Join-Path $ScriptDir ".mcp.json"
$BrokerCtlPath = Join-Path $ScriptDir "tools\gmail\gmail_brokerctl.py"
$BridgeSourcePath = Join-Path $ScriptDir "tools\gmail\cloud\GmailMcpBridge.gs"
$BridgeAttestationPath = Join-Path $ScriptDir "tools\gmail\cloud\bridge_release_attestation.json"
$RuntimeHelperPath = Join-Path $ScriptDir "tools\installer\runtime_package.py"
$PyProjectPath = Join-Path $ScriptDir "pyproject.toml"

foreach ($RequiredFile in @(
    $CodexManifestPath, $MarketplaceManifestPath, $McpManifestPath, $BrokerCtlPath,
    $BridgeSourcePath, $BridgeAttestationPath, $RuntimeHelperPath, $PyProjectPath
)) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
        throw "Required installation file is missing: $RequiredFile"
    }
}

$CodexManifest = Get-Content -LiteralPath $CodexManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$MarketplaceManifest = Get-Content -LiteralPath $MarketplaceManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$PluginName = [string]$CodexManifest.name
$MarketplaceName = [string]$MarketplaceManifest.name
$PluginVersion = [string]$CodexManifest.version
if (
    [string]::IsNullOrWhiteSpace($PluginName) -or
    [string]::IsNullOrWhiteSpace($MarketplaceName) -or
    [string]::IsNullOrWhiteSpace($PluginVersion)
) {
    throw "Codex plugin or marketplace name is missing."
}
if (@($MarketplaceManifest.plugins | Where-Object { $_.name -eq $PluginName }).Count -ne 1) {
    throw "Marketplace must contain exactly one entry for '$PluginName'."
}
$ReleaseRef = "v$PluginVersion"
$TargetRef = if ([string]::IsNullOrWhiteSpace($MarketplaceRef)) { $ReleaseRef } else { $MarketplaceRef }
if ($TargetRef -ne $ReleaseRef -and -not $AllowUnreleasedRef) {
    throw "Marketplace ref '$TargetRef' is not the manifest release ref. Use -AllowUnreleasedRef only for development or release-candidate installation."
}
$PluginSelector = "$PluginName@$MarketplaceName"

if ($CloudBridgeVerified) {
    Write-Warning "-CloudBridgeVerified is deprecated and does not bypass local or live bridge verification."
}

$PyProject = Get-Content -LiteralPath $PyProjectPath -Raw -Encoding UTF8
$ProjectVersion = [regex]::Match($PyProject, '(?m)^version\s*=\s*"([^"]+)"\s*$')
if (-not $ProjectVersion.Success -or $ProjectVersion.Groups[1].Value -cne $PluginVersion) {
    throw "Runtime package version does not match the Codex plugin version."
}
Test-McpManifestContract -Path $McpManifestPath
Test-LocalBridgeAttestation `
    -SourcePath $BridgeSourcePath `
    -AttestationPath $BridgeAttestationPath `
    -PluginVersion $PluginVersion

if (-not $DryRun) {
    foreach ($RequiredCommand in @("python", "codex", "git")) {
        if (-not (Get-Command $RequiredCommand -ErrorAction SilentlyContinue)) {
            throw "$RequiredCommand was not found in PATH."
        }
    }
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Avaya Case Review Suite - Codex Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Plugin:      $PluginName"
Write-Host "  Marketplace: $MarketplaceName"
Write-Host "  Source:      $MarketplaceSource"
Write-Host "  Ref:         $TargetRef"
if ($DryRun) {
    Write-Host "  Mode:        dry run (no state changes)" -ForegroundColor DarkGray
    foreach ($Stage in @(
        "validate release attestation", "check Python and Codex versions",
        "inspect installed runtime", "verify retained rollback wheel", "verify-bridge",
        "install dependencies and build runtime wheel", "validate runtime wheel",
        "install runtime wheel", "smoke runtime MCP modules", "new marketplace add",
        "new plugin add", "verify plugin identity, version, and MCP definitions"
    )) {
        Write-Host "  Planned stage: $Stage" -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "Codex installation dry run complete; no state changes were made." -ForegroundColor Green
    exit 0
}

$PythonVersion = Invoke-CheckedCommand `
    -Stage "Python version" `
    -Command "python" `
    -Arguments @("--version") `
    -Description "Checking Python" `
    -TimeoutSeconds $TimeoutLocalSeconds
Test-VersionAtLeast -Actual ($PythonVersion.StdOut + $PythonVersion.StdErr) -Minimum ([version]'3.10') -Label 'Python'
$CodexVersion = Invoke-CheckedCommand `
    -Stage "Codex version" `
    -Command "codex" `
    -Arguments @("--version") `
    -Description "Checking Codex CLI" `
    -TimeoutSeconds $TimeoutLocalSeconds
Test-VersionAtLeast -Actual ($CodexVersion.StdOut + $CodexVersion.StdErr) -Minimum ([version]'0.153.4') -Label 'Codex CLI'

$InstalledVersionResult = Invoke-CheckedCommand `
    -Stage "runtime version inspection" `
    -Command "python" `
    -Arguments @($RuntimeHelperPath, "installed-version") `
    -Description "Recording the installed MCP runtime version" `
    -TimeoutSeconds $TimeoutLocalSeconds
$InstalledRuntime = ConvertFrom-CommandJson -Result $InstalledVersionResult -Stage "runtime version inspection"
$PreviousRuntimePresent = [bool]$InstalledRuntime.installed
$PreviousRuntimeVersion = if ($PreviousRuntimePresent) { [string]$InstalledRuntime.version } else { "" }
$WheelStore = Join-Path $env:LOCALAPPDATA "AvayaCaseReview\runtime-wheels"
$PreviousRuntimeWheel = $null
if ($PreviousRuntimePresent -and $PreviousRuntimeVersion -cne $PluginVersion -and -not $SkipDependencyInstall) {
    $PriorWheels = @(Get-ChildItem -LiteralPath $WheelStore -Filter "avaya_case_review_runtime-$PreviousRuntimeVersion-*.whl" -File -ErrorAction SilentlyContinue)
    if ($PriorWheels.Count -ne 1) {
        throw "A retained wheel for the installed runtime version is required before upgrade."
    }
    $PreviousRuntimeWheel = $PriorWheels[0].FullName
    Invoke-CheckedCommand `
        -Stage "prior runtime wheel validation" `
        -Command "python" `
        -Arguments @($RuntimeHelperPath, "validate-wheel", "--wheel", $PreviousRuntimeWheel, "--version", $PreviousRuntimeVersion) `
        -Description "Validating the retained rollback wheel" `
        -TimeoutSeconds $TimeoutLocalSeconds | Out-Null
}

$VerifyArguments = @(
    "-B", $BrokerCtlPath, "verify-bridge",
    "--source", $BridgeSourcePath,
    "--attestation", $BridgeAttestationPath,
    "--plugin-version", $PluginVersion
)
$BridgeResult = Invoke-CheckedCommand `
    -Stage "verify-bridge" `
    -Command "python" `
    -Arguments $VerifyArguments `
    -Description "Verifying the live Gmail Cloud Bridge" `
    -TimeoutSeconds $TimeoutBridgeSeconds `
    -AllowFailure
if ($BridgeResult.ExitCode -eq 10) {
    if ($SkipLogin) {
        throw "Gmail authentication is required; rerun without -SkipLogin to open Managed Edge."
    }
    Invoke-CheckedCommand `
        -Stage "Gmail login" `
        -Command "python" `
        -Arguments @("-B", $BrokerCtlPath, "login") `
        -Description "Opening Managed Edge for SSO/MFA" `
        -TimeoutSeconds 330 | Out-Null
    $BridgeResult = Invoke-CheckedCommand `
        -Stage "verify-bridge retry" `
        -Command "python" `
        -Arguments $VerifyArguments `
        -Description "Retrying live Gmail Cloud Bridge verification" `
        -TimeoutSeconds $TimeoutBridgeSeconds `
        -AllowFailure
}
if ($BridgeResult.ExitCode -eq 10) {
    throw "Gmail authentication remains required after one login attempt."
}
if ($BridgeResult.ExitCode -eq 20) {
    throw "The Gmail Cloud Bridge is unavailable."
}
if ($BridgeResult.ExitCode -ne 0) {
    throw "The Gmail Cloud Bridge is incompatible with this release."
}

$RuntimeMutated = $false
$CurrentRuntimeWheel = $null
try {
    if ($SkipDependencyInstall) {
        if (-not $PreviousRuntimePresent -or $PreviousRuntimeVersion -cne $PluginVersion) {
            throw "-SkipDependencyInstall requires runtime version $PluginVersion to already be installed."
        }
    } else {
        $PipArguments = @(
            "-m", "pip", "install", "mcp", "playwright", "setuptools>=68", "--quiet",
            "--trusted-host", "pypi.org", "--trusted-host", "pypi.python.org",
            "--trusted-host", "files.pythonhosted.org"
        )
        Invoke-CheckedCommand `
            -Stage "dependency install" `
            -Command "python" `
            -Arguments $PipArguments `
            -Description "Installing Python MCP dependencies and the local build backend" `
            -TimeoutSeconds $TimeoutPipSeconds | Out-Null

        if ($IncludeLegacyChromium) {
            $PreviousNodeTls = $env:NODE_TLS_REJECT_UNAUTHORIZED
            try {
                if (-not $env:NODE_EXTRA_CA_CERTS) { $env:NODE_TLS_REJECT_UNAUTHORIZED = "0" }
                Invoke-CheckedCommand `
                    -Stage "playwright install" `
                    -Command "python" `
                    -Arguments @("-m", "playwright", "install", "chromium") `
                    -Description "Installing optional legacy Chromium rollback runtime" `
                    -TimeoutSeconds $TimeoutPipSeconds | Out-Null
            } finally {
                $env:NODE_TLS_REJECT_UNAUTHORIZED = $PreviousNodeTls
            }
        }

        New-Item -ItemType Directory -Path $WheelStore -Force | Out-Null
        Invoke-CheckedCommand `
            -Stage "runtime wheel build" `
            -Command "python" `
            -Arguments @("-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", $WheelStore, $ScriptDir) `
            -Description "Building the packaged MCP runtime" `
            -TimeoutSeconds $TimeoutPipSeconds | Out-Null
        $CurrentWheels = @(Get-ChildItem -LiteralPath $WheelStore -Filter "avaya_case_review_runtime-$PluginVersion-*.whl" -File)
        if ($CurrentWheels.Count -ne 1) {
            throw "Stage 'runtime wheel discovery' did not find exactly one current runtime wheel."
        }
        $CurrentRuntimeWheel = $CurrentWheels[0].FullName
        Invoke-CheckedCommand `
            -Stage "runtime wheel validation" `
            -Command "python" `
            -Arguments @($RuntimeHelperPath, "validate-wheel", "--wheel", $CurrentRuntimeWheel, "--version", $PluginVersion) `
            -Description "Validating the packaged MCP runtime wheel" `
            -TimeoutSeconds $TimeoutLocalSeconds | Out-Null
        $RuntimeMutated = $true
        Invoke-CheckedCommand `
            -Stage "runtime install" `
            -Command "python" `
            -Arguments @("-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", $CurrentRuntimeWheel) `
            -Description "Installing the packaged MCP runtime" `
            -TimeoutSeconds $TimeoutPipSeconds | Out-Null
    }

    Invoke-CheckedCommand `
        -Stage "runtime smoke" `
        -Command "python" `
        -Arguments @($RuntimeHelperPath, "smoke", "--python", "python", "--work-dir", ([IO.Path]::GetTempPath())) `
        -Description "Checking both installed MCP modules" `
        -TimeoutSeconds $TimeoutBridgeSeconds | Out-Null

    $Before = Get-CodexMarketplaceSnapshot -MarketplaceName $MarketplaceName -PluginName $PluginName
    $null = Set-CodexMarketplaceAtRef -Before $Before -TargetSource $MarketplaceSource -TargetRef $TargetRef
} catch {
    $PrimaryMessage = $_.Exception.Message
    if ($RuntimeMutated) {
        try {
            if ($PreviousRuntimePresent) {
                $RestoreWheel = if ($PreviousRuntimeVersion -ceq $PluginVersion) { $CurrentRuntimeWheel } else { $PreviousRuntimeWheel }
                Invoke-CheckedCommand `
                    -Stage "runtime rollback install" `
                    -Command "python" `
                    -Arguments @("-m", "pip", "install", "--no-index", "--no-deps", "--force-reinstall", $RestoreWheel) `
                    -Description "Restoring the prior MCP runtime" `
                    -TimeoutSeconds $TimeoutPipSeconds | Out-Null
            } else {
                Invoke-CheckedCommand `
                    -Stage "runtime rollback uninstall" `
                    -Command "python" `
                    -Arguments @("-m", "pip", "uninstall", "--yes", "avaya-case-review-runtime") `
                    -Description "Removing the newly installed MCP runtime" `
                    -TimeoutSeconds $TimeoutPipSeconds | Out-Null
            }
            $RestoredResult = Invoke-CheckedCommand `
                -Stage "runtime rollback verification" `
                -Command "python" `
                -Arguments @($RuntimeHelperPath, "installed-version") `
                -Description "Verifying the restored MCP runtime state" `
                -TimeoutSeconds $TimeoutLocalSeconds
            $RestoredRuntime = ConvertFrom-CommandJson -Result $RestoredResult -Stage "runtime rollback verification"
            if (
                [bool]$RestoredRuntime.installed -ne $PreviousRuntimePresent -or
                ($PreviousRuntimePresent -and [string]$RestoredRuntime.version -cne $PreviousRuntimeVersion)
            ) {
                throw "Stage 'runtime rollback verification' failed."
            }
        } catch {
            throw "Installation failed: $PrimaryMessage Runtime rollback failed: $($_.Exception.Message)"
        }
    }
    throw $PrimaryMessage
}

Write-Host ""
Write-Host "Codex installation complete." -ForegroundColor Green
Write-Host "Start a new Codex task so the plugin skills and MCP servers are loaded." -ForegroundColor White
Write-Host "Example: Provide a case review for SR 1-23659220672" -ForegroundColor White
