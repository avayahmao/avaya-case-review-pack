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
    [string]$ConfigMigrationCaseToMdScript,
    [switch]$SkipDependencyInstall,
    [ValidateRange(1, 2147483)][int]$LoginTimeoutSeconds = 330,
    [string]$InstallUserHome,
    [string]$InstallLocalAppData
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$WindowsCommonPath = Join-Path $ScriptDir "tools\installer\windows_common.ps1"
if (-not (Test-Path -LiteralPath $WindowsCommonPath -PathType Leaf)) {
    throw "Required installer helper is missing: $WindowsCommonPath"
}
. $WindowsCommonPath

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

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $Stream = [IO.File]::OpenRead($Path)
    $Sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($Sha256.ComputeHash($Stream))).Replace("-", "")
    } finally {
        $Sha256.Dispose()
        $Stream.Dispose()
    }
}

function Get-ProfileBaseline {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return "[ABSENT]"
    }
    $ResolvedRoot = (Resolve-Path -LiteralPath $Path).Path.TrimEnd("\", "/")
    $Records = @(
        Get-ChildItem -LiteralPath $ResolvedRoot -Recurse -Force -File -ErrorAction SilentlyContinue |
            Sort-Object -Property FullName |
            ForEach-Object {
                $RelativePath = $_.FullName.Substring($ResolvedRoot.Length).TrimStart("\", "/")
                $Hash = try {
                    Get-FileSha256 -Path $_.FullName
                } catch {
                    "LOCKED"
                }
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

function Get-DeploymentPathBaseline {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return "[ABSENT]"
    }
    if (Test-Path -LiteralPath $Path -PathType Container) {
        return Get-ProfileBaseline -Path $Path
    }
    $File = Get-Item -LiteralPath $Path
    $Hash = Get-FileSha256 -Path $Path
    return "[FILE]|$($File.Length)|$Hash"
}

function Assert-DeploymentTarget {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$AllowedRoot
    )

    $FullPath = [IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    $FullRoot = [IO.Path]::GetFullPath($AllowedRoot).TrimEnd("\", "/")
    $RequiredPrefix = $FullRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $FullPath.StartsWith($RequiredPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify deployment target outside its expected root: $FullPath"
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
        [Parameter(Mandatory = $true)][string]$EdgeProfileDir,
        [Parameter(Mandatory = $true)][string]$PythonCommand,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$BrokerEnvironment
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
        $StopResult = Invoke-BoundedCommand `
            -Stage "Gmail broker stop" `
            -Command $PythonCommand `
            -Arguments @("-B", $BrokerCtlPath, "stop") `
            -TimeoutSeconds $TimeoutBridgeSeconds `
            -Environment $BrokerEnvironment `
            -AllowFailure
        $StopExit = $StopResult.ExitCode
        if (-not [string]::IsNullOrWhiteSpace($StopResult.StdOut)) {
            Write-Host "  Existing broker stop response: $($StopResult.StdOut.Trim())" -ForegroundColor DarkGray
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

function Get-CanonicalBrokerBuildId {
    param([Parameter(Mandatory = $true)][string]$RuntimePackageRoot)

    $BrokerModulePath = Join-Path $RuntimePackageRoot "gmail_edge_broker.py"
    if (-not (Test-Path -LiteralPath $BrokerModulePath -PathType Leaf)) {
        throw "Canonical Gmail broker runtime module is missing."
    }
    $BrokerSource = Get-Content -LiteralPath $BrokerModulePath -Raw -Encoding UTF8
    $BuildMatch = [regex]::Match(
        $BrokerSource,
        'build_id:\s*str\s*=\s*"(?<id>[A-Za-z0-9._-]+)"'
    )
    if (-not $BuildMatch.Success) {
        throw "Unable to determine the canonical Gmail broker build ID."
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

$UserHome = if ([string]::IsNullOrWhiteSpace($InstallUserHome)) {
    $env:USERPROFILE
} else {
    [IO.Path]::GetFullPath($InstallUserHome)
}
$GeminiConfigDir = Join-Path $UserHome ".gemini\config"
$GeminiPluginsDir = Join-Path $GeminiConfigDir "plugins"
$GeminiToolsDir = Join-Path $UserHome ".gemini\tools\gmail"
$McpConfigFile = Join-Path $GeminiConfigDir "mcp_config.json"
$LocalAppData = if (-not [string]::IsNullOrWhiteSpace($InstallLocalAppData)) {
    [IO.Path]::GetFullPath($InstallLocalAppData)
} elseif ($env:LOCALAPPDATA) {
    $env:LOCALAPPDATA
} else {
    Join-Path $UserHome "AppData\Local"
}
$BrokerStateDir = Join-Path $LocalAppData "AvayaCaseReview\gmail-broker"
$BrokerStateFile = Join-Path $BrokerStateDir "state.json"
$LegacyProfileDir = Join-Path $GeminiToolsDir "chrome_profile"
$EdgeBrokerProfileDir = Join-Path $GeminiToolsDir "edge_broker_profile"
$BrokerCtlPath = Join-Path $GeminiToolsDir "gmail_brokerctl.py"
$BrokerEnvironment = @{
    "USERPROFILE" = $UserHome
    "LOCALAPPDATA" = $LocalAppData
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Avaya Case Review Manager Suite — Environment Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Source and destination paths are resolved before preflight, but no deployed
# plugin, MCP script, configuration, or broker state is changed until every
# local and live compatibility gate has passed.
$SourcePluginDir = Join-Path $ScriptDir "plugins\avaya-case-review"
$SourceGmailDir = Join-Path $ScriptDir "tools\gmail"
$SourceGmailCloudDir = Join-Path $SourceGmailDir "cloud"
$SourceCaseToMdDir = Join-Path $ScriptDir "tools\casetomd"
$CanonicalRuntimePackageRoot = Join-Path $ScriptDir "avaya_case_review_runtime"
$SourceBrokerCtlPath = Join-Path $SourceGmailDir "gmail_brokerctl.py"
$BridgeSourcePath = Join-Path $SourceGmailDir "cloud\GmailMcpBridge.gs"
$BridgeIdentityPath = Join-Path $SourceGmailDir "cloud\bridge_identity.py"
$BridgeAttestationPath = Join-Path $SourceGmailDir "cloud\bridge_release_attestation.json"
$PluginManifestPath = Join-Path $SourcePluginDir "plugin.json"
$TargetPluginDir = Join-Path $GeminiPluginsDir "avaya-case-review"
$TargetGmailCloudDir = Join-Path $GeminiToolsDir "cloud"
$TargetCaseToMdDir = Join-Path $UserHome ".gemini\tools\casetomd"
$CaseToMdSourceFile = Join-Path $SourceCaseToMdDir "casetomd_mcp_bridge.py"
$CaseToMdTargetFile = Join-Path $TargetCaseToMdDir "casetomd_mcp_bridge.py"
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
$GmailCloudDeploymentFiles = @(
    "bridge_identity.py"
)

foreach ($RequiredPath in @(
    $SourcePluginDir,
    $SourceGmailDir,
    $CanonicalRuntimePackageRoot,
    $PluginManifestPath,
    $SourceBrokerCtlPath,
    $BridgeSourcePath,
    $BridgeIdentityPath,
    $BridgeAttestationPath,
    $CaseToMdSourceFile
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required installation source is missing: $RequiredPath"
    }
}
foreach ($RequiredGmailFile in $GmailDeploymentFiles) {
    $SourceFile = Join-Path $SourceGmailDir $RequiredGmailFile
    if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) {
        throw "Required Gmail deployment file is missing: $SourceFile"
    }
}
foreach ($RequiredCloudFile in $GmailCloudDeploymentFiles) {
    $SourceFile = Join-Path $SourceGmailCloudDir $RequiredCloudFile
    if (-not (Test-Path -LiteralPath $SourceFile -PathType Leaf)) {
        throw "Required Gmail cloud helper is missing: $SourceFile"
    }
}

$PluginManifest = Get-Content -LiteralPath $PluginManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$PluginVersion = [string]$PluginManifest.version
if ([string]::IsNullOrWhiteSpace($PluginVersion)) {
    throw "Antigravity plugin version is missing."
}
$ExpectedBrokerBuildId = Get-CanonicalBrokerBuildId `
    -RuntimePackageRoot $CanonicalRuntimePackageRoot

# ------------------------------------------------------------------------------
# 1. Validate Local Release and Python Environment
# ------------------------------------------------------------------------------
Write-Host "[1/6] Validating the local release and Python installation..." -ForegroundColor Yellow
$PythonCmd = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $PythonCmd) {
    throw "Python was not found in PATH. Please install Python 3.10+ and add it to PATH."
}
$PythonCommand = [string]$PythonCmd.Path
$PythonVersionResult = Invoke-BoundedCommand `
    -Stage "Python version" `
    -Command $PythonCommand `
    -Arguments @("--version") `
    -TimeoutSeconds $TimeoutLocalSeconds
Write-Host "  Found: $($PythonVersionResult.StdOut.Trim())" -ForegroundColor Green

$null = Invoke-BoundedCommand `
    -Stage "validate release attestation" `
    -Command $PythonCommand `
    -Arguments @(
        $BridgeIdentityPath,
        "validate",
        "--source", $BridgeSourcePath,
        "--attestation", $BridgeAttestationPath,
        "--plugin-version", $PluginVersion
    ) `
    -TimeoutSeconds $TimeoutLocalSeconds
Write-Host "  Release attestation validated." -ForegroundColor Green

# ------------------------------------------------------------------------------
# 2. Install Dependencies and Verify the Central Bridge
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/6] Preparing dependencies and validating the Gmail Cloud Bridge..." -ForegroundColor Yellow
$env:PYTHONIOENCODING = "utf-8"
if (-not $SkipDependencyInstall) {
    $PipTrustedHosts = @(
        "--trusted-host", "pypi.org",
        "--trusted-host", "pypi.python.org",
        "--trusted-host", "files.pythonhosted.org"
    )
    $null = Invoke-BoundedCommand `
        -Stage "pip upgrade" `
        -Command $PythonCommand `
        -Arguments (@("-m", "pip", "install", "--upgrade", "pip", "--quiet") + $PipTrustedHosts) `
        -TimeoutSeconds $TimeoutPipSeconds
    $null = Invoke-BoundedCommand `
        -Stage "pip install" `
        -Command $PythonCommand `
        -Arguments (@("-m", "pip", "install", "mcp", "playwright", "--quiet") + $PipTrustedHosts) `
        -TimeoutSeconds $TimeoutPipSeconds
    Write-Host "  Python packages installed successfully." -ForegroundColor Green

    $OldNodeTls = $env:NODE_TLS_REJECT_UNAUTHORIZED
    try {
        if (-not $env:NODE_EXTRA_CA_CERTS) {
            $env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
        }
        $PlaywrightResult = Invoke-BoundedCommand `
            -Stage "playwright install" `
            -Command $PythonCommand `
            -Arguments @("-m", "playwright", "install", "chromium") `
            -TimeoutSeconds $TimeoutPipSeconds `
            -AllowFailure
    } finally {
        $env:NODE_TLS_REJECT_UNAUTHORIZED = $OldNodeTls
    }
    if ($PlaywrightResult.ExitCode -ne 0) {
        Write-Warning "Playwright Chromium installation failed; the legacy rollback backend may be unavailable."
    }
}

$BridgeVerifyResult = Invoke-BoundedCommand `
    -Stage "verify-bridge" `
    -Command $PythonCommand `
    -Arguments @(
        "-B", $SourceBrokerCtlPath, "verify-bridge",
        "--source", $BridgeSourcePath,
        "--attestation", $BridgeAttestationPath,
        "--plugin-version", $PluginVersion
    ) `
    -TimeoutSeconds $TimeoutBridgeSeconds `
    -Environment $BrokerEnvironment `
    -AllowFailure
if ($BridgeVerifyResult.ExitCode -eq 10) {
    Write-Host "  Gmail authentication is required. Waiting for Managed Edge SSO/MFA..." -ForegroundColor Cyan
    $null = Invoke-BoundedCommand `
        -Stage "Gmail broker login" `
        -Command $PythonCommand `
        -Arguments @("-B", $SourceBrokerCtlPath, "login") `
        -TimeoutSeconds $LoginTimeoutSeconds `
        -Environment $BrokerEnvironment
    $BridgeVerifyResult = Invoke-BoundedCommand `
        -Stage "verify-bridge retry" `
        -Command $PythonCommand `
        -Arguments @(
            "-B", $SourceBrokerCtlPath, "verify-bridge",
            "--source", $BridgeSourcePath,
            "--attestation", $BridgeAttestationPath,
            "--plugin-version", $PluginVersion
        ) `
        -TimeoutSeconds $TimeoutBridgeSeconds `
        -Environment $BrokerEnvironment `
        -AllowFailure
}
if ($BridgeVerifyResult.ExitCode -ne 0) {
    throw "Gmail Cloud Bridge preflight failed with exit code $($BridgeVerifyResult.ExitCode); deployed Antigravity state was not changed."
}
Write-Host "  Gmail Cloud Bridge is authenticated and compatible." -ForegroundColor Green

# ------------------------------------------------------------------------------
# 3. Stop the Verified Source Broker and Capture Deployment Backups
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/6] Preparing a reversible Antigravity deployment..." -ForegroundColor Yellow
$BrokerStopResult = $null
$BrokerWasStopped = $false
$BackupRoot = $null
$PreserveBackup = $false
$DeploymentStarted = $false
try {
    $BrokerStopResult = Stop-RunningGmailBroker `
        -BrokerCtlPath $SourceBrokerCtlPath `
        -StateFile $BrokerStateFile `
        -EdgeProfileDir $EdgeBrokerProfileDir `
        -PythonCommand $PythonCommand `
        -BrokerEnvironment $BrokerEnvironment
    $BrokerWasStopped = $BrokerStopResult.exit_code -eq 0
    Write-Host "  Verified source broker is stopped (control exit $($BrokerStopResult.exit_code))." -ForegroundColor Green

    $LegacyProfileBaselineBefore = Get-ProfileBaseline -Path $LegacyProfileDir
    $EdgeProfileBaselineBefore = Get-ProfileBaseline -Path $EdgeBrokerProfileDir
    $BackupRoot = Join-Path ([IO.Path]::GetTempPath()) ("avaya-case-review-deploy-" + [guid]::NewGuid().ToString("N"))
    $BackupPluginDir = Join-Path $BackupRoot "plugin"
    $BackupGmailDir = Join-Path $BackupRoot "gmail"
    $BackupGmailCloudDir = Join-Path $BackupGmailDir "cloud"
    $BackupCaseFile = Join-Path $BackupRoot "casetomd_mcp_bridge.py"
    $BackupConfigFile = Join-Path $BackupRoot "mcp_config.json"
    $DeploymentBaselines = @{}
    $DeploymentBackups = @{}
    $DeploymentBaselines[$TargetPluginDir] = Get-DeploymentPathBaseline -Path $TargetPluginDir
    $DeploymentBackups[$TargetPluginDir] = $BackupPluginDir
    $DeploymentBaselines[$CaseToMdTargetFile] = Get-DeploymentPathBaseline -Path $CaseToMdTargetFile
    $DeploymentBackups[$CaseToMdTargetFile] = $BackupCaseFile
    $DeploymentBaselines[$McpConfigFile] = Get-DeploymentPathBaseline -Path $McpConfigFile
    $DeploymentBackups[$McpConfigFile] = $BackupConfigFile
    foreach ($GmailDeploymentFile in $GmailDeploymentFiles) {
        $TargetFile = Join-Path $GeminiToolsDir $GmailDeploymentFile
        $DeploymentBaselines[$TargetFile] = Get-DeploymentPathBaseline -Path $TargetFile
        $DeploymentBackups[$TargetFile] = Join-Path $BackupGmailDir $GmailDeploymentFile
    }
    foreach ($GmailCloudDeploymentFile in $GmailCloudDeploymentFiles) {
        $TargetFile = Join-Path $TargetGmailCloudDir $GmailCloudDeploymentFile
        $DeploymentBaselines[$TargetFile] = Get-DeploymentPathBaseline -Path $TargetFile
        $DeploymentBackups[$TargetFile] = Join-Path $BackupGmailCloudDir $GmailCloudDeploymentFile
    }

    New-Item -ItemType Directory -Path $BackupGmailCloudDir -Force | Out-Null
    if (Test-Path -LiteralPath $TargetPluginDir -PathType Container) {
        Copy-Item -LiteralPath $TargetPluginDir -Destination $BackupPluginDir -Recurse -Force
    }
    foreach ($GmailDeploymentFile in $GmailDeploymentFiles) {
        $TargetFile = Join-Path $GeminiToolsDir $GmailDeploymentFile
        if (Test-Path -LiteralPath $TargetFile -PathType Leaf) {
            Copy-Item -LiteralPath $TargetFile -Destination (Join-Path $BackupGmailDir $GmailDeploymentFile) -Force
        }
    }
    foreach ($GmailCloudDeploymentFile in $GmailCloudDeploymentFiles) {
        $TargetFile = Join-Path $TargetGmailCloudDir $GmailCloudDeploymentFile
        if (Test-Path -LiteralPath $TargetFile -PathType Leaf) {
            Copy-Item -LiteralPath $TargetFile -Destination (Join-Path $BackupGmailCloudDir $GmailCloudDeploymentFile) -Force
        }
    }
    if (Test-Path -LiteralPath $CaseToMdTargetFile -PathType Leaf) {
        Copy-Item -LiteralPath $CaseToMdTargetFile -Destination $BackupCaseFile -Force
    }
    if (Test-Path -LiteralPath $McpConfigFile -PathType Leaf) {
        Copy-Item -LiteralPath $McpConfigFile -Destination $BackupConfigFile -Force
    }
    foreach ($TargetPath in $DeploymentBaselines.Keys) {
        $BackupBaseline = Get-DeploymentPathBaseline -Path $DeploymentBackups[$TargetPath]
        if (-not [string]::Equals(
            [string]$DeploymentBaselines[$TargetPath],
            [string]$BackupBaseline,
            [StringComparison]::Ordinal
        )) {
            throw "Backup verification failed before deployment for target: $TargetPath"
        }
    }

    # --------------------------------------------------------------------------
    # 4-6. Commit Plugin, MCP, and Configuration Changes; Verify the New Broker
    # --------------------------------------------------------------------------
    Assert-DeploymentTarget -Path $TargetPluginDir -AllowedRoot $GeminiPluginsDir
    Assert-DeploymentTarget -Path $CaseToMdTargetFile -AllowedRoot $TargetCaseToMdDir
    Assert-DeploymentTarget -Path $McpConfigFile -AllowedRoot $GeminiConfigDir
    foreach ($GmailDeploymentFile in $GmailDeploymentFiles) {
        Assert-DeploymentTarget `
            -Path (Join-Path $GeminiToolsDir $GmailDeploymentFile) `
            -AllowedRoot $GeminiToolsDir
    }
    foreach ($GmailCloudDeploymentFile in $GmailCloudDeploymentFiles) {
        Assert-DeploymentTarget `
            -Path (Join-Path $TargetGmailCloudDir $GmailCloudDeploymentFile) `
            -AllowedRoot $GeminiToolsDir
    }
    $DeploymentStarted = $true

    Write-Host "[4/6] Deploying Avaya Case Review plugin and MCP files..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $GeminiPluginsDir -Force | Out-Null
    if (Test-Path -LiteralPath $TargetPluginDir) {
        Remove-Item -LiteralPath $TargetPluginDir -Recurse -Force
    }
    Copy-Item -LiteralPath $SourcePluginDir -Destination $TargetPluginDir -Recurse -Force

    New-Item -ItemType Directory -Path $GeminiToolsDir -Force | Out-Null
    foreach ($GmailDeploymentFile in $GmailDeploymentFiles) {
        Copy-Item `
            -LiteralPath (Join-Path $SourceGmailDir $GmailDeploymentFile) `
            -Destination (Join-Path $GeminiToolsDir $GmailDeploymentFile) `
            -Force
    }
    New-Item -ItemType Directory -Path $TargetGmailCloudDir -Force | Out-Null
    foreach ($GmailCloudDeploymentFile in $GmailCloudDeploymentFiles) {
        Copy-Item `
            -LiteralPath (Join-Path $SourceGmailCloudDir $GmailCloudDeploymentFile) `
            -Destination (Join-Path $TargetGmailCloudDir $GmailCloudDeploymentFile) `
            -Force
    }
    New-Item -ItemType Directory -Path $TargetCaseToMdDir -Force | Out-Null
    Copy-Item -LiteralPath $CaseToMdSourceFile -Destination $CaseToMdTargetFile -Force

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
    $null = Invoke-BoundedCommand `
        -Stage "secure Gmail broker state" `
        -Command $PythonCommand `
        -Arguments @("-B", "-c", $AclPython, $GeminiToolsDir, $BrokerStateDir) `
        -TimeoutSeconds $TimeoutLocalSeconds

    Write-Host "[5/6] Updating Antigravity MCP configuration ($McpConfigFile)..." -ForegroundColor Yellow
    $GmailScriptPath = (Join-Path $GeminiToolsDir "gmail_mcp_server.py").Replace("\", "/")
    $CaseToMdScriptPath = $CaseToMdTargetFile.Replace("\", "/")
    Update-McpConfiguration `
        -ConfigPath $McpConfigFile `
        -GmailScriptPath $GmailScriptPath `
        -CaseToMdScriptPath $CaseToMdScriptPath

    Write-Host "[6/6] Starting and validating the deployed Gmail Edge broker..." -ForegroundColor Yellow
    $BrokerStatus = Invoke-BoundedCommand `
        -Stage "deployed Gmail broker status" `
        -Command $PythonCommand `
        -Arguments @("-B", $BrokerCtlPath, "status") `
        -TimeoutSeconds $TimeoutBridgeSeconds `
        -Environment $BrokerEnvironment `
        -AllowFailure
    if ($BrokerStatus.ExitCode -ne 0) {
        throw "Deployed Gmail broker validation failed with exit code $($BrokerStatus.ExitCode)."
    }
    Assert-BrokerBuildId `
        -StatusOutput @($BrokerStatus.StdOut -split "`r?`n") `
        -ExpectedBuildId $ExpectedBrokerBuildId
    Write-Host "  Running broker build verified: $ExpectedBrokerBuildId" -ForegroundColor Green
} catch {
    $PrimaryFailure = $_
    try {
        if ($DeploymentStarted) {
            if (Test-Path -LiteralPath $TargetPluginDir) {
                Remove-Item -LiteralPath $TargetPluginDir -Recurse -Force
            }
            if (Test-Path -LiteralPath $BackupPluginDir -PathType Container) {
                Copy-Item -LiteralPath $BackupPluginDir -Destination $TargetPluginDir -Recurse -Force
            }
            foreach ($GmailDeploymentFile in $GmailDeploymentFiles) {
                $TargetFile = Join-Path $GeminiToolsDir $GmailDeploymentFile
                $BackupFile = Join-Path $BackupGmailDir $GmailDeploymentFile
                if (Test-Path -LiteralPath $TargetFile) {
                    Remove-Item -LiteralPath $TargetFile -Force
                }
                if (Test-Path -LiteralPath $BackupFile -PathType Leaf) {
                    Copy-Item -LiteralPath $BackupFile -Destination $TargetFile -Force
                }
            }
            foreach ($GmailCloudDeploymentFile in $GmailCloudDeploymentFiles) {
                $TargetFile = Join-Path $TargetGmailCloudDir $GmailCloudDeploymentFile
                $BackupFile = Join-Path $BackupGmailCloudDir $GmailCloudDeploymentFile
                if (Test-Path -LiteralPath $TargetFile) {
                    Remove-Item -LiteralPath $TargetFile -Force
                }
                if (Test-Path -LiteralPath $BackupFile -PathType Leaf) {
                    Copy-Item -LiteralPath $BackupFile -Destination $TargetFile -Force
                }
            }
            if (Test-Path -LiteralPath $CaseToMdTargetFile) {
                Remove-Item -LiteralPath $CaseToMdTargetFile -Force
            }
            if (Test-Path -LiteralPath $BackupCaseFile -PathType Leaf) {
                Copy-Item -LiteralPath $BackupCaseFile -Destination $CaseToMdTargetFile -Force
            }
            if (Test-Path -LiteralPath $McpConfigFile) {
                Remove-Item -LiteralPath $McpConfigFile -Force
            }
            if (Test-Path -LiteralPath $BackupConfigFile -PathType Leaf) {
                Copy-Item -LiteralPath $BackupConfigFile -Destination $McpConfigFile -Force
            }
            foreach ($TargetPath in $DeploymentBaselines.Keys) {
                $RestoredBaseline = Get-DeploymentPathBaseline -Path $TargetPath
                if (-not [string]::Equals(
                    [string]$DeploymentBaselines[$TargetPath],
                    [string]$RestoredBaseline,
                    [StringComparison]::Ordinal
                )) {
                    throw "Backup verification failed for restored target: $TargetPath"
                }
            }
        }
        if ($BrokerWasStopped -and (Test-Path -LiteralPath $BrokerCtlPath -PathType Leaf)) {
            $null = Invoke-BoundedCommand `
                -Stage "restored Gmail broker start" `
                -Command $PythonCommand `
                -Arguments @("-B", $BrokerCtlPath, "start") `
                -TimeoutSeconds $TimeoutBridgeSeconds `
                -Environment $BrokerEnvironment
        }
    } catch {
        $RecoveryFailure = $_
        $BackupStatus = "No usable backup was created."
        if (
            -not [string]::IsNullOrWhiteSpace($BackupRoot) -and
            (Test-Path -LiteralPath $BackupRoot -PathType Container)
        ) {
            $PreserveBackup = $true
            $BackupStatus = "Backup preserved at: $BackupRoot"
            Write-Host "RECOVERY_BACKUP=$BackupRoot"
        }
        throw "Antigravity deployment failed: $($PrimaryFailure.Exception.Message) Recovery status: failed ($($RecoveryFailure.Exception.Message)). $BackupStatus"
    }
    throw $PrimaryFailure
} finally {
    if (
        -not $PreserveBackup -and
        -not [string]::IsNullOrWhiteSpace($BackupRoot) -and
        (Test-Path -LiteralPath $BackupRoot)
    ) {
        Remove-Item -LiteralPath $BackupRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE SUCCESSFUL!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "You are all set! Restart Antigravity to load the new plugin & MCP servers." -ForegroundColor White
Write-Host "Example prompt: 'Provide a case review for SR 1-23659220672'" -ForegroundColor White
Write-Host ""
