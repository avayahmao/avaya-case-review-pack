# ==============================================================================
# Avaya Case Review Suite — Automated Setup Script for Support Managers
# ==============================================================================
# This script sets up Antigravity Plugins, MCP Servers, Python dependencies,
# and performs initial authentication for Avaya Support Managers.
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$ConfigMigrationOnly,
    [string]$ConfigMigrationPath,
    [string]$ConfigMigrationGmailScript,
    [string]$ConfigMigrationCaseToMdScript
)

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

$ErrorActionPreference = "Stop"

function Test-ObjectContainer {
    param([AllowNull()][object]$Value)

    return (
        $null -ne $Value -and (
            $Value -is [System.Collections.IDictionary] -or
            $Value -is [System.Management.Automation.PSCustomObject]
        )
    )
}

function Get-ObjectPropertyValue {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) {
            return $Object[$Name]
        }
        return $null
    }

    $Property = $Object.PSObject.Properties[$Name]
    if ($null -eq $Property) {
        return $null
    }
    return $Property.Value
}

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowNull()][object]$Value
    )

    if ($Object -is [System.Collections.IDictionary]) {
        $Object[$Name] = $Value
        return
    }

    $Property = $Object.PSObject.Properties[$Name]
    if ($null -eq $Property) {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    } else {
        $Property.Value = $Value
    }
}

function Get-OrAddObjectProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $Value = Get-ObjectPropertyValue -Object $Object -Name $Name
    if (-not (Test-ObjectContainer -Value $Value)) {
        $Value = [pscustomobject]@{}
        Set-ObjectProperty -Object $Object -Name $Name -Value $Value
    }
    return $Value
}

function Update-McpConfiguration {
    param(
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [Parameter(Mandatory = $true)][string]$GmailScriptPath,
        [Parameter(Mandatory = $true)][string]$CaseToMdScriptPath
    )

    $ExistingConfig = [pscustomobject]@{}
    if (Test-Path -LiteralPath $ConfigPath) {
        $ExistingJson = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
        if (-not [string]::IsNullOrWhiteSpace($ExistingJson)) {
            try {
                $ExistingConfig = $ExistingJson | ConvertFrom-Json
            } catch {
                throw "Existing MCP configuration is invalid JSON; refusing to overwrite $ConfigPath."
            }
            if (-not (Test-ObjectContainer -Value $ExistingConfig)) {
                throw "Existing MCP configuration must be a JSON object."
            }
        }
    }

    $McpServers = Get-OrAddObjectProperty -Object $ExistingConfig -Name "mcpServers"
    $GmailServer = Get-OrAddObjectProperty -Object $McpServers -Name "gmail"
    $GmailEnvironment = Get-OrAddObjectProperty -Object $GmailServer -Name "env"
    Set-ObjectProperty -Object $GmailEnvironment -Name "GMAIL_BACKEND" -Value "edge_broker"
    Set-ObjectProperty -Object $GmailServer -Name "command" -Value "python"
    Set-ObjectProperty -Object $GmailServer -Name "args" -Value @($GmailScriptPath)

    $CaseToMdServer = Get-OrAddObjectProperty -Object $McpServers -Name "CaseToMD"
    Set-ObjectProperty -Object $CaseToMdServer -Name "command" -Value "python"
    Set-ObjectProperty -Object $CaseToMdServer -Name "args" -Value @($CaseToMdScriptPath)

    $ConfigDirectory = Split-Path -Parent $ConfigPath
    if ($ConfigDirectory -and -not (Test-Path -LiteralPath $ConfigDirectory)) {
        New-Item -ItemType Directory -Path $ConfigDirectory -Force | Out-Null
    }
    $McpJson = $ExistingConfig | ConvertTo-Json -Depth 20
    Set-Content -LiteralPath $ConfigPath -Value $McpJson -Encoding UTF8
}

