# ==============================================================================
# Avaya Case Review Suite - Codex installer
# ==============================================================================

[CmdletBinding()]
param(
    [string]$MarketplaceSource = "https://github.com/avayahmao/avaya-case-review-pack",
    [string]$MarketplaceRef = "main",
    [switch]$CloudBridgeVerified,
    [switch]$SkipDependencyInstall,
    [switch]$SkipLogin,
    [switch]$IncludeLegacyChromium,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $RenderedArguments = @($Arguments | ForEach-Object {
        $Text = [string]$_
        if ($Text -match '\s') { '"' + $Text.Replace('"', '\"') + '"' } else { $Text }
    })
    Write-Host "  $Description" -ForegroundColor Yellow
    Write-Host "  > $Command $($RenderedArguments -join ' ')" -ForegroundColor DarkGray
    if ($DryRun) {
        return
    }

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
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
if ([string]::IsNullOrWhiteSpace($PluginName) -or [string]::IsNullOrWhiteSpace($MarketplaceName)) {
    throw "Codex plugin or marketplace name is missing."
}
if (@($MarketplaceManifest.plugins | Where-Object { $_.name -eq $PluginName }).Count -ne 1) {
    throw "Marketplace must contain exactly one entry for '$PluginName'."
}

if (-not $DryRun -and -not $CloudBridgeVerified) {
    throw "Cloud bridge verification is required. Complete docs/GMAIL_CLOUD_BRIDGE.md, then rerun with -CloudBridgeVerified."
}

foreach ($RequiredCommand in @("python", "codex")) {
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
if ($DryRun) {
    Write-Host "  Mode:        dry run (no state changes)" -ForegroundColor DarkGray
}

if (-not $SkipDependencyInstall) {
    $PipArguments = @(
        "-m", "pip", "install", "mcp", "playwright", "--quiet",
        "--trusted-host", "pypi.org",
        "--trusted-host", "pypi.python.org",
        "--trusted-host", "files.pythonhosted.org"
    )
    Invoke-CheckedCommand -Command "python" -Arguments $PipArguments -Description "Installing Python MCP and Playwright dependencies"

    if ($IncludeLegacyChromium) {
        $PreviousNodeTls = $env:NODE_TLS_REJECT_UNAUTHORIZED
        try {
            if (-not $env:NODE_EXTRA_CA_CERTS) {
                $env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
            }
            Invoke-CheckedCommand `
                -Command "python" `
                -Arguments @("-m", "playwright", "install", "chromium") `
                -Description "Installing optional legacy Chromium rollback runtime"
        } finally {
            $env:NODE_TLS_REJECT_UNAUTHORIZED = $PreviousNodeTls
        }
    }
}

if ($DryRun) {
    $AddArguments = @("plugin", "marketplace", "add", $MarketplaceSource)
    if (-not (Test-LocalMarketplaceSource -Value $MarketplaceSource) -and $MarketplaceRef) {
        $AddArguments += @("--ref", $MarketplaceRef)
    }
    Invoke-CheckedCommand -Command "codex" -Arguments $AddArguments -Description "Adding the Codex marketplace"
} else {
    $MarketplaceListJson = & codex plugin marketplace list --json
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to list configured Codex marketplaces."
    }
    try {
        $MarketplaceList = ($MarketplaceListJson | Out-String) | ConvertFrom-Json
    } catch {
        throw "Codex marketplace list returned invalid JSON."
    }

    $ExistingMarketplace = @(
        $MarketplaceList.marketplaces | Where-Object { $_.name -eq $MarketplaceName }
    ) | Select-Object -First 1

    if ($null -ne $ExistingMarketplace) {
        if (Test-LocalMarketplaceSource -Value $MarketplaceSource) {
            $RequestedRoot = Normalize-LocalPath -Value $MarketplaceSource
            $ExistingRoot = Normalize-LocalPath -Value ([string]$ExistingMarketplace.root)
            if (-not $ExistingRoot.Equals($RequestedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Marketplace '$MarketplaceName' already points to a different local source: $ExistingRoot"
            }
        } else {
            $ExistingSource = [string]$ExistingMarketplace.marketplaceSource.source
            if (
                [string]::IsNullOrWhiteSpace($ExistingSource) -or
                (Normalize-GitSource -Value $ExistingSource) -ne (Normalize-GitSource -Value $MarketplaceSource)
            ) {
                throw "Marketplace '$MarketplaceName' already exists with a different source."
            }
            Invoke-CheckedCommand `
                -Command "codex" `
                -Arguments @("plugin", "marketplace", "upgrade", $MarketplaceName) `
                -Description "Refreshing the existing Codex marketplace"
        }
    } else {
        $AddArguments = @("plugin", "marketplace", "add", $MarketplaceSource)
        if (-not (Test-LocalMarketplaceSource -Value $MarketplaceSource) -and $MarketplaceRef) {
            $AddArguments += @("--ref", $MarketplaceRef)
        }
        Invoke-CheckedCommand -Command "codex" -Arguments $AddArguments -Description "Adding the Codex marketplace"
    }
}

Invoke-CheckedCommand `
    -Command "codex" `
    -Arguments @("plugin", "add", "$PluginName@$MarketplaceName") `
    -Description "Installing the Codex plugin"

if (-not $SkipLogin -and -not $DryRun) {
    Write-Host "  Checking the shared Gmail Edge broker..." -ForegroundColor Yellow
    & python $BrokerCtlPath status
    $BrokerStatusExit = $LASTEXITCODE
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
