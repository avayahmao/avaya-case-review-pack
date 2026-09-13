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
    param(
        [Parameter(Mandatory = $true)][string]$RuntimePackageRoot,
        [Parameter(Mandatory = $true)][string]$BridgeSourcePath,
        [Parameter(Mandatory = $true)][string]$PluginVersion
    )

    $BrokerModulePath = Join-Path $RuntimePackageRoot "gmail_edge_broker.py"
    $IdentityModulePath = Join-Path $RuntimePackageRoot "bridge_identity.py"
    if (-not (Test-Path -LiteralPath $BrokerModulePath -PathType Leaf)) {
        throw "Canonical Gmail broker runtime module is missing."
    }
    if (-not (Test-Path -LiteralPath $IdentityModulePath -PathType Leaf)) {
        throw "Canonical Gmail bridge identity runtime module is missing."
    }
    $BrokerSource = Get-Content -LiteralPath $BrokerModulePath -Raw -Encoding UTF8
    if (
        $BrokerSource -notmatch '(?m)^from \.bridge_identity import BROKER_BUILD_ID\s*$' -or
        $BrokerSource -notmatch 'build_id:\s*str\s*=\s*BROKER_BUILD_ID'
    ) {
        throw "Unable to determine the canonical Gmail broker build ID."
    }
    $IdentitySource = Get-Content -LiteralPath $IdentityModulePath -Raw -Encoding UTF8
    $CloudSource = Get-Content -LiteralPath $BridgeSourcePath -Raw -Encoding UTF8
    $ProtocolMatch = [regex]::Match($IdentitySource, '(?m)^BRIDGE_PROTOCOL_VERSION\s*=\s*(?<value>\d+)\s*$')
    $RevisionMatch = [regex]::Match($IdentitySource, '(?m)^CONTRACT_REVISION\s*=\s*(?<value>\d+)\s*$')
    $RuntimeDigestMatch = [regex]::Match($IdentitySource, '(?m)^BRIDGE_SOURCE_SHA256\s*=\s*"(?<value>[0-9a-f]{64})"\s*$')
    $CloudDigestMatch = [regex]::Match($CloudSource, '(?m)^var GMAIL_BRIDGE_SOURCE_SHA256 = "(?<value>[0-9a-f]{64})";$')
    if (
        -not $ProtocolMatch.Success -or
        -not $RevisionMatch.Success -or
        -not $RuntimeDigestMatch.Success -or
        -not $CloudDigestMatch.Success -or
        $RuntimeDigestMatch.Groups["value"].Value -cne $CloudDigestMatch.Groups["value"].Value
    ) {
        throw "Unable to determine the canonical Gmail broker build ID."
    }
    return "$PluginVersion-b$($ProtocolMatch.Groups['value'].Value)-r$($RevisionMatch.Groups['value'].Value)-$($RuntimeDigestMatch.Groups['value'].Value)"
}

