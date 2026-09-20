[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepositoryRoot,
    [Parameter(Mandatory = $true)][string]$MarketplaceRef,
    [Parameter(Mandatory = $true)][string]$BridgeAttestationPath,
    [switch]$Automated
)

$ErrorActionPreference = "Stop"

if (-not $Automated) {
    throw "This clean-profile smoke harness is automated-only. Supply -Automated so no production Python, Codex profile, broker, Gmail, or CaseToMD service is used."
}

$ResolvedRepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$ResolvedAttestationPath = (Resolve-Path -LiteralPath $BridgeAttestationPath).Path
if (-not (Test-Path -LiteralPath $ResolvedRepositoryRoot -PathType Container)) {
    throw "RepositoryRoot must resolve to a directory."
}
if (-not (Test-Path -LiteralPath $ResolvedAttestationPath -PathType Leaf)) {
    throw "BridgeAttestationPath must resolve to a file."
}
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ("avaya-codex-clean-profile-" + [guid]::NewGuid().ToString("N"))
$TestCodexHome = Join-Path $TestRoot ".codex"
$PreviousCodexHome = $env:CODEX_HOME
$PreviousLocalAppData = $env:LOCALAPPDATA
$PreviousPath = $env:PATH
$PreviousPythonPath = $env:PYTHONPATH
$PreviousCleanProfileEnvironment = @{}
Get-ChildItem Env: | Where-Object { $_.Name -like "AVAYA_CLEAN_PROFILE_*" } | ForEach-Object {
    $PreviousCleanProfileEnvironment[$_.Name] = $_.Value
}
$RealPythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $RealPythonCommand) {
    throw "A real Python application is required for the isolated runtime handshake."
}
$RealPythonPath = [string]$RealPythonCommand.Path
$FixtureRepository = Join-Path $TestRoot "repository"
$AdapterRoot = Join-Path $TestRoot "adapters"
$RuntimeTarget = Join-Path $TestRoot "runtime-target"
$HandshakeWorkDirectory = Join-Path $TestRoot "unrelated-working-directory"
$StatePath = Join-Path $TestRoot "state.json"
$InstallerLog = Join-Path $TestRoot "installer.log"
$Summary = $null
$FixtureFiles = @()

function Assert-NoReparsePointComponent {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Entry
    )

    $CurrentPath = $Root
    foreach ($Segment in $Entry.Split('/')) {
        $CurrentPath = Join-Path $CurrentPath $Segment
        if (-not (Test-Path -LiteralPath $CurrentPath)) {
            continue
        }
        $Item = Get-Item -LiteralPath $CurrentPath -Force
        if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq [IO.FileAttributes]::ReparsePoint) {
            throw "Release manifest path contains a reparse point: $Entry"
        }
    }
}

function Get-ReleaseManifestFiles {
    param([Parameter(Mandatory = $true)][string]$Root)

    $ManifestPath = Join-Path $Root "release-manifest.txt"
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "The clean-profile source does not contain release-manifest.txt."
    }

    $RootPrefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $Seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $Files = @()
    foreach ($RawLine in Get-Content -LiteralPath $ManifestPath -Encoding UTF8) {
        $Entry = $RawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($Entry) -or $Entry.StartsWith("#")) {
            continue
        }
        $Segments = @($Entry.Split('/'))
        if (
            [IO.Path]::IsPathRooted($Entry) -or
            $Entry.Contains("\") -or
            $Segments -contains ".." -or
            $Segments -contains "." -or
            $Segments -contains "" -or
            -not $Seen.Add($Entry)
        ) {
            throw "Release manifest contains an unsafe or duplicate path."
        }

        $SourcePath = [IO.Path]::GetFullPath((Join-Path $Root ($Entry.Replace('/', [IO.Path]::DirectorySeparatorChar))))
        if (-not $SourcePath.StartsWith($RootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Release manifest path resolves outside RepositoryRoot."
        }
        Assert-NoReparsePointComponent -Root $Root -Entry $Entry
        if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
            throw "Release manifest path is missing or is not a file: $Entry"
        }
        $ResolvedSourcePath = (Resolve-Path -LiteralPath $SourcePath).Path
        if (-not $ResolvedSourcePath.StartsWith($RootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Release manifest source resolves outside RepositoryRoot."
        }
        $Files += [pscustomobject]@{ Entry = $Entry; Source = $ResolvedSourcePath }
    }
    return $Files
}

