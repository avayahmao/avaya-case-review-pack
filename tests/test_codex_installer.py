import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from tools.gmail.cloud.bridge_identity import write_attestation


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install-codex.ps1"
WINDOWS_COMMON = ROOT / "tools" / "installer" / "windows_common.ps1"


CODEX_SHIM = r"""
function Add-TestEvent {
    param([Parameter(Mandatory = $true)][string]$Name)
    Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG -Value $Name -Encoding UTF8
}

function Read-TestState {
    $State = Get-Content -LiteralPath $env:AVAYA_INSTALL_TEST_STATE -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not [string]::IsNullOrWhiteSpace([string]$State.fixture_sentinel)) { Write-Error ([string]$State.fixture_sentinel) }
    return $State
}

function Write-TestState {
    param([Parameter(Mandatory = $true)][pscustomobject]$State)
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $env:AVAYA_INSTALL_TEST_STATE -Encoding UTF8
}

if ($args.Count -eq 1 -and $args[0] -eq "--version") {
    Add-TestEvent "codex-version"
    Write-Output "codex-cli 0.153.4"
    exit 0
}

if ($args.Count -ge 4 -and $args[0] -eq "plugin" -and $args[1] -eq "marketplace" -and $args[2] -eq "add") {
    $State = Read-TestState
    $RefIndex = [Array]::IndexOf($args, "--ref")
    $RequestedRef = if ($RefIndex -ge 0) { [string]$args[$RefIndex + 1] } else { "local" }
    Add-TestEvent "marketplace-add"
    Add-TestEvent ("marketplace-add:" + $RequestedRef)
    Add-TestEvent ("source=" + [string]$args[3])
    if ($env:AVAYA_INSTALL_TEST_MODE -eq "hang-marketplace") {
        & powershell.exe -NoProfile -Command 'Start-Sleep -Seconds 2; Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG -Value "descendant-survived" -Encoding UTF8'
        Start-Sleep -Seconds 30
    }
    if ($env:AVAYA_INSTALL_TEST_MODE -eq "cleanup-failure") {
        Start-Sleep -Seconds 3
        Add-TestEvent "resistant-child-mutated"
    }
    if (
        $State.fail_stage -like "*rollback-marketplace-add*" -and
        $RequestedRef -eq [string]$State.original_sha
    ) {
        Write-Error "UNSANITIZED_ROLLBACK_MARKETPLACE_ADD"
        exit 31
    }
    if ($State.fail_stage -like "*new-marketplace-add*" -and $RequestedRef -eq [string]$State.target_ref) {
        if ($State.fail_stage -eq "new-marketplace-add-after-mutation") {
            $State.marketplace_exists = $true
            $State.marketplace_source = [string]$args[3]
            $State.marketplace_source_type = [string]$State.target_source_type
            $State.marketplace_sha = [string]$State.target_sha
            Write-TestState $State
        }
        Write-Error "UNSANITIZED_NEW_MARKETPLACE_ADD"
        exit 32
    }
    if ($State.marketplace_exists) {
        Write-Error "UNSANITIZED_DUPLICATE_MARKETPLACE"
        exit 36
    }
    $State.marketplace_exists = $true
    $State.marketplace_source = [string]$args[3]
    $State.marketplace_source_type = [string]$State.target_source_type
    $State.marketplace_sha = if ($RequestedRef -eq [string]$State.target_ref) {
        [string]$State.target_sha
    } else {
        $RequestedRef
    }
    Write-TestState $State
    exit 0
}

if ($args.Count -ge 4 -and $args[0] -eq "plugin" -and $args[1] -eq "marketplace" -and $args[2] -eq "list") {
    $State = Read-TestState
    Add-TestEvent "marketplace-list"
    if ($State.marketplace_exists) {
        [pscustomobject]@{
            marketplaces = @(
                [pscustomobject]@{
                    name = "avaya-case-review-pack"
                    root = $env:AVAYA_INSTALL_TEST_MARKETPLACE_ROOT
                    marketplaceSource = [pscustomobject]@{
                        sourceType = [string]$State.marketplace_source_type
                        source = [string]$State.marketplace_source
                    }
                }
            )
        } | ConvertTo-Json -Depth 8
    } else {
        Write-Output '{"marketplaces":[]}'
    }
    exit 0
}

if ($args.Count -ge 4 -and $args[0] -eq "plugin" -and $args[1] -eq "marketplace" -and $args[2] -eq "remove") {
    $State = Read-TestState
    Add-TestEvent "marketplace-remove"
    if ($State.fail_stage -like "*marketplace-remove*") {
        if ($State.fail_stage -eq "marketplace-remove-after-mutation") {
            $State.marketplace_exists = $false
            $State.marketplace_sha = ""
            Write-TestState $State
        }
        Write-Error "UNSANITIZED_MARKETPLACE_REMOVE"
        exit 33
    }
    if ($State.plugin_installed) {
        Write-Error "UNSANITIZED_MARKETPLACE_HAS_PLUGIN"
        exit 37
    }
    $State.marketplace_exists = $false
    $State.marketplace_sha = ""
    Write-TestState $State
    exit 0
}

if ($args.Count -ge 3 -and $args[0] -eq "plugin" -and $args[1] -eq "list") {
    $State = Read-TestState
    Add-TestEvent "plugin-list"
    $Installed = @()
    if ($State.plugin_installed) {
        $Installed = @(
            [pscustomobject]@{
                pluginId = "avaya-case-review@avaya-case-review-pack"
                name = "avaya-case-review"
                marketplaceName = "avaya-case-review-pack"
                version = [string]$State.plugin_version
                installed = $true
                enabled = [bool]$State.plugin_enabled
            }
        )
    }
    [pscustomobject]@{ installed = $Installed; available = @() } | ConvertTo-Json -Depth 8
    exit 0
}

if ($args.Count -ge 3 -and $args[0] -eq "plugin" -and $args[1] -eq "add") {
    $State = Read-TestState
    $PluginId = [string]$args[2]
    Add-TestEvent "plugin-add"
    Add-TestEvent ("plugin-add:" + $PluginId)
    if (-not $State.marketplace_exists) {
        Write-Error "UNSANITIZED_PLUGIN_MARKETPLACE_MISSING"
        exit 38
    }
    if ($State.fail_stage -like "*new-plugin-add*" -and $State.marketplace_sha -eq $State.target_sha) {
        if ($State.fail_stage -in @("new-plugin-add-after-mutation", "new-plugin-add-after-mutation-timeout")) {
            $State.plugin_installed = $true
            $State.plugin_enabled = $true
            Write-TestState $State
            if ($State.fail_stage -eq "new-plugin-add-after-mutation-timeout") {
                Start-Sleep -Seconds 30
            }
        }
        Write-Error "UNSANITIZED_NEW_PLUGIN_ADD"
        exit 34
    }
    $State.plugin_installed = $true
    $State.plugin_enabled = $true
    Write-TestState $State
    exit 0
}

if ($args.Count -ge 3 -and $args[0] -eq "plugin" -and $args[1] -eq "remove") {
    $State = Read-TestState
    Add-TestEvent "plugin-remove"
    if ($State.fail_stage -like "*plugin-remove*") {
        if ($State.fail_stage -eq "plugin-remove-after-mutation") {
            $State.plugin_installed = $false
            $State.plugin_enabled = $false
            Write-TestState $State
        }
        Write-Error "UNSANITIZED_PLUGIN_REMOVE"
        exit 35
    }
    $State.plugin_installed = $false
    $State.plugin_enabled = $false
    Write-TestState $State
    exit 0
}

if ($args.Count -ge 4 -and $args[0] -eq "mcp" -and $args[1] -eq "get") {
    $State = Read-TestState
    $Name = [string]$args[2]
    Add-TestEvent ("mcp-get:" + $Name)
    $Module = if ($Name -eq "gmail") {
        "avaya_case_review_runtime.gmail_mcp_server"
    } else {
        "avaya_case_review_runtime.casetomd_mcp_bridge"
    }
    if ($State.fail_stage -like "*mcp-definition*" -and $Name -eq "gmail") {
        $Module = '${BROKEN_ROOT}/gmail_mcp_server.py'
    }
    $McpEnvironment = if ($Name -eq "gmail") {
        $Values = [ordered]@{
            GMAIL_BACKEND = "edge_broker"
            PYTHONIOENCODING = "utf-8"
        }
        if ($State.fail_stage -like "*mcp-env*") {
            $Values["PYTHONPATH"] = "SENTINEL_INJECTED"
        }
        [pscustomobject]$Values
    } else {
        [pscustomobject]@{ PYTHONIOENCODING = "utf-8" }
    }
    $TransportValues = [ordered]@{
        type = if ($State.fail_stage -like "*mcp-transport-type*") { "http" } else { "stdio" }
        command = "python"
        args = @("-m", $Module)
        env = $McpEnvironment
    }
    if ($State.fail_stage -like "*mcp-transport-cwd*") {
        $TransportValues["cwd"] = "SENTINEL_CWD"
    }
    if ($State.fail_stage -like "*mcp-transport-extra*") {
        $TransportValues["injected"] = "SENTINEL_EXTRA"
    }
    [pscustomobject]@{
        name = $Name
        transport = [pscustomobject]$TransportValues
    } | ConvertTo-Json -Depth 8
    exit 0
}

Write-Error "Unexpected codex arguments"
exit 91
"""