function Get-GmailBrokerSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$StateFile,
        [Parameter(Mandatory = $true)][string]$PreferredControlPath,
        [Parameter(Mandatory = $true)][string]$FallbackControlPath
    )

    if (-not (Test-Path -LiteralPath $StateFile -PathType Leaf)) {
        return [pscustomobject]@{
            StatePresent = $false
            BuildId = ""
            ControlPath = $FallbackControlPath
        }
    }
    try {
        $State = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]::IsNullOrWhiteSpace([string]$State.build_id)) {
            throw "invalid"
        }
        return [pscustomobject]@{
            StatePresent = $true
            BuildId = [string]$State.build_id
            ControlPath = if (Test-Path -LiteralPath $PreferredControlPath -PathType Leaf) {
                $PreferredControlPath
            } else {
                $FallbackControlPath
            }
        }
    } catch {
        throw "Existing Gmail broker state is invalid; resolve it before installation."
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

function Get-InstalledRuntimeState {
    param(
        [Parameter(Mandatory = $true)][string]$PythonCommand,
        [Parameter(Mandatory = $true)][string]$RuntimeHelperPath,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Environment,
        [Parameter(Mandatory = $true)][string]$Stage
    )

    $Result = Invoke-BoundedCommand `
        -Stage $Stage `
        -Command $PythonCommand `
        -Arguments @($RuntimeHelperPath, "installed-version") `
        -TimeoutSeconds $TimeoutLocalSeconds `
        -Environment $Environment
    $State = ConvertFrom-CommandJson -Result $Result -Stage $Stage
    $InstalledProperty = $State.PSObject.Properties["installed"]
    if ($null -eq $InstalledProperty -or $InstalledProperty.Value -isnot [bool]) {
        throw "Stage '$Stage' returned an invalid runtime state."
    }
    if (
        [bool]$State.installed -and
        [string]::IsNullOrWhiteSpace([string]$State.version)
    ) {
        throw "Stage '$Stage' returned an invalid runtime state."
    }
    return $State
}

function Restore-RuntimePackage {
    param(
        [Parameter(Mandatory = $true)][string]$PythonCommand,
        [Parameter(Mandatory = $true)][string]$RuntimeHelperPath,
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Environment,
        [Parameter(Mandatory = $true)][bool]$PreviousPresent,
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$PreviousVersion,
        [AllowNull()][string]$PreviousWheel,
        [AllowNull()][string]$CurrentWheel,
        [Parameter(Mandatory = $true)][string]$CurrentVersion
    )

    if ($PreviousPresent) {
        $RestoreWheel = if ($PreviousVersion -ceq $CurrentVersion) {
            $CurrentWheel
        } else {
            $PreviousWheel
        }
        if ([string]::IsNullOrWhiteSpace([string]$RestoreWheel)) {
            throw "Stage 'runtime rollback wheel selection' failed."
        }
        $null = Invoke-BoundedCommand `
            -Stage "runtime rollback install" `
            -Command $PythonCommand `
            -Arguments @(
                "-m", "pip", "install", "--no-index", "--no-deps",
                "--force-reinstall", $RestoreWheel
            ) `
            -TimeoutSeconds $TimeoutPipSeconds `
            -Environment $Environment
    } else {
        $null = Invoke-BoundedCommand `
            -Stage "runtime rollback uninstall" `
            -Command $PythonCommand `
            -Arguments @(
                "-m", "pip", "uninstall", "--yes", "avaya-case-review-runtime"
            ) `
            -TimeoutSeconds $TimeoutPipSeconds `
            -Environment $Environment
    }

    $Restored = Get-InstalledRuntimeState `
        -PythonCommand $PythonCommand `
        -RuntimeHelperPath $RuntimeHelperPath `
        -Environment $Environment `
        -Stage "runtime rollback verification"
    if (
        [bool]$Restored.installed -ne $PreviousPresent -or
        ($PreviousPresent -and [string]$Restored.version -cne $PreviousVersion)
    ) {
        throw "Stage 'runtime rollback verification' failed."
    }
}

function Restore-DeploymentTarget {
    param(
        [Parameter(Mandatory = $true)][string]$TargetPath,
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [AllowEmptyString()][Parameter(Mandatory = $true)][string]$ExpectedBaseline
    )

    if (Test-Path -LiteralPath $TargetPath) {
        if (Test-Path -LiteralPath $TargetPath -PathType Container) {
            Remove-Item -LiteralPath $TargetPath -Recurse -Force
        } else {
            Remove-Item -LiteralPath $TargetPath -Force
        }
    }
    if (Test-Path -LiteralPath $BackupPath -PathType Container) {
        Copy-Item -LiteralPath $BackupPath -Destination $TargetPath -Recurse -Force
    } elseif (Test-Path -LiteralPath $BackupPath -PathType Leaf) {
        Copy-Item -LiteralPath $BackupPath -Destination $TargetPath -Force
    }

    $RestoredBaseline = Get-DeploymentPathBaseline -Path $TargetPath
    if (-not [string]::Equals(
        $ExpectedBaseline,
        [string]$RestoredBaseline,
        [StringComparison]::Ordinal
    )) {
        throw "Deployment target verification failed."
    }
}

function Invoke-DeploymentRecoveryStep {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [AllowEmptyCollection()][Parameter(Mandatory = $true)][System.Collections.Generic.List[string]]$Failures
    )

    try {
        & $Action
    } catch {
        [void]$Failures.Add("Stage '$Stage' failed.")
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
$RuntimeHelperPath = Join-Path $ScriptDir "tools\installer\runtime_package.py"
$PyProjectPath = Join-Path $ScriptDir "pyproject.toml"
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
    $CaseToMdSourceFile,
    $RuntimeHelperPath,
    $PyProjectPath
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
$PyProject = Get-Content -LiteralPath $PyProjectPath -Raw -Encoding UTF8
$ProjectVersion = [regex]::Match($PyProject, '(?m)^version\s*=\s*"([^"]+)"\s*$')
if (-not $ProjectVersion.Success -or $ProjectVersion.Groups[1].Value -cne $PluginVersion) {
    throw "Runtime package version does not match the Antigravity plugin version."
}
$ExpectedBrokerBuildId = Get-CanonicalBrokerBuildId `
    -RuntimePackageRoot $CanonicalRuntimePackageRoot `
    -BridgeSourcePath $BridgeSourcePath `
    -PluginVersion $PluginVersion

# ------------------------------------------------------------------------------
# 1. Validate Local Release and Python Environment
# ------------------------------------------------------------------------------
Write-Host "[1/6] Validating the local release and Python installation..." -ForegroundColor Yellow
$PythonCmd = Get-Command python -CommandType Application, ExternalScript -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $PythonCmd) {
    throw "Python was not found in PATH. Please install Python 3.10+ and add it to PATH."
}
$PythonCommand = [string]$PythonCmd.Path
$PythonVersionResult = Invoke-BoundedCommand `
    -Stage "Python version" `
    -Command $PythonCommand `
    -Arguments @("--version") `
    -TimeoutSeconds $TimeoutLocalSeconds `
    -Environment $BrokerEnvironment
Write-Host "  Found: $($PythonVersionResult.StdOut.Trim())" -ForegroundColor Green
Test-VersionAtLeast `
    -Actual ($PythonVersionResult.StdOut + $PythonVersionResult.StdErr) `
    -Minimum ([version]'3.10') `
    -Label 'Python'

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
    -TimeoutSeconds $TimeoutLocalSeconds `
    -Environment $BrokerEnvironment
Write-Host "  Release attestation validated." -ForegroundColor Green

# ------------------------------------------------------------------------------
# 2. Install and Verify the Packaged Runtime, Then Verify the Central Bridge
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/6] Preparing the packaged runtime and validating the Gmail Cloud Bridge..." -ForegroundColor Yellow
$env:PYTHONIOENCODING = "utf-8"
$InstalledRuntime = Get-InstalledRuntimeState `
    -PythonCommand $PythonCommand `
    -RuntimeHelperPath $RuntimeHelperPath `
    -Environment $BrokerEnvironment `
    -Stage "runtime version inspection"
$PreviousRuntimePresent = [bool]$InstalledRuntime.installed
$PreviousRuntimeVersion = if ($PreviousRuntimePresent) {
    [string]$InstalledRuntime.version
} else {
    ""
}
$WheelStore = Join-Path $LocalAppData "AvayaCaseReview\runtime-wheels"
$PreviousRuntimeWheel = $null
if ($PreviousRuntimePresent -and $PreviousRuntimeVersion -cne $PluginVersion) {
    $PriorWheels = @(
        Get-ChildItem `
            -LiteralPath $WheelStore `
            -Filter "avaya_case_review_runtime-$PreviousRuntimeVersion-*.whl" `
            -File `
            -ErrorAction SilentlyContinue
    )
    if ($PriorWheels.Count -ne 1) {
        throw "A retained wheel for the installed runtime version is required before upgrade."
    }
    $PreviousRuntimeWheel = $PriorWheels[0].FullName
    $null = Invoke-BoundedCommand `
        -Stage "prior runtime wheel validation" `
        -Command $PythonCommand `
        -Arguments @(
            $RuntimeHelperPath, "validate-wheel",
            "--wheel", $PreviousRuntimeWheel,
            "--version", $PreviousRuntimeVersion
        ) `
        -TimeoutSeconds $TimeoutLocalSeconds `
        -Environment $BrokerEnvironment
}