function Get-ProfileBaseline {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return "[ABSENT]"
    }
    $ResolvedRoot = (Resolve-Path -LiteralPath $Path).Path.TrimEnd("\", "/")
    $Records = @(
        Get-ChildItem -LiteralPath $ResolvedRoot -Recurse -Force -File |
            Sort-Object -Property FullName |
            ForEach-Object {
                $RelativePath = $_.FullName.Substring($ResolvedRoot.Length).TrimStart("\", "/")
                $Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
                "{0}|{1}|{2}" -f $RelativePath, $_.Length, $Hash
            }
    )
    return "[PRESENT]`n$($Records -join "`n")"
}

function Assert-ProfileBaselineUnchanged {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$Before,
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$After
    )

    if (-not [string]::Equals($Before, $After, [StringComparison]::Ordinal)) {
        throw "$Name changed during deployment; refusing to continue."
    }
}

function Get-BrokerEdgeOwnerProcesses {
    param([Parameter(Mandatory = $true)][string]$EdgeProfileDir)

    $ResolvedProfile = [IO.Path]::GetFullPath($EdgeProfileDir).TrimEnd("\", "/")
    $ProfileArgument = "--user-data-dir=$ResolvedProfile"
    return @(
        Get-CimInstance Win32_Process -Filter "Name = 'msedge.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -and $_.CommandLine.IndexOf(
                    $ProfileArgument,
                    [StringComparison]::OrdinalIgnoreCase
                ) -ge 0
            }
    )
}

function Wait-GmailBrokerExit {
    param(
        [int]$BrokerProcessId,
        [Parameter(Mandatory = $true)][string]$StateFile,
        [Parameter(Mandatory = $true)][string]$EdgeProfileDir,
        [bool]$RequireStateRemoval = $false,
        [int]$TimeoutSeconds = 390
    )

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ($true) {
        $BrokerIsRunning = $false
        if ($BrokerProcessId -gt 0) {
            $BrokerIsRunning = $null -ne (
                Get-Process -Id $BrokerProcessId -ErrorAction SilentlyContinue
            )
        }
        $StateExists = Test-Path -LiteralPath $StateFile
        $StateBlocksExit = $RequireStateRemoval -and $StateExists
        $EdgeOwners = @(Get-BrokerEdgeOwnerProcesses -EdgeProfileDir $EdgeProfileDir)
        if (-not $BrokerIsRunning -and -not $StateBlocksExit -and $EdgeOwners.Count -eq 0) {
            return
        }
        if ([DateTime]::UtcNow -ge $Deadline) {
            throw "Timed out waiting for the Gmail broker and its Managed Edge owner to exit."
        }
        Start-Sleep -Milliseconds 500
    }
}

function Stop-RunningGmailBroker {
    param(
        [Parameter(Mandatory = $true)][string]$BrokerCtlPath,
        [Parameter(Mandatory = $true)][string]$StateFile,
        [Parameter(Mandatory = $true)][string]$EdgeProfileDir
    )

    $BrokerProcessId = 0
    if (Test-Path -LiteralPath $StateFile) {
        try {
            $BrokerState = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($BrokerState.pid -is [int] -or $BrokerState.pid -is [long]) {
                $BrokerProcessId = [int]$BrokerState.pid
            }
        } catch {
            $BrokerProcessId = 0
        }
    }

    $StopExit = 20
    if (Test-Path -LiteralPath $BrokerCtlPath) {
        $StopOutput = @(python $BrokerCtlPath stop)
        $StopExit = $LASTEXITCODE
        if ($StopOutput.Count -gt 0) {
            Write-Host "  Existing broker stop response: $($StopOutput[-1])" -ForegroundColor DarkGray
        }
        if ($StopExit -ne 0 -and $StopExit -ne 20) {
            throw "Unable to stop the existing Gmail broker (exit $StopExit)."
        }
    }

    Wait-GmailBrokerExit `
        -BrokerProcessId $BrokerProcessId `
        -StateFile $StateFile `
        -EdgeProfileDir $EdgeProfileDir `
        -RequireStateRemoval ($StopExit -eq 0)
    return [pscustomobject]@{
        exit_code = $StopExit
        pid = $BrokerProcessId
    }
}

function Get-InstalledBrokerBuildId {
    param([Parameter(Mandatory = $true)][string]$BrokerScriptPath)

    $BrokerSource = Get-Content -LiteralPath $BrokerScriptPath -Raw -Encoding UTF8
    $BuildMatch = [regex]::Match(
        $BrokerSource,
        'build_id:\s*str\s*=\s*"(?<id>[A-Za-z0-9._-]+)"'
    )
    if (-not $BuildMatch.Success) {
        throw "Unable to determine the installed Gmail broker build ID."
    }
    return $BuildMatch.Groups["id"].Value
}

function Assert-BrokerBuildId {
    param(
        [Parameter(Mandatory = $true)][object[]]$StatusOutput,
        [Parameter(Mandatory = $true)][string]$ExpectedBuildId
    )

    $StatusLine = @($StatusOutput | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })[-1]
    try {
        $StatusPayload = $StatusLine | ConvertFrom-Json
    } catch {
        throw "Gmail broker status did not return valid JSON."
    }
    $ActualBuildId = $StatusPayload.result.build_id
    if ($ActualBuildId -ne $ExpectedBuildId) {
        throw "Running Gmail broker build '$ActualBuildId' does not match installed build '$ExpectedBuildId'."
    }
}

if ($ConfigMigrationOnly) {
    if (
        [string]::IsNullOrWhiteSpace($ConfigMigrationPath) -or
        [string]::IsNullOrWhiteSpace($ConfigMigrationGmailScript) -or
        [string]::IsNullOrWhiteSpace($ConfigMigrationCaseToMdScript)
    ) {
        throw "Config migration paths are required when -ConfigMigrationOnly is used."
    }
    Update-McpConfiguration `
        -ConfigPath $ConfigMigrationPath `
        -GmailScriptPath $ConfigMigrationGmailScript `
        -CaseToMdScriptPath $ConfigMigrationCaseToMdScript
    return
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$UserHome = $env:USERPROFILE
$GeminiConfigDir = Join-Path $UserHome ".gemini\config"
$GeminiPluginsDir = Join-Path $GeminiConfigDir "plugins"
$GeminiToolsDir = Join-Path $UserHome ".gemini\tools\gmail"
$McpConfigFile = Join-Path $GeminiConfigDir "mcp_config.json"
$LocalAppData = if ($env:LOCALAPPDATA) {
    $env:LOCALAPPDATA
} else {
    Join-Path $UserHome "AppData\Local"
}
$BrokerStateDir = Join-Path $LocalAppData "AvayaCaseReview\gmail-broker"
$BrokerStateFile = Join-Path $BrokerStateDir "state.json"
$LegacyProfileDir = Join-Path $GeminiToolsDir "chrome_profile"
$EdgeBrokerProfileDir = Join-Path $GeminiToolsDir "edge_broker_profile"
$BrokerCtlPath = Join-Path $GeminiToolsDir "gmail_brokerctl.py"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Avaya Case Review Manager Suite — Environment Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------------------
# 1. Check Python Environment
# ------------------------------------------------------------------------------
Write-Host "[1/6] Checking Python installation..." -ForegroundColor Yellow
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Error "Python was not found in PATH. Please install Python 3.10+ and add it to PATH."
    exit 1
}
$PythonVersion = python --version 2>&1
Write-Host "  Found: $PythonVersion" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 2. Install Required Python Packages & Playwright Browser
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/6] Installing required Python libraries (mcp, playwright)..." -ForegroundColor Yellow
$env:PYTHONIOENCODING = "utf-8"