GIT_SHIM = r"""
function Add-TestEvent {
    param([Parameter(Mandatory = $true)][string]$Name)
    Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG -Value $Name -Encoding UTF8
}

$State = Get-Content -LiteralPath $env:AVAYA_INSTALL_TEST_STATE -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [string]::IsNullOrWhiteSpace([string]$State.fixture_sentinel)) { Write-Error ([string]$State.fixture_sentinel) }
if ($args.Count -ge 3 -and $args[0] -eq "ls-remote") {
    if ($args.Count -eq 3) {
        Add-TestEvent "git-ls-remote:all"
        Write-Output (([string]$State.target_sha) + "`trefs/heads/release-candidate")
        exit 0
    }
    $RequestedRef = [string]$args[3]
    $DisplayRef = $RequestedRef.Replace("refs/tags/", "").Replace("^{}", "")
    Add-TestEvent ("git-ls-remote:" + $DisplayRef)
    if ($RequestedRef.StartsWith("refs/tags/")) {
        if ($State.missing_tag) { exit 2 }
        $TagRef = $RequestedRef.Replace("^{}", "")
        if ($State.annotated_tag) {
            Write-Output ("tag-object-sha`t" + $TagRef)
            Write-Output (([string]$State.target_sha) + "`t" + $TagRef + "^{}")
        } else {
            Write-Output (([string]$State.target_sha) + "`t" + $TagRef)
        }
        exit 0
    }
    if ($RequestedRef -match '^[0-9a-fA-F]{40}$') {
        exit 2
    }
    if ($State.annotated_tag) {
        Write-Output ("tag-object-sha`trefs/tags/" + $RequestedRef)
        Write-Output (([string]$State.target_sha) + "`trefs/tags/" + $RequestedRef + "^{}")
        exit 0
    }
    if ($State.ref_collision) {
        Write-Output ("branch-sha`trefs/heads/" + $RequestedRef)
        Write-Output (([string]$State.target_sha) + "`trefs/tags/" + $RequestedRef)
        exit 0
    }
    Write-Output (([string]$State.target_sha) + "`trefs/tags/" + $RequestedRef)
    exit 0
}

if ($args.Count -ge 4 -and $args[0] -eq "-C" -and $args[2] -eq "rev-parse" -and $args[3] -eq "HEAD") {
    $ResolvedSha = [string]$State.marketplace_sha
    if ($State.fail_stage -like "*resolved-sha-mismatch*" -and $ResolvedSha -eq [string]$State.target_sha) {
        $ResolvedSha = "mismatched-sha"
    }
    Add-TestEvent ("git-rev-parse:" + $ResolvedSha)
    Write-Output $ResolvedSha
    exit 0
}

Write-Error "Unexpected git arguments"
exit 92
"""