function Copy-ReleaseManifestFiles {
    param(
        [Parameter(Mandatory = $true)][object[]]$Files,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    foreach ($File in $Files) {
        $DestinationPath = Join-Path $DestinationRoot ([string]$File.Entry).Replace('/', [IO.Path]::DirectorySeparatorChar)
        $DestinationParent = Split-Path -Parent $DestinationPath
        if (-not (Test-Path -LiteralPath $DestinationParent -PathType Container)) {
            New-Item -ItemType Directory -Path $DestinationParent -Force | Out-Null
        }
        Copy-Item -LiteralPath ([string]$File.Source) -Destination $DestinationPath -Force
    }
}

function Set-SmokeTextFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Text
    )

    [IO.File]::WriteAllText(
        $Path,
        $Text.Replace("`r`n", "`n").Replace("`n", "`r`n"),
        (New-Object System.Text.UTF8Encoding($true))
    )
}

function Write-SmokeAdapters {
    param([Parameter(Mandatory = $true)][string]$Path)

    $CodexAdapter = @'
function Read-State { Get-Content -LiteralPath $env:AVAYA_CLEAN_PROFILE_STATE -Raw -Encoding UTF8 | ConvertFrom-Json }
function Write-State($State) { $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $env:AVAYA_CLEAN_PROFILE_STATE -Encoding UTF8 }
function Assert-TestProfile {
    if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME) -or $env:CODEX_HOME -ne $env:AVAYA_CLEAN_PROFILE_CODEX_HOME) { exit 71 }
}
Assert-TestProfile
$State = Read-State
if ($args.Count -eq 1 -and $args[0] -eq "--version") { "codex-cli 0.153.4"; exit 0 }
if ($args.Count -ge 4 -and $args[0] -eq "plugin" -and $args[1] -eq "marketplace" -and $args[2] -eq "list") {
    if ($State.marketplace_installed) {
        [pscustomobject]@{ marketplaces = @([pscustomobject]@{ name = "avaya-case-review-pack"; root = $State.marketplace_root; marketplaceSource = [pscustomobject]@{ sourceType = "local"; source = $State.marketplace_root } }) } | ConvertTo-Json -Depth 8
    } else { '{"marketplaces":[]}' }
    exit 0
}
if ($args.Count -ge 3 -and $args[0] -eq "plugin" -and $args[1] -eq "list") {
    $Installed = @()
    if ($State.plugin_installed) { $Installed = @([pscustomobject]@{ pluginId = "avaya-case-review@avaya-case-review-pack"; name = "avaya-case-review"; marketplaceName = "avaya-case-review-pack"; version = $State.plugin_version; installed = $true; enabled = $true }) }
    [pscustomobject]@{ installed = $Installed; available = @() } | ConvertTo-Json -Depth 8
    exit 0
}
if ($args.Count -ge 4 -and $args[0] -eq "plugin" -and $args[1] -eq "marketplace" -and $args[2] -eq "add") { $State.marketplace_installed = $true; Write-State $State; exit 0 }
if ($args.Count -ge 3 -and $args[0] -eq "plugin" -and $args[1] -eq "add") { if (-not $State.marketplace_installed) { exit 72 }; $State.plugin_installed = $true; Write-State $State; exit 0 }
if ($args.Count -ge 4 -and $args[0] -eq "mcp" -and $args[1] -eq "get") {
    $Name = [string]$args[2]
    $Manifest = Get-Content -LiteralPath (Join-Path $State.marketplace_root ".mcp.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    [pscustomobject]@{ name = $Name; transport = [pscustomobject]@{ type = "stdio"; command = $Manifest.mcpServers.$Name.command; args = @($Manifest.mcpServers.$Name.args); env = $Manifest.mcpServers.$Name.env } } | ConvertTo-Json -Depth 8
    exit 0
}
exit 73
'@
    $PythonAdapter = @'
function Read-State { Get-Content -LiteralPath $env:AVAYA_CLEAN_PROFILE_STATE -Raw -Encoding UTF8 | ConvertFrom-Json }
function Write-State($State) { $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $env:AVAYA_CLEAN_PROFILE_STATE -Encoding UTF8 }
if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME) -or $env:CODEX_HOME -ne $env:AVAYA_CLEAN_PROFILE_CODEX_HOME) { exit 81 }
$State = Read-State
if ($args.Count -eq 1 -and $args[0] -eq "--version") { "Python 3.10.0"; exit 0 }
if ($args.Count -ge 2 -and $args[0] -like "*bridge_identity.py" -and $args[1] -eq "validate") {
    & $env:AVAYA_CLEAN_PROFILE_REAL_PYTHON @args
    exit $LASTEXITCODE
}
if ($args.Count -ge 2 -and $args[0] -like "*runtime_package.py") {
    if ($args[1] -eq "installed-version") {
        if ($State.runtime_installed) { ('{"distribution":"avaya-case-review-runtime","installed":true,"version":"' + $State.plugin_version + '"}') } else { '{"distribution":"avaya-case-review-runtime","installed":false}' }
        exit 0
    }
    if ($args[1] -eq "validate-wheel" -or $args[1] -eq "smoke") { exit 0 }
}
if ($args.Count -ge 3 -and $args[0] -eq "-m" -and $args[1] -eq "avaya_case_review_runtime.gmail_brokerctl") {
    $BrokerState = Join-Path $env:LOCALAPPDATA "AvayaCaseReview\gmail-broker\state.json"
    if ($args[2] -eq "verify-bridge") {
        New-Item -ItemType Directory -Path (Split-Path -Parent $BrokerState) -Force | Out-Null
        '{"build_id":"candidate"}' | Set-Content -LiteralPath $BrokerState -Encoding UTF8
        exit 0
    }
    if ($args[2] -eq "stop") {
        if (-not (Test-Path -LiteralPath $BrokerState -PathType Leaf)) { exit 20 }
        Remove-Item -LiteralPath $BrokerState -Force
        exit 0
    }
}
if ($args.Count -ge 3 -and $args[0] -eq "-m" -and $args[1] -eq "pip") {
    if ($args[2] -eq "wheel") {
        $Index = [Array]::IndexOf($args, "--wheel-dir")
        $WheelDirectory = [string]$args[$Index + 1]
        New-Item -ItemType Directory -Path $WheelDirectory -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $WheelDirectory ("avaya_case_review_runtime-" + $State.plugin_version + "-py3-none-any.whl")) -Value "fixture" -Encoding ASCII
    }
    if ($args[2] -eq "install" -and (@($args | Where-Object { $_ -like "*.whl" }).Count -gt 0)) { $State.runtime_installed = $true; Write-State $State }
    exit 0
}
exit 83
'@
    Set-SmokeTextFile -Path (Join-Path $Path "codex.ps1") -Text $CodexAdapter
    Set-SmokeTextFile -Path (Join-Path $Path "python.ps1") -Text $PythonAdapter
    Set-SmokeTextFile -Path (Join-Path $Path "codex.cmd") -Text "@echo off`n powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0codex.ps1`" %*`nexit /b %ERRORLEVEL%`n"
    Set-SmokeTextFile -Path (Join-Path $Path "python.cmd") -Text "@echo off`n powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"%~dp0python.ps1`" %*`nexit /b %ERRORLEVEL%`n"
}

function Invoke-McpHandshake {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$ExpectedTools
    )

    $Definition = & codex mcp get $Name --json | ConvertFrom-Json
    $Transport = $Definition.transport
    if ($Transport.type -cne "stdio" -or $Transport.command -cne "python" -or @($Transport.args).Count -ne 2 -or $Transport.args[0] -cne "-m") {
        throw "Installed MCP definition does not use the packaged module contract."
    }
    $Requests = @(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"release-smoke","version":"1.0"}}}',
        '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
    )
    $ModuleArguments = @($Transport.args)
    Push-Location -LiteralPath $HandshakeWorkDirectory
    try {
        $AdapterOutput = @($Requests | & $RealPythonPath @ModuleArguments 2>&1)
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Installed MCP command exited before completing its handshake."
    }
    $Responses = @($AdapterOutput | ForEach-Object { $_ | ConvertFrom-Json })
    $Initialize = @($Responses | Where-Object { $_.id -eq 1 }) | Select-Object -First 1
    $Listed = @($Responses | Where-Object { $_.id -eq 2 }) | Select-Object -First 1
    if ($null -eq $Initialize -or $null -eq $Listed -or [string]::IsNullOrWhiteSpace([string]$Initialize.result.protocolVersion)) {
        throw "Installed MCP handshake did not complete ($($Responses.Count) response records)."
    }
    $ActualTools = @($Listed.result.tools | ForEach-Object { [string]$_.name } | Sort-Object)
    if (@(Compare-Object -ReferenceObject @($ExpectedTools | Sort-Object) -DifferenceObject $ActualTools).Count -ne 0) {
        throw "Installed MCP tool contract does not match."
    }
    return $ActualTools
}

try {
    New-Item -ItemType Directory -Path $TestRoot, $TestCodexHome, $FixtureRepository, $AdapterRoot, $RuntimeTarget, $HandshakeWorkDirectory -Force | Out-Null
    $ReleaseFiles = @(Get-ReleaseManifestFiles -Root $ResolvedRepositoryRoot)
    Copy-ReleaseManifestFiles -Files $ReleaseFiles -DestinationRoot $FixtureRepository

    $BridgeSourcePath = Join-Path $FixtureRepository "tools\gmail\cloud\GmailMcpBridge.gs"
    $BridgeIdentityPath = Join-Path $FixtureRepository "tools\gmail\cloud\bridge_identity.py"
    $PluginVersion = [string]((Get-Content -LiteralPath (Join-Path $FixtureRepository ".codex-plugin\plugin.json") -Raw -Encoding UTF8 | ConvertFrom-Json).version)
    $null = & $RealPythonPath -B $BridgeIdentityPath validate `
        --source $BridgeSourcePath `
        --attestation $ResolvedAttestationPath `
        --plugin-version $PluginVersion 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "The supplied bridge attestation failed source verification."
    }
    Copy-Item -LiteralPath $ResolvedAttestationPath -Destination (Join-Path $FixtureRepository "tools\gmail\cloud\bridge_release_attestation.json") -Force
    $FixtureFiles = @(
        Get-ChildItem -LiteralPath $FixtureRepository -File -Recurse |
            ForEach-Object { $_.FullName.Substring($FixtureRepository.Length + 1).Replace('\', '/') } |
            Sort-Object
    )
    $ExpectedFixtureFiles = @($ReleaseFiles | ForEach-Object { [string]$_.Entry } | Sort-Object)
    $FixtureDifference = @(Compare-Object -ReferenceObject $ExpectedFixtureFiles -DifferenceObject $FixtureFiles)
    if ($FixtureDifference.Count -ne 0) {
        $DifferentPaths = @($FixtureDifference | ForEach-Object { [string]$_.InputObject }) -join ", "
        throw "Fixture repository files do not exactly match release-manifest.txt: $DifferentPaths"
    }
    Write-SmokeAdapters -Path $AdapterRoot
    [pscustomobject]@{
        marketplace_installed = $false
        plugin_installed = $false
        plugin_version = "1.11.0"
        runtime_installed = $false
        marketplace_root = $FixtureRepository
    } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8

    $env:CODEX_HOME = $TestCodexHome
    $env:LOCALAPPDATA = Join-Path $TestRoot "localappdata"
    $env:PATH = $AdapterRoot + [IO.Path]::PathSeparator + $PreviousPath
    $env:AVAYA_CLEAN_PROFILE_STATE = $StatePath
    $env:AVAYA_CLEAN_PROFILE_CODEX_HOME = $TestCodexHome
    $env:AVAYA_CLEAN_PROFILE_ADAPTER_ROOT = $AdapterRoot
    $env:AVAYA_CLEAN_PROFILE_REAL_PYTHON = $RealPythonPath
    $Installer = Join-Path $FixtureRepository "install-codex.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Installer -MarketplaceSource $FixtureRepository -MarketplaceRef $MarketplaceRef -AllowUnreleasedRef -SkipLogin *> $InstallerLog
    if ($LASTEXITCODE -ne 0) { throw "Automated installer smoke failed." }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Installer -MarketplaceSource $FixtureRepository -MarketplaceRef $MarketplaceRef -AllowUnreleasedRef -SkipLogin -SkipDependencyInstall *> $InstallerLog
    if ($LASTEXITCODE -ne 0) { throw "Automated installer reinstall smoke failed." }

    $env:PYTHONPATH = $RuntimeTarget
    & $RealPythonPath -m pip install --target $RuntimeTarget --no-deps --no-build-isolation $FixtureRepository *> $InstallerLog
    if ($LASTEXITCODE -ne 0) { throw "Isolated runtime package installation failed." }
    $GmailTools = Invoke-McpHandshake -Name "gmail" -ExpectedTools @("gmail_search", "gmail_read", "gmail_send", "gmail_list_threads", "gmail_read_thread_page")
    $CaseTools = Invoke-McpHandshake -Name "CaseToMD" -ExpectedTools @("get_case_markdown")
    $State = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $Summary = [ordered]@{
        automated = $true
        profile_restored = $false
        runtime = [ordered]@{ installed = [bool]$State.runtime_installed; version = [string]$State.plugin_version; real_handshake = $true }
        marketplace = [ordered]@{ installed = [bool]$State.marketplace_installed }
        plugin = [ordered]@{ enabled = [bool]$State.plugin_installed }
        tools = [ordered]@{ gmail = @($GmailTools); CaseToMD = @($CaseTools) }
        fixture_files = @($FixtureFiles)
    }
} finally {
    if ($null -eq $PreviousCodexHome) {
        Remove-Item -LiteralPath Env:CODEX_HOME -ErrorAction SilentlyContinue
    } else {
        $env:CODEX_HOME = $PreviousCodexHome
    }
    $env:PATH = $PreviousPath
    if ($null -eq $PreviousPythonPath) {
        Remove-Item -LiteralPath Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $PreviousPythonPath
    }
    if ($null -eq $PreviousLocalAppData) {
        Remove-Item -LiteralPath Env:LOCALAPPDATA -ErrorAction SilentlyContinue
    } else {
        $env:LOCALAPPDATA = $PreviousLocalAppData
    }
    Get-ChildItem Env: | Where-Object { $_.Name -like "AVAYA_CLEAN_PROFILE_*" } | ForEach-Object {
        Remove-Item -LiteralPath ("Env:" + $_.Name) -ErrorAction SilentlyContinue
    }
    foreach ($Name in $PreviousCleanProfileEnvironment.Keys) {
        Set-Item -LiteralPath ("Env:" + $Name) -Value $PreviousCleanProfileEnvironment[$Name]
    }
    if ($null -ne $Summary) {
        $Summary.profile_restored = ($env:CODEX_HOME -eq $PreviousCodexHome)
        $Summary.clean_profile_environment_restored = @(
            $PreviousCleanProfileEnvironment.Keys | Where-Object {
                (Get-Item -LiteralPath ("Env:" + $_)).Value -cne $PreviousCleanProfileEnvironment[$_]
            }
        ).Count -eq 0
    }
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force
    }
}

if ($null -ne $Summary) {
    $Summary | ConvertTo-Json -Depth 8 -Compress
}