# Corporate SSL bypass for pip (many enterprise proxies MITM PyPI TLS).
# --trusted-host disables cert validation ONLY for these hosts; other traffic is untouched.
$PipTrustedHosts = @(
    "--trusted-host", "pypi.org",
    "--trusted-host", "pypi.python.org",
    "--trusted-host", "files.pythonhosted.org"
)

python -m pip install --upgrade pip --quiet @PipTrustedHosts
python -m pip install mcp playwright --quiet @PipTrustedHosts
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Python packages. If your corporate proxy requires authentication, set HTTPS_PROXY / HTTP_PROXY before running this script."
    exit 1
}
Write-Host "  Python packages installed successfully." -ForegroundColor Green

Write-Host "  Installing Playwright Chromium browser binary..." -ForegroundColor Yellow
# Corporate MITM proxies (e.g. Zscaler, Netskope, Blue Coat) commonly break the
# Playwright browser download because the bundled Node driver validates TLS strictly.
# NODE_TLS_REJECT_UNAUTHORIZED=0 disables cert validation for THIS process only —
# it does NOT persist after the script exits.
# If your org supplies a corporate CA bundle, prefer setting NODE_EXTRA_CA_CERTS
# to that PEM file INSTEAD of using this bypass.
$OldNodeTls = $env:NODE_TLS_REJECT_UNAUTHORIZED
if (-not $env:NODE_EXTRA_CA_CERTS) {
    Write-Host "  (Applying NODE_TLS_REJECT_UNAUTHORIZED=0 to bypass corporate SSL inspection for this download.)" -ForegroundColor DarkGray
    $env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
} else {
    Write-Host "  (Using corporate CA bundle from NODE_EXTRA_CA_CERTS=$($env:NODE_EXTRA_CA_CERTS))" -ForegroundColor DarkGray
}
playwright install chromium
$PlaywrightExit = $LASTEXITCODE
# Restore prior state (do not leak the bypass into later steps or the user's shell).
$env:NODE_TLS_REJECT_UNAUTHORIZED = $OldNodeTls