$PriorBroker = Get-GmailBrokerSnapshot `
    -StateFile $BrokerStateFile `
    -PreferredControlPath $BrokerCtlPath `
    -FallbackControlPath $SourceBrokerCtlPath
$RuntimeMutated = $false
$CurrentRuntimeWheel = $null
$RuntimeSmokeWorkDir = $null
$BackupRoot = $null
$PreserveBackup = $false
$PriorBrokerWasRunning = $false
$CandidateBrokerMayBeRunning = $false
$DeploymentStarted = $false
try {
    if ($SkipDependencyInstall) {
        if (-not $PreviousRuntimePresent -or $PreviousRuntimeVersion -cne $PluginVersion) {
            throw "-SkipDependencyInstall requires runtime version $PluginVersion to already be installed."
        }
    } else {
        $PipTrustedHosts = @(
            "--trusted-host", "pypi.org",
            "--trusted-host", "pypi.python.org",
            "--trusted-host", "files.pythonhosted.org"
        )
        $null = Invoke-BoundedCommand `
            -Stage "pip upgrade" `
            -Command $PythonCommand `
            -Arguments (@("-m", "pip", "install", "--upgrade", "pip", "--quiet") + $PipTrustedHosts) `
            -TimeoutSeconds $TimeoutPipSeconds `
            -Environment $BrokerEnvironment
        $null = Invoke-BoundedCommand `
            -Stage "dependency install" `
            -Command $PythonCommand `
            -Arguments (@(
                "-m", "pip", "install", "mcp", "playwright", "setuptools>=68", "--quiet"
            ) + $PipTrustedHosts) `
            -TimeoutSeconds $TimeoutPipSeconds `
            -Environment $BrokerEnvironment
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
                -Environment $BrokerEnvironment `
                -AllowFailure
        } finally {
            $env:NODE_TLS_REJECT_UNAUTHORIZED = $OldNodeTls
        }
        if ($PlaywrightResult.ExitCode -ne 0) {
            Write-Warning "Playwright Chromium installation failed; the legacy rollback backend may be unavailable."
        }

        New-Item -ItemType Directory -Path $WheelStore -Force | Out-Null
        $null = Invoke-BoundedCommand `
            -Stage "runtime wheel build" `
            -Command $PythonCommand `
            -Arguments @(
                "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                "--wheel-dir", $WheelStore, $ScriptDir
            ) `
            -TimeoutSeconds $TimeoutPipSeconds `
            -Environment $BrokerEnvironment
        $CurrentWheels = @(
            Get-ChildItem `
                -LiteralPath $WheelStore `
                -Filter "avaya_case_review_runtime-$PluginVersion-*.whl" `
                -File
        )
        if ($CurrentWheels.Count -ne 1) {
            throw "Stage 'runtime wheel discovery' did not find exactly one current runtime wheel."
        }
        $CurrentRuntimeWheel = $CurrentWheels[0].FullName
        $null = Invoke-BoundedCommand `
            -Stage "runtime wheel validation" `
            -Command $PythonCommand `
            -Arguments @(
                $RuntimeHelperPath, "validate-wheel",
                "--wheel", $CurrentRuntimeWheel,
                "--version", $PluginVersion
            ) `
            -TimeoutSeconds $TimeoutLocalSeconds `
            -Environment $BrokerEnvironment
        $RuntimeMutated = $true
        $null = Invoke-BoundedCommand `
            -Stage "runtime install" `
            -Command $PythonCommand `
            -Arguments @(
                "-m", "pip", "install", "--no-index", "--no-deps",
                "--force-reinstall", $CurrentRuntimeWheel
            ) `
            -TimeoutSeconds $TimeoutPipSeconds `
            -Environment $BrokerEnvironment
    }

    $RuntimeSmokeWorkDir = Join-Path `
        ([IO.Path]::GetTempPath()) `
        ("avaya-case-review-runtime-smoke-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $RuntimeSmokeWorkDir -Force | Out-Null
    $null = Invoke-BoundedCommand `
        -Stage "runtime smoke" `
        -Command $PythonCommand `
        -Arguments @(
            $RuntimeHelperPath, "smoke",
            "--python", $PythonCommand,
            "--work-dir", $RuntimeSmokeWorkDir
        ) `
        -TimeoutSeconds $TimeoutBridgeSeconds `
        -Environment $BrokerEnvironment

    if ($PriorBroker.StatePresent) {
        $PriorStopResult = Stop-RunningGmailBroker `
            -BrokerCtlPath $SourceBrokerCtlPath `
            -StateFile $BrokerStateFile `
            -EdgeProfileDir $EdgeBrokerProfileDir `
            -PythonCommand $PythonCommand `
            -BrokerEnvironment $BrokerEnvironment
        $PriorBrokerWasRunning = $PriorStopResult.exit_code -eq 0
    }

    $CandidateBrokerMayBeRunning = $true
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
        throw "Gmail Cloud Bridge preflight failed with exit code $($BridgeVerifyResult.ExitCode); deployed Antigravity files and configuration were not changed."
    }
    Write-Host "  Gmail Cloud Bridge is authenticated and compatible." -ForegroundColor Green

