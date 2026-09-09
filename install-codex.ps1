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
$BrokerCtlPath = Join-Path $ScriptDir "tools\gmail\gmail_brokerctl.py"

foreach ($RequiredFile in @($CodexManifestPath, $MarketplaceManifestPath, $BrokerCtlPath)) {
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

if (-not $DryRun -and -not $CloudBridgeVerified) {
    throw "Cloud bridge verification is required. Complete docs/GMAIL_CLOUD_BRIDGE.md, then rerun with -CloudBridgeVerified."
}

foreach ($RequiredCommand in @("python", "codex", "git")) {
    if (-not (Get-Command $RequiredCommand -ErrorAction SilentlyContinue)) {
        throw "$RequiredCommand was not found in PATH."
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
    Write-Host "  Planned gate: validate release attestation" -ForegroundColor DarkGray
    Write-Host "  Planned gate: verify-bridge" -ForegroundColor DarkGray
}

if (-not $SkipDependencyInstall) {
    $PipArguments = @(
        "-m", "pip", "install", "mcp", "playwright", "--quiet",
        "--trusted-host", "pypi.org",
        "--trusted-host", "pypi.python.org",
        "--trusted-host", "files.pythonhosted.org"
    )
    $null = Invoke-CheckedCommand `
        -Stage "pip install" `
        -Command "python" `
        -Arguments $PipArguments `
        -Description "Installing Python MCP and Playwright dependencies" `
        -TimeoutSeconds $TimeoutPipSeconds

    if ($IncludeLegacyChromium) {
        $PreviousNodeTls = $env:NODE_TLS_REJECT_UNAUTHORIZED
        try {
            if (-not $env:NODE_EXTRA_CA_CERTS) {
                $env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
            }
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
}

if ($DryRun) {
    Add-CodexMarketplace `
        -Stage "new marketplace add" `
        -Source $MarketplaceSource `
        -Ref $TargetRef
    Invoke-CheckedCommand `
        -Stage "new plugin add" `
        -Command "codex" `
        -Arguments @("plugin", "add", $PluginSelector, "--json") `
        -Description "Installing the Codex plugin" `
        -TimeoutSeconds $TimeoutPluginSeconds | Out-Null
} else {
    $Before = Get-CodexMarketplaceSnapshot `
        -MarketplaceName $MarketplaceName `
        -PluginName $PluginName
    $null = Set-CodexMarketplaceAtRef `
        -Before $Before `
        -TargetSource $MarketplaceSource `
        -TargetRef $TargetRef
}

if (-not $SkipLogin -and -not $DryRun) {
    Write-Host "  Checking the shared Gmail Edge broker..." -ForegroundColor Yellow
    $BrokerStatus = Invoke-BoundedCommand `
        -Stage "Gmail broker status" `
        -Command "python" `
        -Arguments @($BrokerCtlPath, "status") `
        -TimeoutSeconds $TimeoutBridgeSeconds `
        -AllowFailure
    $BrokerStatusExit = $BrokerStatus.ExitCode
    if ($BrokerStatusExit -eq 10) {
        Write-Host "  Gmail authentication is required. Opening Managed Edge for SSO/MFA..." -ForegroundColor Cyan
        & python $BrokerCtlPath login
        if ($LASTEXITCODE -ne 0) {
            throw "Gmail authentication did not complete successfully."
        }
    } elseif ($BrokerStatusExit -ne 0) {
        throw "Gmail broker validation failed with exit code $BrokerStatusExit."
    }
}

Write-Host ""
if ($DryRun) {
    Write-Host "Codex installation dry run complete; no state changes were made." -ForegroundColor Green
} else {
    Write-Host "Codex installation complete." -ForegroundColor Green
    Write-Host "Start a new Codex task so the plugin skills and MCP servers are loaded." -ForegroundColor White
    Write-Host "Example: Provide a case review for SR 1-23659220672" -ForegroundColor White
}