if ($PlaywrightExit -ne 0) {
    Write-Warning "Playwright browser installation returned non-zero code ($PlaywrightExit). Attempting to proceed."
    Write-Warning "If this failed due to corporate SSL, set NODE_EXTRA_CA_CERTS to your corporate CA .pem file and re-run install.bat."
} else {
    Write-Host "  Playwright Chromium installed successfully." -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# 3. Deploy Plugin Files
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/6] Deploying Avaya Case Review plugin files..." -ForegroundColor Yellow
$SourcePluginDir = Join-Path $ScriptDir "plugins\avaya-case-review"
$TargetPluginDir = Join-Path $GeminiPluginsDir "avaya-case-review"

if (-not (Test-Path $GeminiPluginsDir)) {
    New-Item -ItemType Directory -Path $GeminiPluginsDir -Force | Out-Null
}

if (Test-Path $SourcePluginDir) {
    Copy-Item -Path $SourcePluginDir -Destination $GeminiPluginsDir -Recurse -Force
    Write-Host "  Plugin deployed to: $TargetPluginDir" -ForegroundColor Green
} else {
    Write-Error "Source plugin directory not found at $SourcePluginDir"
    exit 1
}

# ------------------------------------------------------------------------------
# 4. Deploy Gmail & CaseToMD MCP Server Scripts
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/6] Deploying MCP server scripts (Gmail & CaseToMD)..." -ForegroundColor Yellow
$SourceGmailDir = Join-Path $ScriptDir "tools\gmail"
$SourceCaseToMdDir = Join-Path $ScriptDir "tools\casetomd"
$TargetCaseToMdDir = Join-Path $UserHome ".gemini\tools\casetomd"
$GmailDeploymentFiles = @(
    "gmail_broker_client.py",
    "gmail_broker_protocol.py",
    "gmail_broker_state.py",
    "gmail_brokerctl.py",
    "gmail_edge_broker.py",
    "gmail_edge_common.py",
    "gmail_edge_poc.py",
    "gmail_legacy_backend.py",
    "gmail_mcp_server.py",
    "gmail_playwright.py"
)

if (-not (Test-Path -LiteralPath $SourceGmailDir)) {
    Write-Error "Source Gmail directory not found at $SourceGmailDir"
    exit 1
}
foreach ($RequiredGmailFile in $GmailDeploymentFiles) {
    $SourceFile = Join-Path $SourceGmailDir $RequiredGmailFile
    if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) {
        Write-Error "Required Gmail deployment file not found at $SourceFile"
        exit 1
    }
}

if (-not (Test-Path $GeminiToolsDir)) {
    New-Item -ItemType Directory -Path $GeminiToolsDir -Force | Out-Null
}
if (-not (Test-Path $TargetCaseToMdDir)) {
    New-Item -ItemType Directory -Path $TargetCaseToMdDir -Force | Out-Null
}

$BrokerStopResult = Stop-RunningGmailBroker `
    -BrokerCtlPath $BrokerCtlPath `
    -StateFile $BrokerStateFile `
    -EdgeProfileDir $EdgeBrokerProfileDir
Write-Host "  Existing Gmail broker is stopped (control exit $($BrokerStopResult.exit_code))." -ForegroundColor Green

$LegacyProfileBaselineBefore = Get-ProfileBaseline -Path $LegacyProfileDir
$EdgeProfileBaselineBefore = Get-ProfileBaseline -Path $EdgeBrokerProfileDir

foreach ($GmailDeploymentFile in $GmailDeploymentFiles) {
    Copy-Item `
        -LiteralPath (Join-Path $SourceGmailDir $GmailDeploymentFile) `
        -Destination (Join-Path $GeminiToolsDir $GmailDeploymentFile) `
        -Force
}
Write-Host "  Gmail MCP scripts deployed to: $GeminiToolsDir" -ForegroundColor Green