# ------------------------------------------------------------------------------
# 3. Stop the Verified Candidate Broker and Capture Deployment Backups
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/6] Preparing a reversible Antigravity deployment..." -ForegroundColor Yellow
$BrokerStopResult = $null
try {
    $BrokerStopResult = Stop-RunningGmailBroker `
        -BrokerCtlPath $SourceBrokerCtlPath `
        -StateFile $BrokerStateFile `
        -EdgeProfileDir $EdgeBrokerProfileDir `
        -PythonCommand $PythonCommand `
        -BrokerEnvironment $BrokerEnvironment
    $CandidateBrokerMayBeRunning = $false
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
        -TimeoutSeconds $TimeoutLocalSeconds `
        -Environment $BrokerEnvironment

    Write-Host "[5/6] Updating Antigravity MCP configuration ($McpConfigFile)..." -ForegroundColor Yellow
    $GmailScriptPath = (Join-Path $GeminiToolsDir "gmail_mcp_server.py").Replace("\", "/")
    $CaseToMdScriptPath = $CaseToMdTargetFile.Replace("\", "/")
    Update-McpConfiguration `
        -ConfigPath $McpConfigFile `
        -GmailScriptPath $GmailScriptPath `
        -CaseToMdScriptPath $CaseToMdScriptPath

    Write-Host "[6/6] Starting and validating the deployed Gmail Edge broker..." -ForegroundColor Yellow
    $CandidateBrokerMayBeRunning = $true
    $DeployedBridgeVerify = Invoke-BoundedCommand `
        -Stage "deployed Gmail bridge verification" `
        -Command $PythonCommand `
        -Arguments @(
            "-B", $BrokerCtlPath, "verify-bridge",
            "--source", $BridgeSourcePath,
            "--attestation", $BridgeAttestationPath,
            "--plugin-version", $PluginVersion
        ) `
        -TimeoutSeconds $TimeoutBridgeSeconds `
        -Environment $BrokerEnvironment `
        -AllowFailure
    if ($DeployedBridgeVerify.ExitCode -ne 0) {
        throw "Deployed Gmail bridge verification failed with exit code $($DeployedBridgeVerify.ExitCode)."
    }
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

    $ShimImportCode = "import importlib.util, sys; paths=sys.argv[1:]; [(lambda s: s.loader.exec_module(importlib.util.module_from_spec(s)))(importlib.util.spec_from_file_location('_avaya_deployed_shim_' + str(i), p)) for i, p in enumerate(paths)]"
    $PreviousProcessWorkingDirectory = [Environment]::CurrentDirectory
    Push-Location -LiteralPath $RuntimeSmokeWorkDir
    try {
        [Environment]::CurrentDirectory = $RuntimeSmokeWorkDir
        $null = Invoke-BoundedCommand `
            -Stage "deployed MCP shim import" `
            -Command $PythonCommand `
            -Arguments @(
                "-B", "-c", $ShimImportCode,
                (Join-Path $GeminiToolsDir "gmail_mcp_server.py"),
                $CaseToMdTargetFile
            ) `
            -TimeoutSeconds $TimeoutBridgeSeconds `
            -Environment $BrokerEnvironment
        $null = Invoke-BoundedCommand `
            -Stage "deployed broker shim help" `
            -Command $PythonCommand `
            -Arguments @("-B", $BrokerCtlPath, "--help") `
            -TimeoutSeconds $TimeoutBridgeSeconds `
            -Environment $BrokerEnvironment

        $FinalRuntime = Get-InstalledRuntimeState `
            -PythonCommand $PythonCommand `
            -RuntimeHelperPath $RuntimeHelperPath `
            -Environment $BrokerEnvironment `
            -Stage "final runtime verification"
        if (
            -not [bool]$FinalRuntime.installed -or
            [string]$FinalRuntime.version -cne $PluginVersion
        ) {
            throw "Stage 'final runtime verification' failed."
        }
    } finally {
        [Environment]::CurrentDirectory = $PreviousProcessWorkingDirectory
        Pop-Location
    }
} catch {
    throw $_
}
} catch {
    $RuntimePrimaryFailure = $_.Exception.Message
    $RecoveryFailures = New-Object System.Collections.Generic.List[string]
    if ($CandidateBrokerMayBeRunning) {
        Invoke-DeploymentRecoveryStep `
            -Stage "candidate Gmail broker stop" `
            -Failures $RecoveryFailures `
            -Action {
                $null = Stop-RunningGmailBroker `
                    -BrokerCtlPath $SourceBrokerCtlPath `
                    -StateFile $BrokerStateFile `
                    -EdgeProfileDir $EdgeBrokerProfileDir `
                    -PythonCommand $PythonCommand `
                    -BrokerEnvironment $BrokerEnvironment
                $CandidateBrokerMayBeRunning = $false
            }
    }
    if ($RuntimeMutated) {
        Invoke-DeploymentRecoveryStep `
            -Stage "runtime restoration" `
            -Failures $RecoveryFailures `
            -Action {
                Restore-RuntimePackage `
                    -PythonCommand $PythonCommand `
                    -RuntimeHelperPath $RuntimeHelperPath `
                    -Environment $BrokerEnvironment `
                    -PreviousPresent $PreviousRuntimePresent `
                    -PreviousVersion $PreviousRuntimeVersion `
                    -PreviousWheel $PreviousRuntimeWheel `
                    -CurrentWheel $CurrentRuntimeWheel `
                    -CurrentVersion $PluginVersion
            }
    }
    if ($DeploymentStarted) {
        Invoke-DeploymentRecoveryStep `
            -Stage "plugin restoration" `
            -Failures $RecoveryFailures `
            -Action {
                Restore-DeploymentTarget `
                    -TargetPath $TargetPluginDir `
                    -BackupPath $BackupPluginDir `
                    -ExpectedBaseline ([string]$DeploymentBaselines[$TargetPluginDir])
            }
        foreach ($GmailDeploymentFile in $GmailDeploymentFiles) {
            $TargetFile = Join-Path $GeminiToolsDir $GmailDeploymentFile
            $BackupFile = Join-Path $BackupGmailDir $GmailDeploymentFile
            Invoke-DeploymentRecoveryStep `
                -Stage "Gmail file restoration ($GmailDeploymentFile)" `
                -Failures $RecoveryFailures `
                -Action {
                    Restore-DeploymentTarget `
                        -TargetPath $TargetFile `
                        -BackupPath $BackupFile `
                        -ExpectedBaseline ([string]$DeploymentBaselines[$TargetFile])
                }
        }
        foreach ($GmailCloudDeploymentFile in $GmailCloudDeploymentFiles) {
            $TargetFile = Join-Path $TargetGmailCloudDir $GmailCloudDeploymentFile
            $BackupFile = Join-Path $BackupGmailCloudDir $GmailCloudDeploymentFile
            Invoke-DeploymentRecoveryStep `
                -Stage "Gmail cloud helper restoration ($GmailCloudDeploymentFile)" `
                -Failures $RecoveryFailures `
                -Action {
                    Restore-DeploymentTarget `
                        -TargetPath $TargetFile `
                        -BackupPath $BackupFile `
                        -ExpectedBaseline ([string]$DeploymentBaselines[$TargetFile])
                }
        }
        Invoke-DeploymentRecoveryStep `
            -Stage "CaseToMD shim restoration" `
            -Failures $RecoveryFailures `
            -Action {
                Restore-DeploymentTarget `
                    -TargetPath $CaseToMdTargetFile `
                    -BackupPath $BackupCaseFile `
                    -ExpectedBaseline ([string]$DeploymentBaselines[$CaseToMdTargetFile])
            }
        Invoke-DeploymentRecoveryStep `
            -Stage "MCP configuration restoration" `
            -Failures $RecoveryFailures `
            -Action {
                Restore-DeploymentTarget `
                    -TargetPath $McpConfigFile `
                    -BackupPath $BackupConfigFile `
                    -ExpectedBaseline ([string]$DeploymentBaselines[$McpConfigFile])
            }
    }
    if ($PriorBrokerWasRunning) {
        if ($RecoveryFailures.Count -eq 0) {
            Invoke-DeploymentRecoveryStep `
                -Stage "prior Gmail broker restart and verification" `
                -Failures $RecoveryFailures `
                -Action {
                    $PriorStart = Invoke-BoundedCommand `
                        -Stage "restored Gmail broker start" `
                        -Command $PythonCommand `
                        -Arguments @("-B", $PriorBroker.ControlPath, "start") `
                        -TimeoutSeconds $TimeoutBridgeSeconds `
                        -Environment $BrokerEnvironment `
                        -AllowFailure
                    if ($PriorStart.ExitCode -ne 0 -and $PriorStart.ExitCode -ne 10) {
                        throw "Restored Gmail broker start failed."
                    }
                    $PriorStatus = Invoke-BoundedCommand `
                        -Stage "restored Gmail broker status" `
                        -Command $PythonCommand `
                        -Arguments @("-B", $PriorBroker.ControlPath, "status") `
                        -TimeoutSeconds $TimeoutBridgeSeconds `
                        -Environment $BrokerEnvironment `
                        -AllowFailure
                    if ($PriorStatus.ExitCode -ne 0 -and $PriorStatus.ExitCode -ne 10) {
                        throw "Restored Gmail broker status failed."
                    }
                    Assert-BrokerBuildId `
                        -StatusOutput @($PriorStatus.StdOut -split "`r?`n") `
                        -ExpectedBuildId $PriorBroker.BuildId
                }
        } else {
            $RecoveryFailures.Add("prior broker restart skipped because prerequisite restoration failed")
        }
    }
    if ($RecoveryFailures.Count -gt 0) {
        $BackupStatus = "No usable deployment backup was created."
        if (
            -not [string]::IsNullOrWhiteSpace($BackupRoot) -and
            (Test-Path -LiteralPath $BackupRoot -PathType Container)
        ) {
            $PreserveBackup = $true
            $BackupStatus = "Deployment backup preserved at: $BackupRoot"
            Write-Host "RECOVERY_BACKUP=$BackupRoot"
        }
        throw "Antigravity installation failed: $RuntimePrimaryFailure Recovery status: failed ($($RecoveryFailures -join '; ')). $BackupStatus"
    }
    throw $RuntimePrimaryFailure
} finally {
    if (
        -not [string]::IsNullOrWhiteSpace($RuntimeSmokeWorkDir) -and
        (Test-Path -LiteralPath $RuntimeSmokeWorkDir)
    ) {
        Remove-Item -LiteralPath $RuntimeSmokeWorkDir -Recurse -Force -ErrorAction SilentlyContinue
    }
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