PYTHON_SHIM = r"""
function Add-TestEvent {
    param([Parameter(Mandatory = $true)][string]$Name)
    Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG -Value $Name -Encoding UTF8
}
function Read-TestState {
    $State = Get-Content -LiteralPath $env:AVAYA_INSTALL_TEST_STATE -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not [string]::IsNullOrWhiteSpace([string]$State.fixture_sentinel)) { Write-Error ([string]$State.fixture_sentinel) }
    return $State
}
function Write-TestState {
    param([Parameter(Mandatory = $true)][pscustomobject]$State)
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $env:AVAYA_INSTALL_TEST_STATE -Encoding UTF8
}

$State = Read-TestState
if ($args.Count -eq 1 -and $args[0] -eq "--version") {
    Add-TestEvent "python-version"
    Write-Output "Python 3.14.0"
    exit 0
}
if ($args.Count -ge 2 -and $args[0] -like "*bridge_identity.py" -and $args[1] -eq "validate") {
    Add-TestEvent "attestation-validate"
    & $env:AVAYA_INSTALL_TEST_REAL_PYTHON @args
    exit $LASTEXITCODE
}
if ($args.Count -ge 2 -and $args[0] -like "*runtime_package.py") {
    $Command = [string]$args[1]
    if ($Command -eq "installed-version") {
        Add-TestEvent ("runtime-version:" + [string]$State.runtime_version)
        if ([string]::IsNullOrWhiteSpace([string]$State.runtime_version)) {
            Write-Output '{"distribution":"avaya-case-review-runtime","installed":false}'
        } else {
            Write-Output ('{"distribution":"avaya-case-review-runtime","installed":true,"version":"' + [string]$State.runtime_version + '"}')
        }
        exit 0
    }
    if ($Command -eq "validate-wheel") {
        $WheelIndex = [Array]::IndexOf($args, "--wheel")
        $Wheel = [string]$args[$WheelIndex + 1]
        Add-TestEvent ("wheel-validate:" + [IO.Path]::GetFileName($Wheel))
        if (-not (Test-Path -LiteralPath $Wheel -PathType Leaf)) { exit 41 }
        exit 0
    }
    if ($Command -eq "smoke") {
        Add-TestEvent "runtime-smoke"
        exit 0
    }
}
$BrokerCommand = ""
if ($args.Count -ge 3 -and $args[0] -eq "-B" -and $args[1] -like "*gmail_brokerctl.py") {
    $BrokerCommand = [string]$args[2]
} elseif ($args.Count -ge 3 -and $args[0] -eq "-m" -and $args[1] -eq "avaya_case_review_runtime.gmail_brokerctl") {
    $BrokerCommand = [string]$args[2]
}
if ($BrokerCommand -eq "verify-bridge") {
    Add-TestEvent "verify-bridge"
    if ([bool]$State.broker_running -and [string]$State.broker_build -ne [string]$State.runtime_version) {
        Add-TestEvent "old-broker-rejected-bridge-capabilities"
        exit 30
    }
    $Index = [int]$State.verify_index
    $Exits = @([string]$State.verify_exits -split ',' | ForEach-Object { [int]$_ })
    $State.verify_index = $Index + 1
    $State.broker_running = $true
    $State.broker_build = [string]$State.runtime_version
    Write-TestState $State
    $BrokerDirectory = Split-Path -Parent $env:AVAYA_INSTALL_TEST_BROKER_STATE
    New-Item -ItemType Directory -Path $BrokerDirectory -Force | Out-Null
    [pscustomobject]@{ pid = 0; build_id = [string]$State.broker_build } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $env:AVAYA_INSTALL_TEST_BROKER_STATE -Encoding UTF8
    exit $Exits[[Math]::Min($Index, $Exits.Count - 1)]
}
if ($BrokerCommand -eq "login") {
    Add-TestEvent "login"
    exit [int]$State.login_exit
}
if ($BrokerCommand -eq "stop") {
    Add-TestEvent "stop"
    if (-not [bool]$State.broker_running) { exit 20 }
    $State.broker_running = $false
    Write-TestState $State
    Remove-Item -LiteralPath $env:AVAYA_INSTALL_TEST_BROKER_STATE -Force -ErrorAction SilentlyContinue
    exit 0
}
if ($BrokerCommand -eq "start") {
    Add-TestEvent "start"
    $State.broker_running = $true
    $State.broker_build = [string]$State.runtime_version
    Write-TestState $State
    $BrokerDirectory = Split-Path -Parent $env:AVAYA_INSTALL_TEST_BROKER_STATE
    New-Item -ItemType Directory -Path $BrokerDirectory -Force | Out-Null
    [pscustomobject]@{ pid = 0; build_id = [string]$State.broker_build } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $env:AVAYA_INSTALL_TEST_BROKER_STATE -Encoding UTF8
    [pscustomobject]@{ ok = $true; result = [pscustomobject]@{ build_id = [string]$State.broker_build; edge_state = "STARTING" } } |
        ConvertTo-Json -Compress
    exit [int]$State.prior_start_exit
}
if ($BrokerCommand -eq "status") {
    Add-TestEvent "status"
    if (-not [bool]$State.broker_running) { exit 20 }
    [pscustomobject]@{ ok = $true; result = [pscustomobject]@{ build_id = [string]$State.broker_build; edge_state = "AUTHENTICATED" } } |
        ConvertTo-Json -Compress
    exit [int]$State.prior_status_exit
}
if ($args.Count -ge 3 -and $args[0] -eq "-m" -and $args[1] -eq "pip") {
    $PipCommand = [string]$args[2]
    if ($PipCommand -eq "install" -and $State.fail_stage -like "*dependency-timeout*" -and (@($args | Where-Object { [string]$_ -like "*.whl" }).Count -eq 0)) {
        Start-Sleep -Seconds 30
    }
    if ($PipCommand -eq "wheel") {
        Add-TestEvent "runtime-build"
        $DirectoryIndex = [Array]::IndexOf($args, "--wheel-dir")
        $Directory = [string]$args[$DirectoryIndex + 1]
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
        $Wheel = Join-Path $Directory ("avaya_case_review_runtime-" + [string]$State.plugin_version + "-py3-none-any.whl")
        Set-Content -LiteralPath $Wheel -Value "fixture" -Encoding ASCII
        exit 0
    }
    if ($PipCommand -eq "install") {
        $Wheel = @($args | Where-Object { [string]$_ -like "*.whl" }) | Select-Object -Last 1
        if ($null -ne $Wheel) {
            $Leaf = [IO.Path]::GetFileName([string]$Wheel)
            Add-TestEvent ("runtime-install:" + $Leaf)
            if ($State.fail_stage -like "*runtime-rollback*" -and $Leaf -like ("*" + [string]$State.original_runtime_version + "*")) {
                exit 42
            }
            if ($Leaf -match '^avaya_case_review_runtime-(.+?)-py') {
                $State.runtime_version = $Matches[1]
                Write-TestState $State
            }
        } else {
            Add-TestEvent "dependency-install"
            $PinnedMcpCount = @($args | Where-Object { [string]$_ -ceq "mcp==1.28.1" }).Count
            $BareMcpCount = @($args | Where-Object { [string]$_ -ceq "mcp" }).Count
            if ($PinnedMcpCount -ne 1 -or $BareMcpCount -ne 0) { exit 45 }
        }
        exit 0
    }
    if ($PipCommand -eq "uninstall") {
        Add-TestEvent "runtime-uninstall:avaya-case-review-runtime"
        $State.runtime_version = ""
        Write-TestState $State
        exit 0
    }
}
Write-Error "Unexpected python arguments"
exit 93
"""


class CodexInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.temp_root = Path(self.temporary.name)
        self.bin_dir = self.temp_root / "bin"
        self.bin_dir.mkdir()
        self.log_path = self.temp_root / "events.log"
        self.state_path = self.temp_root / "state.json"
        self.marketplace_root = self.temp_root / "marketplace"
        self.marketplace_root.mkdir()
        self._write_shim("codex.ps1", CODEX_SHIM)
        self._write_shim("git.ps1", GIT_SHIM)
        self._write_shim("python.ps1", PYTHON_SHIM)
        self._write_state()

    def _write_shim(self, name, source):
        (self.bin_dir / name).write_text(
            source.strip() + "\n", encoding="utf-8-sig", newline="\r\n"
        )

    def _write_state(
        self,
        *,
        existing_source="https://example.invalid/repo",
        existing_source_type="git",
        existing_sha="",
        target_sha="new-sha",
        target_ref="v1.10.0",
        plugin_installed=False,
        plugin_enabled=False,
        fail_stage="",
        annotated_tag=False,
        ref_collision=False,
        target_source_type="git",
        plugin_version="1.10.1",
        runtime_version="1.10.1",
        verify_exits="0",
        login_exit=0,
        missing_tag=False,
        fixture_sentinel="",
        prior_broker_running=False,
        prior_broker_build="",
        prior_start_exit=0,
        prior_status_exit=0,
    ):
        state = {
            "marketplace_exists": bool(existing_sha),
            "marketplace_source": existing_source,
            "marketplace_source_type": existing_source_type,
            "marketplace_sha": existing_sha,
            "original_sha": existing_sha,
            "target_sha": target_sha,
            "target_ref": target_ref,
            "plugin_installed": plugin_installed,
            "plugin_enabled": plugin_enabled,
            "fail_stage": fail_stage,
            "annotated_tag": annotated_tag,
            "ref_collision": ref_collision,
            "target_source_type": target_source_type,
            "plugin_version": plugin_version,
            "runtime_version": runtime_version,
            "original_runtime_version": runtime_version,
            "verify_exits": verify_exits,
            "verify_index": 0,
            "login_exit": login_exit,
            "missing_tag": missing_tag,
            "fixture_sentinel": fixture_sentinel,
            "broker_running": prior_broker_running,
            "broker_build": prior_broker_build or runtime_version,
            "prior_start_exit": prior_start_exit,
            "prior_status_exit": prior_status_exit,
        }
        self.state_path.write_text(json.dumps(state), encoding="utf-8-sig")
        broker_state = self.temp_root / "local/AvayaCaseReview/gmail-broker/state.json"
        if prior_broker_running:
            broker_state.parent.mkdir(parents=True, exist_ok=True)
            broker_state.write_text(
                json.dumps({"pid": 0, "build_id": prior_broker_build or runtime_version}),
                encoding="utf-8",
            )
        else:
            broker_state.unlink(missing_ok=True)

    def _read_state(self):
        value = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        return SimpleNamespace(**value)

    def _environment(self, mode="normal", *, python_available=True):
        environment = os.environ.copy()
        if python_available:
            environment["PATH"] = str(self.bin_dir) + os.pathsep + environment["PATH"]
        else:
            no_python_bin = self.temp_root / "no-python-bin"
            no_python_bin.mkdir(exist_ok=True)
            for name in ("codex.ps1", "git.ps1"):
                shutil.copy2(self.bin_dir / name, no_python_bin / name)
            environment["PATH"] = str(no_python_bin)
        environment["AVAYA_INSTALL_TEST_LOG"] = str(self.log_path)
        environment["AVAYA_INSTALL_TEST_MODE"] = mode
        environment["AVAYA_INSTALL_TEST_STATE"] = str(self.state_path)
        environment["AVAYA_INSTALL_TEST_BROKER_STATE"] = str(
            self.temp_root / "local/AvayaCaseReview/gmail-broker/state.json"
        )
        environment["AVAYA_INSTALL_TEST_REAL_PYTHON"] = sys.executable
        environment["AVAYA_INSTALL_TEST_MARKETPLACE_ROOT"] = str(
            self.marketplace_root
        )
        environment["LOCALAPPDATA"] = str(self.temp_root / "local")
        return environment

    def _events(self):
        if not self.log_path.exists():
            return []
        return [
            line.lstrip("\ufeff")
            for line in self.log_path.read_text(encoding="utf-8-sig").splitlines()
            if line
        ]

    def run_installer(self, *extra_arguments, source="https://example.invalid/repo"):
        result, events, _ = self.run_stateful_installer(
            source=source,
            extra_arguments=extra_arguments,
        )
        return result, events

    def run_stateful_installer(
        self,
        *,
        plugin_version="1.10.1",
        existing_source="https://example.invalid/repo",
        existing_source_type="git",
        existing_sha="",
        target_sha="new-sha",
        plugin_installed=False,
        plugin_enabled=False,
        fail_stage="",
        annotated_tag=False,
        ref_collision=False,
        source="https://example.invalid/repo",
        extra_arguments=(),
        runtime_version=None,
        retain_prior_wheel=True,
        verify_exits="0",
        login_exit=0,
        missing_tag=False,
        fixture_sentinel="",
        skip_dependency=True,
        corrupt_attestation=False,
        attestation_variant="",
        local_mcp_variant="",
        installed_mcp_variant="",
        prior_broker_running=False,
        prior_broker_build="",
        prior_start_exit=0,
        prior_status_exit=0,
        python_available=True,
    ):
        fixture_root = self.temp_root / "stateful-installer"
        for relative_path in (
            ".codex-plugin/plugin.json",
            ".agents/plugins/marketplace.json",
            ".mcp.json",
            "pyproject.toml",
            "tools/gmail/gmail_brokerctl.py",
            "tools/gmail/cloud/GmailMcpBridge.gs",
            "tools/gmail/cloud/bridge_identity.py",
            "tools/installer/runtime_package.py",
            "tools/installer/windows_common.ps1",
            "avaya_case_review_runtime/__init__.py",
            "avaya_case_review_runtime/bridge_identity.py",
        ):
            destination = fixture_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative_path, destination)
        shutil.copy2(INSTALLER, fixture_root / INSTALLER.name)

        if fail_stage.endswith("timeout"):
            helper_path = fixture_root / "tools/installer/windows_common.ps1"
            helper_source = helper_path.read_text(encoding="utf-8-sig")
            helper_source = helper_source.replace(
                "$TimeoutPluginSeconds = 120", "$TimeoutPluginSeconds = 1"
            )
            helper_source = helper_source.replace(
                "$TimeoutPipSeconds = 300", "$TimeoutPipSeconds = 1"
            )
            helper_path.write_text(
                helper_source, encoding="utf-8-sig", newline="\r\n"
            )

        manifest_path = fixture_root / ".codex-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        manifest["version"] = plugin_version
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8-sig"
        )
        write_attestation(
            fixture_root / "tools/gmail/cloud/GmailMcpBridge.gs",
            fixture_root / "tools/gmail/cloud/bridge_release_attestation.json",
            plugin_version,
            "2026-09-09T00:00:00Z",
        )
        if corrupt_attestation:
            (fixture_root / "tools/gmail/cloud/bridge_release_attestation.json").write_text(
                json.dumps({"invalid": fixture_sentinel or True}), encoding="utf-8"
            )
        elif attestation_variant == "duplicate-coercible-schema":
            attestation_path = (
                fixture_root / "tools/gmail/cloud/bridge_release_attestation.json"
            )
            source = attestation_path.read_text(encoding="utf-8")
            attestation_path.write_text(
                source.replace("{", '{"schema_version": true,', 1),
                encoding="utf-8",
            )
        pyproject_path = fixture_root / "pyproject.toml"
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8").replace(
                'version = "1.10.0"', f'version = "{plugin_version}"'
            ),
            encoding="utf-8",
        )
        mcp_path = fixture_root / ".mcp.json"
        mcp_manifest = json.loads(mcp_path.read_text(encoding="utf-8"))
        if local_mcp_variant == "extra-server":
            mcp_manifest["mcpServers"]["injected"] = {
                "command": "python",
                "args": ["-m", "injected"],
                "env": {},
            }
        elif local_mcp_variant == "extra-field":
            mcp_manifest["mcpServers"]["gmail"]["cwd"] = "SENTINEL_CWD"
        elif local_mcp_variant == "pythonpath":
            mcp_manifest["mcpServers"]["gmail"]["env"]["PYTHONPATH"] = "SENTINEL_PATH"
        mcp_path.write_text(json.dumps(mcp_manifest), encoding="utf-8")
        installed_mcp = json.loads(json.dumps(mcp_manifest))
        if installed_mcp_variant == "extra-server":
            installed_mcp["mcpServers"]["injected"] = {
                "command": "python",
                "args": ["-m", "injected"],
                "env": {},
            }
        elif installed_mcp_variant == "extra-field":
            installed_mcp["mcpServers"]["gmail"]["cwd"] = "SENTINEL_CWD"
        elif installed_mcp_variant == "pythonpath":
            installed_mcp["mcpServers"]["gmail"]["env"]["PYTHONPATH"] = "SENTINEL_PATH"
        (self.marketplace_root / ".mcp.json").write_text(
            json.dumps(installed_mcp), encoding="utf-8"
        )
        if runtime_version is None:
            runtime_version = plugin_version
        wheel_store = self.temp_root / "local" / "AvayaCaseReview" / "runtime-wheels"
        if runtime_version and runtime_version != plugin_version and retain_prior_wheel:
            wheel_store.mkdir(parents=True, exist_ok=True)
            (wheel_store / f"avaya_case_review_runtime-{runtime_version}-py3-none-any.whl").write_text(
                "retained fixture", encoding="ascii"
            )
        target_ref = f"v{plugin_version}"
        if "-MarketplaceRef" in extra_arguments:
            target_ref = extra_arguments[extra_arguments.index("-MarketplaceRef") + 1]
        self._write_state(
            existing_source=existing_source,
            existing_source_type=existing_source_type,
            existing_sha=existing_sha,
            target_sha=target_sha,
            target_ref=target_ref,
            plugin_installed=plugin_installed,
            plugin_enabled=plugin_enabled,
            fail_stage=fail_stage,
            annotated_tag=annotated_tag,
            ref_collision=ref_collision,
            target_source_type="local" if Path(source).exists() else "git",
            plugin_version=plugin_version,
            runtime_version=runtime_version,
            verify_exits=verify_exits,
            login_exit=login_exit,
            missing_tag=missing_tag,
            fixture_sentinel=fixture_sentinel,
            prior_broker_running=prior_broker_running,
            prior_broker_build=prior_broker_build,
            prior_start_exit=prior_start_exit,
            prior_status_exit=prior_status_exit,
        )
        installer_arguments = [
            shutil.which("powershell.exe") or "powershell.exe",
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(fixture_root / INSTALLER.name), "-CloudBridgeVerified",
        ]
        if skip_dependency:
            installer_arguments.append("-SkipDependencyInstall")
        if "-AllowLogin" not in extra_arguments:
            installer_arguments.append("-SkipLogin")
        extra_arguments = tuple(value for value in extra_arguments if value != "-AllowLogin")
        installer_arguments.extend(("-MarketplaceSource", source, *extra_arguments))
        result = subprocess.run(
            installer_arguments,
            cwd=fixture_root,
            env=self._environment(python_available=python_available),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        return result, self._events(), self._read_state()

    def _short_marketplace_timeout_fixture(self):
        fixture_root = self.temp_root / "installer"
        for relative_path in (
            ".codex-plugin/plugin.json",
            ".agents/plugins/marketplace.json",
            ".mcp.json",
            "pyproject.toml",
            "tools/gmail/gmail_brokerctl.py",
            "tools/gmail/cloud/GmailMcpBridge.gs",
            "tools/gmail/cloud/bridge_identity.py",
            "tools/installer/runtime_package.py",
            "avaya_case_review_runtime/__init__.py",
            "avaya_case_review_runtime/bridge_identity.py",
        ):
            destination = fixture_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative_path, destination)

        manifest = json.loads(
            (fixture_root / ".codex-plugin/plugin.json").read_text(
                encoding="utf-8-sig"
            )
        )
        plugin_version = manifest["version"]
        write_attestation(
            fixture_root / "tools/gmail/cloud/GmailMcpBridge.gs",
            fixture_root / "tools/gmail/cloud/bridge_release_attestation.json",
            plugin_version,
            "2026-09-09T00:00:00Z",
        )
        self._write_state(
            plugin_version=plugin_version,
            runtime_version=plugin_version,
            target_ref=f"v{plugin_version}",
        )

        shutil.copy2(INSTALLER, fixture_root / INSTALLER.name)
        helper_destination = fixture_root / "tools" / "installer" / WINDOWS_COMMON.name
        helper_destination.parent.mkdir(parents=True, exist_ok=True)
        helper_source = WINDOWS_COMMON.read_text(encoding="utf-8-sig")
        self.assertEqual(1, helper_source.count("$TimeoutMarketplaceSeconds = 180"))
        shortened = helper_source.replace(
            "$TimeoutMarketplaceSeconds = 180",
            "$TimeoutMarketplaceSeconds = 1",
        )
        helper_destination.write_text(
            shortened, encoding="utf-8-sig", newline="\r\n"
        )
        return fixture_root

    def _run_installer_with_caller_tree_sentinel(self, fixture_root):
        sentinel_path = self.temp_root / "caller-tree-sentinel.ps1"
        sentinel_path.write_text(
            'Start-Sleep -Seconds 2\n'
            'Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG '
            '-Value "caller-tree-survived" -Encoding UTF8\n',
            encoding="utf-8-sig",
            newline="\r\n",
        )
        wrapper_path = self.temp_root / "installer-wrapper.ps1"
        wrapper_path.write_text(
            '$ErrorActionPreference = "Stop"\n'
            f'$SentinelPath = \'{sentinel_path}\'\n'
            '$null = Start-Process powershell.exe -ArgumentList '
            "@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $SentinelPath)\n"
            "try {\n"
            f"    & '{fixture_root / INSTALLER.name}' "
            "-CloudBridgeVerified -SkipDependencyInstall -SkipLogin "
            "-MarketplaceSource 'https://example.invalid/repo'\n"
            "} catch {\n"
            "    [Console]::Error.WriteLine($_.Exception.Message)\n"
            "    exit 1\n"
            "}\n",
            encoding="utf-8-sig",
            newline="\r\n",
        )
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(wrapper_path),
            ],
            cwd=fixture_root,
            env=self._environment(mode="hang-marketplace"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )

    def _faulted_cleanup_helper(self):
        helper_path = self.temp_root / "windows_common_faulted.ps1"
        source = WINDOWS_COMMON.read_text(encoding="utf-8-sig")
        replacements = {
            "$CleanupTimeoutMilliseconds = 5000": "$CleanupTimeoutMilliseconds = 1000",
            "$TaskKillPath = Join-Path ([Environment]::GetFolderPath('System')) 'taskkill.exe'": (
                "$TaskKillPath = [string](Get-Command powershell.exe "
                "-CommandType Application).Path"
            ),
            '$TaskKillStartInfo.Arguments = "/PID $CapturedProcessId /T /F"': (
                '$TaskKillStartInfo.Arguments = '
                "'-NoProfile -Command \"Start-Sleep -Seconds 30\"'"
            ),
        }
        for original, replacement in replacements.items():
            self.assertEqual(1, source.count(original))
            source = source.replace(original, replacement)
        helper_path.write_text(source, encoding="utf-8-sig", newline="\r\n")
        return helper_path

    def test_installer_marketplace_timeout_kills_only_started_child_tree(self):
        fixture_root = self._short_marketplace_timeout_fixture()
        manifest_version = json.loads(
            (fixture_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8-sig")
        )["version"]
        attestation = json.loads(
            (
                fixture_root
                / "tools/gmail/cloud/bridge_release_attestation.json"
            ).read_text(encoding="utf-8")
        )
        fixture_state = self._read_state()
        self.assertEqual(manifest_version, attestation["plugin_version"])
        self.assertEqual(manifest_version, fixture_state.plugin_version)
        self.assertEqual(manifest_version, fixture_state.runtime_version)
        self.assertEqual(f"v{manifest_version}", fixture_state.target_ref)
        result = self._run_installer_with_caller_tree_sentinel(fixture_root)
        time.sleep(2.5)
        events = self._events()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("marketplace", result.stderr.lower())
        self.assertIn("timed out", result.stderr.lower())
        self.assertIn("marketplace-list", events)
        self.assertIn("marketplace-add", events)
        self.assertIn("caller-tree-survived", events)
        self.assertNotIn("descendant-survived", events)

    def test_cleanup_failure_is_hidden_behind_sanitized_timeout(self):
        command = (
            f". '{WINDOWS_COMMON}'; "
            "function Stop-SpawnedProcessTree { param($Process); "
            "$Process.Kill(); [void]$Process.WaitForExit(1000); "
            "throw 'UNSANITIZED_CLEANUP_SENTINEL' }; "
            "Invoke-BoundedCommand -Stage 'marketplace add' -Command 'codex' "
            "-Arguments @('plugin', 'marketplace', 'add', 'https://example.invalid/repo') "
            "-TimeoutSeconds 1"
        )
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            cwd=ROOT,
            env=self._environment(mode="cleanup-failure"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=6,
            check=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("marketplace", result.stderr.lower())
        self.assertIn("timed out", result.stderr.lower())
        self.assertNotIn("UNSANITIZED_CLEANUP_SENTINEL", result.stderr)

    def test_successful_parent_exit_closes_inherited_pipes_and_terminates_descendant(self):
        child = self.temp_root / "pipe-child.py"
        child_pid = self.temp_root / "pipe-child.pid"
        child.write_text(
            "import os, pathlib, sys, time\n"
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='ascii')\n"
            "time.sleep(20)\n"
            "print('UNSANITIZED_DESCENDANT_OUTPUT', flush=True)\n",
            encoding="utf-8",
        )
        parent = self.temp_root / "pipe-parent.py"
        parent.write_text(
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]], close_fds=False)\n"
            "deadline = time.monotonic() + 2\n"
            "while not __import__('pathlib').Path(sys.argv[2]).exists() and time.monotonic() < deadline: time.sleep(0.01)\n"
            "print('parent-complete', flush=True)\n",
            encoding="utf-8",
        )
        command = (
            f". '{WINDOWS_COMMON}'; "
            "$result = Invoke-BoundedCommand -Stage 'pipe ownership' "
            f"-Command '{sys.executable}' -Arguments @('{parent}', '{child}', '{child_pid}') "
            "-TimeoutSeconds 1; $result | ConvertTo-Json -Compress"
        )

        started = time.monotonic()
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("bounded command hung while a descendant held its output pipes")
        elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 4.0)
        self.assertIn("parent-complete", result.stdout, result.stdout + result.stderr)
        self.assertNotIn("UNSANITIZED_DESCENDANT_OUTPUT", result.stdout + result.stderr)
        self.assertTrue(child_pid.is_file())
        pid = int(child_pid.read_text(encoding="ascii"))
        process = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ exit 1 }}",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        self.assertEqual(process.returncode, 0, "descendant survived job closure")

    def test_job_cleanup_is_bounded_even_when_legacy_fallback_is_faulted(self):
        helper_path = self._faulted_cleanup_helper()
        command = (
            f". '{helper_path}'; "
            "Invoke-BoundedCommand -Stage 'marketplace add' -Command 'codex' "
            "-Arguments @('plugin', 'marketplace', 'add', 'https://example.invalid/repo') "
            "-TimeoutSeconds 1"
        )
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            cwd=ROOT,
            env=self._environment(mode="cleanup-failure"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=6,
            check=False,
        )
        time.sleep(2.5)
        events = self._events()

        self.assertNotEqual(0, result.returncode)
        self.assertIn("marketplace", result.stderr.lower())
        self.assertIn("timed out", result.stderr.lower())
        self.assertNotIn("cleanup failed", result.stderr.lower())
        self.assertIn("marketplace-add", events)
        self.assertNotIn("resistant-child-mutated", events)

    def test_literal_arguments_are_not_reparsed_by_a_shell(self):
        result, events = self.run_installer(source=r"C:\path with spaces\repo")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(r"source=C:\path with spaces\repo", events)

    def test_fresh_install_uses_version_derived_tag(self):
        result, events, state = self.run_stateful_installer(plugin_version="1.10.1")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("marketplace-add:v1.10.1", events)
        self.assertIn(
            "plugin-add:avaya-case-review@avaya-case-review-pack", events
        )
        self.assertEqual("new-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertTrue(state.plugin_enabled)

    def test_matching_install_is_idempotent(self):
        result, events, state = self.run_stateful_installer(
            existing_sha="new-sha",
            target_sha="new-sha",
            plugin_installed=True,
            plugin_enabled=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("marketplace-remove", events)
        self.assertNotIn("plugin-remove", events)
        self.assertEqual("new-sha", state.marketplace_sha)

    def test_annotated_version_tag_verifies_the_peeled_commit(self):
        result, events, state = self.run_stateful_installer(annotated_tag=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git-rev-parse:new-sha", events)
        self.assertEqual("new-sha", state.marketplace_sha)

    def test_version_tag_does_not_resolve_from_same_named_branch(self):
        result, events, state = self.run_stateful_installer(ref_collision=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git-ls-remote:v1.10.1", events)
        self.assertEqual("new-sha", state.marketplace_sha)

    def test_missing_release_tag_blocks_before_marketplace_mutation_with_sanitized_output(self):
        result, events, state = self.run_stateful_installer(missing_tag=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target ref resolve", result.stderr.lower())
        self.assertNotIn("UNSANITIZED", result.stderr)
        self.assertNotIn("marketplace-add", events)
        self.assertFalse(state.marketplace_exists)

    def test_conflicting_source_is_never_removed(self):
        result, events, state = self.run_stateful_installer(
            existing_source="https://example.invalid/other",
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("plugin-remove", events)
        self.assertNotIn("marketplace-remove", events)
        self.assertEqual("old-sha", state.marketplace_sha)

    def test_same_source_ref_change_uses_ordered_transaction(self):
        result, events, state = self.run_stateful_installer(
            existing_sha="old-sha",
            target_sha="new-sha",
            plugin_installed=True,
            plugin_enabled=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        expected = [
            "git-ls-remote:v1.10.1",
            "plugin-remove",
            "marketplace-remove",
            "marketplace-add:v1.10.1",
            "git-rev-parse:new-sha",
            "plugin-add:avaya-case-review@avaya-case-review-pack",
        ]
        positions = [events.index(item) for item in expected]
        self.assertEqual(sorted(positions), positions)
        self.assertEqual("new-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)

    def test_failed_new_plugin_add_restores_old_sha_and_enabled_state(self):
        result, events, state = self.run_stateful_installer(
            existing_sha="old-sha",
            target_sha="new-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="new-plugin-add",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("old-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertTrue(state.plugin_enabled)
        self.assertIn("marketplace-add:old-sha", events)
        self.assertNotIn("UNSANITIZED_NEW_PLUGIN_ADD", result.stderr)

    def test_plugin_remove_failure_leaves_marketplace_untouched(self):
        result, events, state = self.run_stateful_installer(
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="plugin-remove",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("old-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertNotIn("marketplace-remove", events)

    def test_disabled_plugin_blocks_ref_change_before_mutation(self):
        result, events, state = self.run_stateful_installer(
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("disabled", result.stderr.lower())
        self.assertNotIn("plugin-remove", events)
        self.assertNotIn("marketplace-remove", events)
        self.assertEqual("old-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertFalse(state.plugin_enabled)

    def test_disabled_plugin_at_target_fails_without_mutation(self):
        result, events, state = self.run_stateful_installer(
            existing_sha="new-sha",
            target_sha="new-sha",
            plugin_installed=True,
            plugin_enabled=False,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("disabled", result.stderr.lower())
        self.assertNotIn("plugin-remove", events)
        self.assertNotIn("marketplace-remove", events)
        self.assertEqual("new-sha", state.marketplace_sha)
        self.assertFalse(state.plugin_enabled)

    def test_plugin_remove_mutation_then_failure_restores_snapshot(self):
        result, _, state = self.run_stateful_installer(
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="plugin-remove-after-mutation",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("old-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertTrue(state.plugin_enabled)

    def test_marketplace_remove_mutation_then_failure_restores_snapshot(self):
        result, _, state = self.run_stateful_installer(
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="marketplace-remove-after-mutation",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("old-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertTrue(state.plugin_enabled)

    def test_marketplace_add_mutation_then_failure_restores_snapshot(self):
        result, _, state = self.run_stateful_installer(
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="new-marketplace-add-after-mutation",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual("old-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertTrue(state.plugin_enabled)

    def test_plugin_add_mutation_then_timeout_restores_snapshot(self):
        result, _, state = self.run_stateful_installer(
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="new-plugin-add-after-mutation-timeout",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("new plugin add", result.stderr.lower())
        self.assertIn("timed out", result.stderr.lower())
        self.assertEqual("old-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertTrue(state.plugin_enabled)

    def test_resolved_sha_mismatch_triggers_rollback(self):
        result, events, state = self.run_stateful_installer(
            existing_sha="old-sha",
            target_sha="new-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="resolved-sha-mismatch",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("resolved marketplace commit verification", result.stderr.lower())
        self.assertEqual("old-sha", state.marketplace_sha)
        self.assertTrue(state.plugin_installed)
        self.assertIn("marketplace-add:old-sha", events)

    def test_rollback_failure_reports_primary_and_rollback_stages_without_cache_deletion(self):
        result, events, state = self.run_stateful_installer(
            existing_sha="old-sha",
            target_sha="new-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="new-plugin-add+rollback-marketplace-add",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("new plugin add", result.stderr.lower())
        self.assertIn("rollback marketplace add", result.stderr.lower())
        self.assertNotIn("UNSANITIZED", result.stderr)
        self.assertNotIn("cache", result.stderr.lower())
        self.assertFalse(state.marketplace_exists)
        self.assertIn("marketplace-add:old-sha", events)

    def test_unreleased_ref_requires_explicit_override(self):
        result, events, _ = self.run_stateful_installer(
            extra_arguments=("-MarketplaceRef", "candidate-sha")
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("AllowUnreleasedRef", result.stderr)
        self.assertNotIn("marketplace-add", events)

    def test_unreleased_ref_is_used_with_explicit_override(self):
        result, events, _ = self.run_stateful_installer(
            extra_arguments=(
                "-MarketplaceRef",
                "candidate-sha",
                "-AllowUnreleasedRef",
            )
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("marketplace-add:candidate-sha", events)

    def test_git_marketplace_root_is_not_accepted_as_same_local_source(self):
        result, events, state = self.run_stateful_installer(
            source=str(self.marketplace_root),
            existing_source="https://example.invalid/repo",
            existing_source_type="git",
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
        )

        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("plugin-remove", events)
        self.assertNotIn("marketplace-remove", events)
        self.assertEqual("old-sha", state.marketplace_sha)

    def test_unreleased_commit_sha_is_verified_from_advertised_refs(self):
        commit = "a" * 40
        result, events, state = self.run_stateful_installer(
            target_sha=commit,
            extra_arguments=("-MarketplaceRef", commit, "-AllowUnreleasedRef"),
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("git-ls-remote:all", events)
        self.assertEqual(commit, state.marketplace_sha)

    def test_dry_run_is_offline_and_has_no_state_events(self):
        result, events = self.run_installer("-DryRun")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["attestation-validate"], events)
        self.assertIn("validate release attestation", result.stdout.lower())
        self.assertIn("verify-bridge", result.stdout)
        self.assertIn("plugin add", result.stdout)

    def test_dry_run_uses_canonical_strict_attestation_validation(self):
        result, events, state = self.run_stateful_installer(
            extra_arguments=("-DryRun",),
            attestation_variant="duplicate-coercible-schema",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, ["attestation-validate"])
        self.assertFalse(state.marketplace_exists)
        self.assertEqual(state.runtime_version, "1.10.1")

    def test_missing_python_is_actionable_before_attestation_or_state_mutation(self):
        sentinel = "UNSANITIZED_MISSING_PYTHON"
        result, events, state = self.run_stateful_installer(
            fixture_sentinel=sentinel,
            python_available=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python was not found in PATH.", result.stderr)
        self.assertNotIn(sentinel, result.stdout + result.stderr)
        self.assertEqual(events, [])
        self.assertFalse(state.marketplace_exists)
        self.assertFalse(state.plugin_installed)
        self.assertEqual(state.runtime_version, "1.10.1")

    def test_dry_run_missing_python_is_actionable_before_attestation(self):
        result, events, state = self.run_stateful_installer(
            extra_arguments=("-DryRun",),
            python_available=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python was not found in PATH.", result.stderr)
        self.assertEqual(events, [])
        self.assertFalse(state.marketplace_exists)

    def test_clean_install_prepares_candidate_runtime_before_live_verification(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="", skip_dependency=False
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        ordered = (
            "runtime-build",
            "runtime-install:avaya_case_review_runtime-1.10.1-py3-none-any.whl",
            "runtime-smoke",
            "verify-bridge",
            "plugin-add",
        )
        positions = [
            next(i for i, event in enumerate(events) if event.startswith(name))
            for name in ordered
        ]
        self.assertEqual(positions, sorted(positions), events)
        self.assertEqual(state.runtime_version, "1.10.1")

    def test_active_old_broker_is_stopped_before_candidate_verification(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="1.9.9",
            retain_prior_wheel=True,
            skip_dependency=False,
            prior_broker_running=True,
            prior_broker_build="1.9.9",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("old-broker-rejected-bridge-capabilities", events)
        self.assertLess(events.index("stop"), events.index("verify-bridge"))
        self.assertEqual(state.broker_build, "1.10.1")

    def test_candidate_preflight_failure_restores_runtime_and_prior_broker(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="1.9.9",
            retain_prior_wheel=True,
            skip_dependency=False,
            prior_broker_running=True,
            prior_broker_build="1.9.9",
            verify_exits="30",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state.runtime_version, "1.9.9")
        self.assertTrue(state.broker_running)
        self.assertEqual(state.broker_build, "1.9.9")
        candidate_install = events.index(
            "runtime-install:avaya_case_review_runtime-1.10.1-py3-none-any.whl"
        )
        prior_stop = events.index("stop")
        verify = events.index("verify-bridge")
        candidate_stop = events.index("stop", prior_stop + 1)
        runtime_restore = events.index(
            "runtime-install:avaya_case_review_runtime-1.9.9-py3-none-any.whl"
        )
        restart = events.index("start")
        restored_status = events.index("status")
        self.assertEqual(
            [candidate_install, prior_stop, verify, candidate_stop, runtime_restore, restart, restored_status],
            sorted(
                [candidate_install, prior_stop, verify, candidate_stop, runtime_restore, restart, restored_status]
            ),
        )

    def test_prior_lazy_broker_status_ten_is_accepted_during_rollback(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="1.9.9",
            retain_prior_wheel=True,
            skip_dependency=False,
            prior_broker_running=True,
            prior_broker_build="1.9.9",
            prior_start_exit=10,
            prior_status_exit=10,
            verify_exits="30",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Recovery status: failed", result.stderr)
        self.assertTrue(state.broker_running)
        self.assertEqual(events[-2:], ["start", "status"])

    def test_candidate_live_preflight_blocks_codex_mutation_and_rolls_back_runtime(self):
        result, events, _ = self.run_stateful_installer(
            verify_exits="20", runtime_version="", skip_dependency=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("verify-bridge", events)
        self.assertIn("runtime-build", events)
        self.assertIn("runtime-uninstall:avaya-case-review-runtime", events)
        for mutation in ("marketplace-add", "plugin-add"):
            self.assertNotIn(mutation, events)

    def test_dependency_timeout_blocks_before_runtime_or_codex_mutation_with_sanitized_output(self):
        result, events, state = self.run_stateful_installer(
            fail_stage="dependency-timeout", skip_dependency=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("dependency install", result.stderr.lower())
        self.assertNotIn("UNSANITIZED", result.stderr)
        self.assertEqual(state.runtime_version, "1.10.1")
        self.assertNotIn("runtime-build", events)
        self.assertNotIn("marketplace-add", events)

    def test_required_failure_matrix_sanitizes_fixture_sentinels_and_preserves_state(self):
        scenarios = (
            ("different-source", {"existing_source": "https://UNSANITIZED_DIFFERENT_SOURCE.invalid/repo", "existing_sha": "old-sha", "plugin_installed": True, "plugin_enabled": True}, True, "old-sha", True, True),
            ("missing-tag", {"missing_tag": True}, False, "", False, False),
            ("resolved-sha", {"existing_sha": "old-sha", "plugin_installed": True, "plugin_enabled": True, "fail_stage": "resolved-sha-mismatch"}, True, "old-sha", True, True),
            ("invalid-attestation", {"corrupt_attestation": True, "skip_dependency": False}, False, "", False, False),
            ("capability-mismatch", {"verify_exits": "30"}, False, "", False, False),
            ("auth-required", {"verify_exits": "10"}, False, "", False, False),
            ("dependency-timeout", {"fail_stage": "dependency-timeout", "skip_dependency": False}, False, "", False, False),
            ("plugin-add", {"fail_stage": "new-plugin-add"}, False, "", False, False),
            ("rollback-success", {"existing_sha": "old-sha", "plugin_installed": True, "plugin_enabled": True, "fail_stage": "new-plugin-add"}, True, "old-sha", True, True),
            ("rollback-failure", {"existing_sha": "old-sha", "plugin_installed": True, "plugin_enabled": True, "fail_stage": "new-plugin-add+rollback-marketplace-add"}, False, "", False, False),
        )
        for name, options, expected_marketplace_exists, expected_marketplace_sha, expected_plugin_installed, expected_plugin_enabled in scenarios:
            with self.subTest(name=name):
                sentinel = f"UNSANITIZED_MATRIX_{name.upper().replace('-', '_')}"
                result, _, state = self.run_stateful_installer(
                    fixture_sentinel=sentinel, **options
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(sentinel, result.stdout + result.stderr)
                self.assertEqual(state.marketplace_exists, expected_marketplace_exists)
                self.assertEqual(state.marketplace_sha, expected_marketplace_sha)
                self.assertEqual(state.plugin_installed, expected_plugin_installed)
                self.assertEqual(state.plugin_enabled, expected_plugin_enabled)

    def test_invalid_local_attestation_blocks_before_any_command_or_mutation(self):
        result, events, state = self.run_stateful_installer(
            corrupt_attestation=True, skip_dependency=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("attestation", result.stderr.lower())
        self.assertEqual(events, ["attestation-validate"])
        self.assertEqual(state.runtime_version, "1.10.1")
        self.assertFalse(state.marketplace_exists)

    def test_local_mcp_manifest_rejects_extra_servers_fields_and_env_before_commands(self):
        for variant in ("extra-server", "extra-field", "pythonpath"):
            with self.subTest(variant=variant):
                self.log_path.unlink(missing_ok=True)
                result, events, _ = self.run_stateful_installer(
                    local_mcp_variant=variant
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mcp", result.stderr.lower())
                self.assertEqual(events, [])

    def test_fresh_runtime_build_validate_install_and_smoke_precede_plugin_add(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="", skip_dependency=False
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        ordered = (
            "runtime-build",
            "wheel-validate:avaya_case_review_runtime-1.10.1-py3-none-any.whl",
            "runtime-install:avaya_case_review_runtime-1.10.1-py3-none-any.whl",
            "runtime-smoke",
            "verify-bridge",
            "plugin-add",
        )
        for name in ordered:
            self.assertTrue(
                any(event.startswith(name) for event in events),
                f"missing event {name}: {events}",
            )
        positions = [next(i for i, event in enumerate(events) if event.startswith(name)) for name in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(state.runtime_version, "1.10.1")

    def test_installed_mcp_checks_use_the_packaged_module_contract(self):
        result, events, _ = self.run_stateful_installer(
            runtime_version="", skip_dependency=False
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mcp-get:gmail", events)
        self.assertIn("mcp-get:CaseToMD", events)
        installer = INSTALLER.read_text(encoding="utf-8-sig")
        self.assertIn(
            "avaya_case_review_runtime.gmail_mcp_server", installer
        )
        self.assertIn(
            "avaya_case_review_runtime.casetomd_mcp_bridge", installer
        )
        self.assertNotIn("relative Gmail and CaseToMD launch arguments", installer)

    def test_skip_dependency_requires_exact_runtime_without_pip_mutation(self):
        success, success_events, _ = self.run_stateful_installer(
            runtime_version="1.10.1", skip_dependency=True
        )
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertIn("runtime-smoke", success_events)
        self.assertFalse(any(event.startswith("runtime-install") for event in success_events))

        self.log_path.unlink(missing_ok=True)
        mismatch, mismatch_events, state = self.run_stateful_installer(
            runtime_version="1.9.9", skip_dependency=True
        )
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertEqual(state.runtime_version, "1.9.9")
        self.assertNotIn("marketplace-add", mismatch_events)
        self.assertFalse(any(event.startswith("runtime-install") for event in mismatch_events))

    def test_prior_runtime_without_retained_wheel_blocks_before_mutation(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="1.9.9",
            retain_prior_wheel=False,
            skip_dependency=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state.runtime_version, "1.9.9")
        self.assertNotIn("runtime-build", events)
        self.assertNotIn("marketplace-add", events)

    def test_successful_upgrade_retains_current_runtime_wheel(self):
        result, _, state = self.run_stateful_installer(
            runtime_version="1.9.9", skip_dependency=False
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        retained = self.temp_root / "local/AvayaCaseReview/runtime-wheels"
        self.assertTrue(
            (retained / "avaya_case_review_runtime-1.10.1-py3-none-any.whl").is_file()
        )
        self.assertEqual(state.runtime_version, "1.10.1")

    def test_plugin_failure_restores_codex_then_prior_runtime(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="1.9.9",
            skip_dependency=False,
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="new-plugin-add",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state.marketplace_sha, "old-sha")
        self.assertEqual(state.runtime_version, "1.9.9")
        self.assertIn(
            "runtime-install:avaya_case_review_runtime-1.9.9-py3-none-any.whl",
            events,
        )
        self.assertLess(
            events.index("stop"),
            events.index("marketplace-add:old-sha"),
        )
        self.assertLess(
            events.index("marketplace-add:old-sha"),
            events.index("runtime-install:avaya_case_review_runtime-1.9.9-py3-none-any.whl"),
        )

    def test_post_install_mcp_mismatch_restores_codex_before_runtime(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="1.9.9",
            skip_dependency=False,
            existing_sha="old-sha",
            plugin_installed=True,
            plugin_enabled=True,
            fail_stage="mcp-definition",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mcp", result.stderr.lower())
        self.assertEqual(state.marketplace_sha, "old-sha")
        self.assertEqual(state.runtime_version, "1.9.9")
        self.assertLess(
            events.index("marketplace-add:old-sha"),
            events.index("runtime-install:avaya_case_review_runtime-1.9.9-py3-none-any.whl"),
        )

    def test_installed_mcp_manifest_and_environment_are_exact_or_rolled_back(self):
        scenarios = (
            {"installed_mcp_variant": "extra-server"},
            {"installed_mcp_variant": "extra-field"},
            {"installed_mcp_variant": "pythonpath"},
            {"fail_stage": "mcp-env"},
        )
        for options in scenarios:
            with self.subTest(options=options):
                self.log_path.unlink(missing_ok=True)
                result, events, state = self.run_stateful_installer(
                    runtime_version="1.9.9",
                    skip_dependency=False,
                    existing_sha="old-sha",
                    plugin_installed=True,
                    plugin_enabled=True,
                    **options,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mcp", result.stderr.lower())
                self.assertEqual(state.marketplace_sha, "old-sha")
                self.assertEqual(state.runtime_version, "1.9.9")

    def test_installed_mcp_transport_rejects_cwd_extra_fields_and_non_stdio_type(self):
        for fail_stage in (
            "mcp-transport-cwd",
            "mcp-transport-extra",
            "mcp-transport-type",
        ):
            with self.subTest(fail_stage=fail_stage):
                self.log_path.unlink(missing_ok=True)
                result, _, state = self.run_stateful_installer(
                    runtime_version="1.9.9",
                    skip_dependency=False,
                    existing_sha="old-sha",
                    plugin_installed=True,
                    plugin_enabled=True,
                    fail_stage=fail_stage,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("mcp", result.stderr.lower())
                self.assertEqual(state.marketplace_sha, "old-sha")
                self.assertEqual(state.runtime_version, "1.9.9")

    def test_failure_with_no_prior_runtime_uninstalls_only_named_distribution(self):
        result, events, state = self.run_stateful_installer(
            runtime_version="",
            skip_dependency=False,
            fail_stage="new-plugin-add",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state.runtime_version, "")
        self.assertEqual(events.count("runtime-uninstall:avaya-case-review-runtime"), 1)

    def test_runtime_rollback_failure_combines_sanitized_primary_and_rollback_stages(self):
        result, _, _ = self.run_stateful_installer(
            runtime_version="1.9.9",
            skip_dependency=False,
            fail_stage="new-plugin-add+runtime-rollback",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("new plugin add", result.stderr.lower())
        self.assertIn("runtime restoration", result.stderr.lower())
        self.assertNotIn("UNSANITIZED", result.stderr)

    def test_bridge_auth_retry_contract_precedes_codex_state(self):
        scenarios = (
            ("10,0", 0, False, ["verify-bridge", "login", "verify-bridge"]),
            ("10,10", 0, True, ["verify-bridge", "login", "verify-bridge"]),
            ("30", 0, True, ["verify-bridge"]),
            ("10", 30, True, ["verify-bridge", "login"]),
        )
        for verify_exits, login_exit, fails, expected_prefix in scenarios:
            with self.subTest(verify_exits=verify_exits, login_exit=login_exit):
                self.log_path.unlink(missing_ok=True)
                result, events, _ = self.run_stateful_installer(
                    verify_exits=verify_exits,
                    login_exit=login_exit,
                    extra_arguments=("-AllowLogin",),
                )
                self.assertEqual(result.returncode != 0, fails, result.stderr)
                bridge_events = [
                    event for event in events if event in {"verify-bridge", "login"}
                ]
                self.assertEqual(bridge_events, expected_prefix)
                if fails:
                    self.assertNotIn("marketplace-add", events)

    def test_skip_login_still_runs_preflight_and_fails_on_auth_required(self):
        result, events, _ = self.run_stateful_installer(verify_exits="10")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events.count("verify-bridge"), 1)
        self.assertNotIn("login", events)
        self.assertNotIn("marketplace-add", events)


if __name__ == "__main__":
    unittest.main()