$CaseToMdSourceFile = Join-Path $SourceCaseToMdDir "casetomd_mcp_bridge.py"
if (Test-Path -LiteralPath $CaseToMdSourceFile -PathType Leaf) {
    Copy-Item -LiteralPath $CaseToMdSourceFile -Destination $TargetCaseToMdDir -Force
    Write-Host "  CaseToMD MCP bridge deployed to: $TargetCaseToMdDir" -ForegroundColor Green
}

$LegacyProfileBaselineAfter = Get-ProfileBaseline -Path $LegacyProfileDir
$EdgeProfileBaselineAfter = Get-ProfileBaseline -Path $EdgeBrokerProfileDir
Assert-ProfileBaselineUnchanged `
    -Name "Legacy Gmail profile" `
    -Before $LegacyProfileBaselineBefore `
    -After $LegacyProfileBaselineAfter
Assert-ProfileBaselineUnchanged `
    -Name "Managed Edge broker profile" `
    -Before $EdgeProfileBaselineBefore `
    -After $EdgeProfileBaselineAfter

New-Item -ItemType Directory -Path $BrokerStateDir -Force | Out-Null
$AclPython = "import sys; sys.path.insert(0, sys.argv[1]); from gmail_broker_state import apply_windows_acl; apply_windows_acl(sys.argv[2])"
python -c $AclPython $GeminiToolsDir $BrokerStateDir
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to restrict the Gmail broker state directory ACL."
    exit 1
}
Write-Host "  Gmail broker state directory secured: $BrokerStateDir" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 5. Configure MCP Config (mcp_config.json) safely without overwriting other servers
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[5/6] Updating Antigravity MCP configuration ($McpConfigFile)..." -ForegroundColor Yellow

$GmailScriptPath = (Join-Path $GeminiToolsDir "gmail_mcp_server.py").Replace("\", "/")
$CaseToMdScriptPath = (Join-Path $TargetCaseToMdDir "casetomd_mcp_bridge.py").Replace("\", "/")

Update-McpConfiguration `
    -ConfigPath $McpConfigFile `
    -GmailScriptPath $GmailScriptPath `
    -CaseToMdScriptPath $CaseToMdScriptPath
Write-Host "  mcp_config.json updated successfully." -ForegroundColor Green

# ------------------------------------------------------------------------------
# 6. Start Broker and Authenticate Only When Required
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[6/6] Starting and validating the Gmail Edge broker..." -ForegroundColor Yellow
$InstalledBrokerScript = Join-Path $GeminiToolsDir "gmail_edge_broker.py"
$ExpectedBrokerBuildId = Get-InstalledBrokerBuildId -BrokerScriptPath $InstalledBrokerScript
$BrokerStatusOutput = @(python $BrokerCtlPath status)
$BrokerStatusExit = $LASTEXITCODE

if ($BrokerStatusExit -eq 0 -or $BrokerStatusExit -eq 10) {
    Assert-BrokerBuildId `
        -StatusOutput $BrokerStatusOutput `
        -ExpectedBuildId $ExpectedBrokerBuildId
    Write-Host "  Running broker build verified: $ExpectedBrokerBuildId" -ForegroundColor Green
}

if ($BrokerStatusExit -eq 10) {
    Write-Host "  Gmail authentication is required. Opening Managed Edge for SSO/MFA..." -ForegroundColor Cyan
    python $BrokerCtlPath login
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Gmail authentication was not completed; run python $BrokerCtlPath login before using Gmail tools."
    }
} elseif ($BrokerStatusExit -ne 0) {
    Write-Warning "Gmail broker is not ready; legacy rollback remains available."
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE SUCCESSFUL!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "You are all set! Restart Antigravity to load the new plugin & MCP servers." -ForegroundColor White
Write-Host "Example prompt: 'Provide a case review for SR 1-23659220672'" -ForegroundColor White
Write-Host ""
