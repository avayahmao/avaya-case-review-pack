import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.gmail.cloud.bridge_identity import write_attestation
from avaya_case_review_runtime.bridge_identity import BROKER_BUILD_ID


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup_env.ps1"
FIXTURE = ROOT / "tests/fixtures/run_setup_config_migration.ps1"
GMAIL_SOURCE = ROOT / "tools/gmail"


def read_setup() -> str:
    return SETUP.read_text(encoding="utf-8-sig")


def directory_bytes(path: Path) -> dict[str, bytes]:
    return {
        item.relative_to(path).as_posix(): item.read_bytes()
        for item in path.rglob("*")
        if item.is_file()
    }


class SetupInstallFixture:
    gmail_files = (
        "gmail_broker_client.py",
        "gmail_broker_protocol.py",
        "gmail_broker_state.py",
        "gmail_brokerctl.py",
        "gmail_edge_broker.py",
        "gmail_edge_common.py",
        "gmail_edge_poc.py",
        "gmail_legacy_backend.py",
        "gmail_mcp_server.py",
        "gmail_playwright.py",
    )

    fake_brokerctl = '''\
import json
import os
import sys
import time
from pathlib import Path

build_id: str = os.environ["SETUP_FIXTURE_EXPECTED_BUILD_ID"]
event_path = Path(os.environ["SETUP_FIXTURE_EVENTS"])
counter_path = Path(os.environ["SETUP_FIXTURE_COUNTER"])
command = sys.argv[1]
with event_path.open("a", encoding="utf-8") as stream:
    stream.write(command + "\\n")
with Path(os.environ["SETUP_FIXTURE_ENVIRONMENTS"]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({
        "command": command,
        "USERPROFILE": os.environ.get("USERPROFILE"),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA"),
    }) + "\\n")

if command == "verify-bridge":
    state_path = Path(os.environ["SETUP_FIXTURE_RUNTIME_STATE"])
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    control_build = (
        build_id
        if state["runtime_version"] == state["plugin_version"]
        else state["prior_broker_build"]
    )
    if state["broker_running"] and state["broker_build"] != control_build:
        with event_path.open("a", encoding="utf-8") as stream:
            stream.write("old-broker-rejected-bridge-capabilities\\n")
        raise SystemExit(30)
    exits = [int(value) for value in os.environ["SETUP_FIXTURE_VERIFY_EXITS"].split(",")]
    index = int(counter_path.read_text(encoding="ascii")) if counter_path.exists() else 0
    counter_path.write_text(str(index + 1), encoding="ascii")
    exit_code = exits[min(index, len(exits) - 1)]
    state["broker_running"] = True
    state["broker_build"] = control_build
    state["broker_edge_state"] = "AUTHENTICATED" if exit_code == 0 else "STARTING"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    broker_state = Path(os.environ["SETUP_FIXTURE_BROKER_STATE"])
    broker_state.parent.mkdir(parents=True, exist_ok=True)
    broker_state.write_text(json.dumps({"pid": 0, "build_id": control_build}), encoding="utf-8")
    raise SystemExit(exit_code)
if command == "login":
    time.sleep(float(os.environ.get("SETUP_FIXTURE_LOGIN_SLEEP", "0")))
    raise SystemExit(int(os.environ.get("SETUP_FIXTURE_LOGIN_EXIT", "0")))
if command == "stop":
    state_path = Path(os.environ["SETUP_FIXTURE_RUNTIME_STATE"])
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    if not state["broker_running"]:
        raise SystemExit(20)
    forced = int(os.environ.get("SETUP_FIXTURE_STOP_EXIT", "0"))
    if forced not in (0, 20):
        raise SystemExit(forced)
    state["broker_running"] = False
    state["broker_edge_state"] = "STARTING"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    Path(os.environ["SETUP_FIXTURE_BROKER_STATE"]).unlink(missing_ok=True)
    raise SystemExit(0)
if command == "status":
    if os.environ.get("SETUP_FIXTURE_ROLLBACK_BLOCK") == "1":
        target = Path(os.environ["SETUP_FIXTURE_CONFIG"])
        target.unlink()
        target.mkdir()
        (target / "block.txt").write_text("block", encoding="ascii")
    state = json.loads(Path(os.environ["SETUP_FIXTURE_RUNTIME_STATE"]).read_text(encoding="utf-8-sig"))
    print(json.dumps({"ok": True, "result": {"build_id": state["broker_build"], "edge_state": state["broker_edge_state"]}}))
    forced = int(os.environ.get("SETUP_FIXTURE_STATUS_EXIT", "0"))
    if forced:
        raise SystemExit(forced)
    raise SystemExit(10 if state["broker_edge_state"] == "STARTING" else 0)
if command == "start":
    exit_code = int(os.environ.get("SETUP_FIXTURE_START_EXIT", "0"))
    if exit_code:
        raise SystemExit(exit_code)
    state_path = Path(os.environ["SETUP_FIXTURE_RUNTIME_STATE"])
    state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    state["broker_running"] = True
    state["broker_build"] = (
        build_id
        if state["runtime_version"] == state["plugin_version"]
        else state["prior_broker_build"]
    )
    state["broker_edge_state"] = "STARTING"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    broker_state = Path(os.environ["SETUP_FIXTURE_BROKER_STATE"])
    broker_state.parent.mkdir(parents=True, exist_ok=True)
    broker_state.write_text(json.dumps({"pid": 0, "build_id": state["broker_build"]}), encoding="utf-8")
    print(json.dumps({"ok": True, "result": {"build_id": state["broker_build"], "edge_state": "STARTING"}}))
    raise SystemExit(0)
raise SystemExit(30)
'''

    fake_python = r'''
function Add-TestEvent {
    param([Parameter(Mandatory = $true)][string]$Name)
    Add-Content -LiteralPath $env:SETUP_FIXTURE_EVENTS -Value $Name -Encoding UTF8
}
function Read-TestState {
    return Get-Content -LiteralPath $env:SETUP_FIXTURE_RUNTIME_STATE -Raw -Encoding UTF8 | ConvertFrom-Json
}
function Write-TestState {
    param([Parameter(Mandatory = $true)][pscustomobject]$State)
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $env:SETUP_FIXTURE_RUNTIME_STATE -Encoding UTF8
}
function Add-EnvironmentRecord {
    param([Parameter(Mandatory = $true)][string]$Command)
    $Record = [ordered]@{
        command = $Command
        USERPROFILE = $env:USERPROFILE
        LOCALAPPDATA = $env:LOCALAPPDATA
        cwd = $PWD.Path
    }
    Add-Content -LiteralPath $env:SETUP_FIXTURE_ENVIRONMENTS -Value ($Record | ConvertTo-Json -Compress) -Encoding UTF8
}

$State = Read-TestState
if ($args.Count -eq 1 -and $args[0] -eq "--version") {
    Add-TestEvent "python-version"
    Add-EnvironmentRecord "python-version"
    Write-Output ("Python " + $env:SETUP_FIXTURE_PYTHON_VERSION)
    exit 0
}
if ($args.Count -ge 2 -and $args[0] -like "*bridge_identity.py" -and $args[1] -eq "validate") {
    Add-TestEvent "attestation-validate"
    Add-EnvironmentRecord "attestation-validate"
    & $env:SETUP_FIXTURE_REAL_PYTHON @args
    exit $LASTEXITCODE
}
if ($args.Count -ge 2 -and $args[0] -like "*runtime_package.py") {
    $Command = [string]$args[1]
    Add-EnvironmentRecord ("runtime-" + $Command)
    if ($Command -eq "installed-version") {
        $DisplayVersion = if ([string]::IsNullOrWhiteSpace([string]$State.runtime_version)) { "absent" } else { [string]$State.runtime_version }
        Add-TestEvent ("runtime-version:" + $DisplayVersion)
        if ($DisplayVersion -eq "absent") {
            Write-Output '{"distribution":"avaya-case-review-runtime","installed":false}'
        } else {
            Write-Output ('{"distribution":"avaya-case-review-runtime","installed":true,"version":"' + $DisplayVersion + '"}')
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
if ($args.Count -ge 3 -and $args[0] -eq "-m" -and $args[1] -eq "pip") {
    $PipCommand = [string]$args[2]
    Add-EnvironmentRecord ("pip-" + $PipCommand)
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
        if ($null -eq $Wheel) {
            if ($args -contains "--upgrade") {
                Add-TestEvent "pip-upgrade"
                exit 0
            }
            Add-TestEvent "dependency-install"
            $PinnedMcpCount = @($args | Where-Object { [string]$_ -ceq "mcp==1.28.1" }).Count
            $BareMcpCount = @($args | Where-Object { [string]$_ -ceq "mcp" }).Count
            if ($PinnedMcpCount -ne 1 -or $BareMcpCount -ne 0) { exit 44 }
            if (-not ($args -contains "setuptools>=68")) { exit 45 }
            exit 0
        }
        $Leaf = [IO.Path]::GetFileName([string]$Wheel)
        Add-TestEvent ("runtime-install:" + $Leaf)
        if ($Leaf -match '^avaya_case_review_runtime-(.+?)-py') {
            $InstallVersion = $Matches[1]
            if (
                [int]$env:SETUP_FIXTURE_RUNTIME_ROLLBACK_EXIT -ne 0 -and
                $InstallVersion -eq [string]$State.original_runtime_version
            ) {
                exit [int]$env:SETUP_FIXTURE_RUNTIME_ROLLBACK_EXIT
            }
            if ($InstallVersion -eq [string]$State.original_runtime_version) {
                $ConfigRestored = (Test-Path -LiteralPath $env:SETUP_FIXTURE_CONFIG -PathType Leaf) -and
                    ([IO.File]::ReadAllBytes($env:SETUP_FIXTURE_CONFIG) -join ',') -eq ([Text.Encoding]::UTF8.GetBytes('{"existing":"config"}' + "`r`n") -join ',')
                Add-TestEvent ("runtime-rollback-files-restored:" + $ConfigRestored.ToString().ToLowerInvariant())
            }
            $State.runtime_version = $InstallVersion
            Write-TestState $State
        }
        exit 0
    }
    if ($PipCommand -eq "uninstall") {
        if ($args[-1] -ne "avaya-case-review-runtime") { exit 44 }
        Add-TestEvent "runtime-uninstall:avaya-case-review-runtime"
        $State.runtime_version = ""
        Write-TestState $State
        exit 0
    }
}
if ($args.Count -ge 3 -and $args[0] -eq "-m" -and $args[1] -eq "playwright") {
    Add-TestEvent "playwright-install"
    Add-EnvironmentRecord "playwright-install"
    exit 0
}
if ($args.Count -ge 3 -and $args[0] -eq "-B" -and $args[1] -eq "-c") {
    if ([string]$args[2] -like "*apply_windows_acl*") {
        Add-TestEvent "secure-state"
        Add-EnvironmentRecord "secure-state"
        exit 0
    }
    Add-TestEvent "deployed-shim-import"
    Add-EnvironmentRecord "deployed-shim-import"
    exit 0
}
if ($args.Count -ge 3 -and $args[0] -eq "-B" -and [string]$args[-1] -eq "--help") {
    Add-TestEvent "deployed-shim-help"
    Add-EnvironmentRecord "deployed-shim-help"
    exit 0
}
if ($args.Count -ge 3 -and $args[0] -eq "-B") {
    & $env:SETUP_FIXTURE_REAL_PYTHON @args
    exit $LASTEXITCODE
}
Write-Error "Unexpected fake Python arguments"
exit 93
'''

    restore_failure_wrapper = r'''
function Copy-Item {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$LiteralPath,
        [Parameter(Mandatory = $true)][string]$Destination,
        [switch]$Recurse,
        [switch]$Force
    )

    $FailPluginRestore = (
        $env:SETUP_FIXTURE_EARLY_RESTORE_FAILURE -eq "1" -and
        $LiteralPath -like "*avaya-case-review-deploy-*\plugin" -and
        $Destination -eq $env:SETUP_FIXTURE_TARGET_PLUGIN
    )
    $FailConfigRestore = (
        $env:SETUP_FIXTURE_ROLLBACK_BLOCK -eq "1" -and
        $LiteralPath -like "*avaya-case-review-deploy-*\mcp_config.json" -and
        $Destination -eq $env:SETUP_FIXTURE_CONFIG
    )
    if ($FailPluginRestore -or $FailConfigRestore) {
        throw "fixture restore failure"
    }
    if ($LiteralPath -like "*avaya-case-review-deploy-*") {
        Add-Content -LiteralPath $env:SETUP_FIXTURE_EVENTS -Value ("restore-file:" + $Destination) -Encoding UTF8
    }
    Microsoft.PowerShell.Management\Copy-Item @PSBoundParameters
}
'''

    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.user = self.root / "user"
        self.local_app_data = self.root / "local"
        self.events = self.root / "events.txt"
        self.environments = self.root / "environments.jsonl"
        self.counter = self.root / "counter.txt"
        self.runtime_state = self.root / "runtime-state.json"
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.target_plugin = (
            self.user / ".gemini/config/plugins/avaya-case-review"
        )
        self.target_gmail = self.user / ".gemini/tools/gmail"
        self.target_case = self.user / ".gemini/tools/casetomd"
        self.config = self.user / ".gemini/config/mcp_config.json"
        self._build_source()
        self._build_existing_install()
        self._write_fake_python()
        self.set_runtime(self.plugin_version)

    def close(self):
        self.temporary.cleanup()

    def _write(self, relative: str, content: str):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def _build_source(self):
        (self.source / "tools/installer").mkdir(parents=True)
        fixture_setup = read_setup().replace(
            ". $WindowsCommonPath",
            ". $WindowsCommonPath\n\n" + self.restore_failure_wrapper.strip(),
            1,
        )
        (self.source / "setup_env.ps1").write_text(
            fixture_setup, encoding="utf-8-sig", newline="\r\n"
        )
        shutil.copy2(ROOT / "pyproject.toml", self.source / "pyproject.toml")
        shutil.copy2(
            ROOT / "tools/installer/runtime_package.py",
            self.source / "tools/installer/runtime_package.py",
        )
        shutil.copytree(
            ROOT / "avaya_case_review_runtime",
            self.source / "avaya_case_review_runtime",
        )
        shutil.copy2(
            ROOT / "tools/installer/windows_common.ps1",
            self.source / "tools/installer/windows_common.ps1",
        )

        cloud = self.source / "tools/gmail/cloud"
        cloud.mkdir(parents=True)
        shutil.copy2(GMAIL_SOURCE / "cloud/GmailMcpBridge.gs", cloud)
        shutil.copy2(GMAIL_SOURCE / "cloud/bridge_identity.py", cloud)

        plugin_manifest = json.loads(
            (ROOT / "plugins/avaya-case-review/plugin.json").read_text(encoding="utf-8")
        )
        self.plugin_version = plugin_manifest["version"]
        self._write(
            "plugins/avaya-case-review/plugin.json",
            json.dumps(plugin_manifest),
        )
        self._write("plugins/avaya-case-review/new-plugin.txt", "new plugin")
        for name in self.gmail_files:
            content = self.fake_brokerctl if name == "gmail_brokerctl.py" else "# new\n"
            if name == "gmail_broker_state.py":
                content = "def apply_windows_acl(path):\n    return None\n"
            elif name == "gmail_edge_broker.py":
                content = 'build_id: str = "source"\n'
            self._write(f"tools/gmail/{name}", content)
        self._write("tools/casetomd/casetomd_mcp_bridge.py", "# new case bridge\n")

        write_attestation(
            cloud / "GmailMcpBridge.gs",
            cloud / "bridge_release_attestation.json",
            plugin_manifest["version"],
            "2026-09-09T00:00:00Z",
        )

    def _write_fake_python(self):
        (self.bin_dir / "python.ps1").write_text(
            self.fake_python.strip() + "\n", encoding="utf-8-sig", newline="\r\n"
        )

    def set_runtime(self, version: str | None, *, retain: bool = False):
        payload = {
            "plugin_version": self.plugin_version,
            "runtime_version": version or "",
            "original_runtime_version": version or "",
            "broker_running": False,
            "broker_build": "",
            "broker_edge_state": "STARTING",
            "prior_broker_build": f"{version}-prior-build" if version else "",
        }
        self.runtime_state.write_text(json.dumps(payload), encoding="utf-8")
        if version and retain:
            wheel_store = self.local_app_data / "AvayaCaseReview/runtime-wheels"
            wheel_store.mkdir(parents=True, exist_ok=True)
            (wheel_store / f"avaya_case_review_runtime-{version}-py3-none-any.whl").write_bytes(
                b"fixture"
            )

    def runtime_version(self):
        payload = json.loads(self.runtime_state.read_text(encoding="utf-8-sig"))
        return payload["runtime_version"] or None

    def _build_existing_install(self):
        self.target_plugin.mkdir(parents=True)
        (self.target_plugin / "old-plugin.bin").write_bytes(b"old plugin\x00")
        self.target_gmail.mkdir(parents=True)
        (self.target_gmail / "gmail_mcp_server.py").write_bytes(b"old gmail\x00")
        (self.target_gmail / "gmail_brokerctl.py").write_text(
            self.fake_brokerctl, encoding="utf-8", newline="\n"
        )
        (self.target_gmail / "unrelated.txt").write_bytes(b"unrelated\x00")
        self.target_case.mkdir(parents=True)
        (self.target_case / "casetomd_mcp_bridge.py").write_bytes(b"old case\x00")
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(b'{"existing":"config"}\r\n')

    def snapshot(self):
        return {
            "plugin": directory_bytes(self.target_plugin),
            "gmail": directory_bytes(self.target_gmail),
            "case": directory_bytes(self.target_case),
            "config": self.config.read_bytes(),
        }

    def run(
        self,
        verify_exits: str,
        *,
        login_exit: int = 0,
        login_sleep: float = 0,
        login_timeout: int = 2,
        status_exit: int = 0,
        stop_exit: int = 20,
        start_exit: int = 0,
        rollback_block: bool = False,
        blocked_backup_parent: bool = False,
        skip_dependency_install: bool = True,
        runtime_rollback_exit: int = 0,
        early_restore_failure: bool = False,
        prior_broker_running: bool = False,
        prior_broker_build: str | None = None,
        python_version: str = "3.14.0",
    ) -> subprocess.CompletedProcess:
        runtime_state = json.loads(self.runtime_state.read_text(encoding="utf-8"))
        if prior_broker_running:
            build_id = prior_broker_build or runtime_state["prior_broker_build"]
            runtime_state["broker_running"] = True
            runtime_state["broker_build"] = build_id
            runtime_state["broker_edge_state"] = "AUTHENTICATED"
            self.runtime_state.write_text(json.dumps(runtime_state), encoding="utf-8")
            broker_state = self.local_app_data / "AvayaCaseReview/gmail-broker/state.json"
            broker_state.parent.mkdir(parents=True, exist_ok=True)
            broker_state.write_text(
                json.dumps({"pid": 0, "build_id": build_id}), encoding="utf-8"
            )
        environment = os.environ.copy()
        environment.update(
            {
                "SETUP_FIXTURE_EVENTS": str(self.events),
                "SETUP_FIXTURE_COUNTER": str(self.counter),
                "SETUP_FIXTURE_ENVIRONMENTS": str(self.environments),
                "SETUP_FIXTURE_VERIFY_EXITS": verify_exits,
                "SETUP_FIXTURE_LOGIN_EXIT": str(login_exit),
                "SETUP_FIXTURE_LOGIN_SLEEP": str(login_sleep),
                "SETUP_FIXTURE_STATUS_EXIT": str(status_exit),
                "SETUP_FIXTURE_STOP_EXIT": str(stop_exit),
                "SETUP_FIXTURE_START_EXIT": str(start_exit),
                "SETUP_FIXTURE_ROLLBACK_BLOCK": "1" if rollback_block else "0",
                "SETUP_FIXTURE_CONFIG": str(self.config),
                "SETUP_FIXTURE_RUNTIME_STATE": str(self.runtime_state),
                "SETUP_FIXTURE_RUNTIME_ROLLBACK_EXIT": str(runtime_rollback_exit),
                "SETUP_FIXTURE_EXPECTED_BUILD_ID": BROKER_BUILD_ID,
                "SETUP_FIXTURE_BROKER_STATE": str(
                    self.local_app_data / "AvayaCaseReview/gmail-broker/state.json"
                ),
                "SETUP_FIXTURE_PYTHON_VERSION": python_version,
                "SETUP_FIXTURE_REAL_PYTHON": sys.executable,
                "SETUP_FIXTURE_PYTHON": str(self.bin_dir / "python.ps1"),
                "SETUP_FIXTURE_EARLY_RESTORE_FAILURE": (
                    "1" if early_restore_failure else "0"
                ),
                "SETUP_FIXTURE_TARGET_PLUGIN": str(self.target_plugin),
            }
        )
        environment["PATH"] = str(self.bin_dir) + os.pathsep + environment["PATH"]
        if blocked_backup_parent:
            blocked = self.root / "blocked-temp"
            blocked.write_bytes(b"not a directory")
            environment["TEMP"] = str(blocked)
            environment["TMP"] = str(blocked)
        arguments = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.source / "setup_env.ps1"),
                "-InstallUserHome",
                str(self.user),
                "-InstallLocalAppData",
                str(self.local_app_data),
                "-LoginTimeoutSeconds",
                str(login_timeout),
            ]
        if skip_dependency_install:
            arguments.append("-SkipDependencyInstall")
        return subprocess.run(
            arguments,
            cwd=self.source,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

    def event_lines(self):
        if not self.events.exists():
            return []
        return [
            line.lstrip("\ufeff")
            for line in self.events.read_text(encoding="utf-8").splitlines()
        ]

    def broker_event_lines(self):
        broker_commands = {"verify-bridge", "login", "stop", "status", "start"}
        return [event for event in self.event_lines() if event in broker_commands]

    def environment_records(self):
        if not self.environments.exists():
            return []
        return [
            json.loads(line)
            for line in self.environments.read_text(encoding="utf-8-sig").splitlines()
        ]


class InstallerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = read_setup()

    def test_running_broker_is_stopped_and_waited_before_gmail_copy(self):
        stop_call = self.script.find("$BrokerStopResult = Stop-RunningGmailBroker")
        deploy_loop = self.script.find("foreach ($GmailDeploymentFile")

        self.assertGreaterEqual(stop_call, 0)
        self.assertGreaterEqual(deploy_loop, 0)
        self.assertLess(stop_call, deploy_loop)
        for marker in (
            "gmail_brokerctl.py",
            "Wait-GmailBrokerExit",
            "Get-CimInstance Win32_Process",
            "edge_broker_profile",
        ):
            self.assertIn(marker, self.script)

    def test_bridge_preflight_precedes_plugin_and_mcp_replacement(self):
        verify = self.script.index("verify-bridge")
        plugin_copy = self.script.index(
            "Copy-Item -LiteralPath $SourcePluginDir -Destination $TargetPluginDir"
        )
        config_update = self.script.index("Update-McpConfiguration `", verify)

        self.assertLess(verify, plugin_copy)
        self.assertLess(verify, config_update)

    def test_canonical_broker_build_is_validated_before_live_or_mutating_work(self):
        build_preflight = self.script.index(
            "$ExpectedBrokerBuildId = Get-CanonicalBrokerBuildId `"
        )
        live_preflight = self.script.index('-Stage "verify-bridge"')
        plugin_copy = self.script.index(
            "Copy-Item -LiteralPath $SourcePluginDir -Destination $TargetPluginDir"
        )
        config_update = self.script.index("Update-McpConfiguration `", live_preflight)

        self.assertLess(build_preflight, live_preflight)
        self.assertLess(build_preflight, plugin_copy)
        self.assertLess(build_preflight, config_update)

    def test_missing_or_malformed_canonical_broker_aborts_before_live_preflight(self):
        for mode in ("missing", "malformed"):
            with self.subTest(mode=mode):
                fixture = SetupInstallFixture()
                self.addCleanup(fixture.close)
                broker_module = (
                    fixture.source
                    / "avaya_case_review_runtime/gmail_edge_broker.py"
                )
                if mode == "missing":
                    broker_module.unlink()
                else:
                    broker_module.write_text(
                        'build_id: str = "not valid whitespace"\n',
                        encoding="utf-8",
                    )
                before = fixture.snapshot()

                completed = fixture.run("0")

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(
                    "canonical gmail broker",
                    (completed.stdout + completed.stderr).lower(),
                )
                self.assertEqual(fixture.broker_event_lines(), [])
                self.assertEqual(fixture.snapshot(), before)

    def test_both_bridge_preflights_pass_explicit_release_identity_inputs(self):
        argument_blocks = re.findall(
            r'-Stage "verify-bridge(?: retry)?"\s+`\s+'
            r'-Command \$PythonCommand\s+`\s+'
            r'-Arguments @\((?P<arguments>.*?)\)\s+`',
            self.script,
            flags=re.DOTALL,
        )
        self.assertEqual(len(argument_blocks), 2)
        for arguments in argument_blocks:
            with self.subTest(arguments=arguments):
                self.assertIn('"--source", $BridgeSourcePath', arguments)
                self.assertIn('"--attestation", $BridgeAttestationPath', arguments)
                self.assertIn('"--plugin-version", $PluginVersion', arguments)

    def test_plugin_copy_uses_literal_source_and_destination_paths(self):
        self.assertIn(
            "Copy-Item -LiteralPath $SourcePluginDir -Destination $TargetPluginDir",
            self.script,
        )
        self.assertNotIn("Copy-Item -Path $SourcePluginDir", self.script)

    def test_incompatible_bridge_preserves_prior_install_byte_for_byte(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("30")

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.broker_event_lines(), ["verify-bridge", "stop"])
        self.assertEqual(fixture.snapshot(), before)

    def test_invalid_local_attestation_stops_before_broker_or_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()
        attestation = fixture.source / "tools/gmail/cloud/bridge_release_attestation.json"
        attestation.write_text('{"invalid":true}', encoding="utf-8")

        completed = fixture.run("0")

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.broker_event_lines(), [])
        self.assertEqual(fixture.snapshot(), before)

    def test_runtime_and_plugin_version_mismatch_stops_before_commands_or_mutation(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()
        pyproject = fixture.source / "pyproject.toml"
        pyproject.write_text(
            pyproject.read_text(encoding="utf-8").replace(
                f'version = "{fixture.plugin_version}"', 'version = "9.9.9"'
            ),
            encoding="utf-8",
        )

        completed = fixture.run("0")

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("runtime package version", (completed.stdout + completed.stderr).lower())
        self.assertEqual(fixture.event_lines(), [])
        self.assertEqual(fixture.snapshot(), before)

    def test_python_3_9_is_rejected_before_attestation_or_runtime_work(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("0", python_version="3.9.19")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("python 3.10", (completed.stdout + completed.stderr).lower())
        self.assertEqual(fixture.event_lines(), ["python-version"])
        self.assertEqual(fixture.snapshot(), before)

    def test_running_old_broker_is_stopped_before_candidate_preflight(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime("1.9.0", retain=True)

        completed = fixture.run(
            "0,0",
            skip_dependency_install=False,
            prior_broker_running=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = fixture.broker_event_lines()
        self.assertEqual(events[:2], ["stop", "verify-bridge"])
        self.assertNotIn("old-broker-rejected-bridge-capabilities", fixture.event_lines())

    def test_auth_required_runs_one_login_and_one_preflight_retry(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run("10,0,0")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = fixture.broker_event_lines()
        self.assertEqual(events.count("login"), 1)
        self.assertEqual(events.count("verify-bridge"), 3)
        self.assertLess(events.index("login"), events.index("stop"))
        self.assertEqual(
            (fixture.target_plugin / "new-plugin.txt").read_text(encoding="utf-8"),
            "new plugin",
        )
        self.assertEqual(
            (fixture.target_gmail / "gmail_mcp_server.py").read_text(
                encoding="utf-8"
            ),
            "# new\n",
        )
        self.assertTrue((fixture.target_gmail / "cloud/bridge_identity.py").is_file())
        self.assertFalse((fixture.target_gmail / "cloud/GmailMcpBridge.gs").exists())
        self.assertEqual(
            json.loads(fixture.config.read_text(encoding="utf-8-sig"))["existing"],
            "config",
        )

    def test_all_broker_subprocesses_use_selected_install_environment(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run("10,0")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        records = fixture.environment_records()
        self.assertGreaterEqual(len(records), 5)
        for record in records:
            self.assertEqual(record["USERPROFILE"], str(fixture.user))
            self.assertEqual(record["LOCALAPPDATA"], str(fixture.local_app_data))

    def test_unavailable_bridge_stops_before_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("20")

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.broker_event_lines(), ["verify-bridge", "stop"])
        self.assertEqual(fixture.snapshot(), before)

    def test_login_failure_stops_before_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("10", login_exit=30)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.broker_event_lines(), ["verify-bridge", "login", "stop"])
        self.assertEqual(fixture.snapshot(), before)

    def test_auth_required_after_retry_stops_before_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("10,10")

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(
            fixture.broker_event_lines(),
            ["verify-bridge", "login", "verify-bridge", "stop"],
        )
        self.assertEqual(fixture.snapshot(), before)

    def test_login_timeout_stops_before_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("10", login_sleep=5, login_timeout=1)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        output = completed.stdout + completed.stderr
        self.assertIn(
            "Gmail authentication is required. Waiting for Managed Edge SSO/MFA...",
            output,
        )
        self.assertIn("Stage 'Gmail broker login' timed out after 1 seconds.", output)
        broker_events = fixture.broker_event_lines()
        self.assertEqual(broker_events[0], "verify-bridge")
        self.assertEqual(broker_events[-1], "stop")
        events = fixture.event_lines()
        preflight_events = {
            "python-version",
            "attestation-validate",
            f"runtime-version:{fixture.plugin_version}",
            "runtime-smoke",
            "verify-bridge",
            "login",
            "stop",
        }
        self.assertEqual(
            [event for event in events if event not in preflight_events],
            [],
            events,
        )
        self.assertEqual(fixture.snapshot(), before)

    def test_login_timeout_defaults_to_330_seconds(self):
        self.assertRegex(
            self.script,
            r"\[int\]\$LoginTimeoutSeconds\s*=\s*330",
        )

    def test_post_copy_failure_restores_backups_byte_for_byte(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("0", status_exit=30)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(
            fixture.broker_event_lines(),
            ["verify-bridge", "stop", "verify-bridge", "status", "stop"],
        )
        self.assertEqual(fixture.snapshot(), before)

    def test_rollback_failure_preserves_backup_and_reports_recovery_location(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run("0", status_exit=30, rollback_block=True)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        output = completed.stdout + completed.stderr
        match = re.search(r"RECOVERY_BACKUP=(?P<path>[^\r\n]+)", output)
        self.assertIsNotNone(match, output)
        backup = Path(match.group("path").strip())
        self.addCleanup(shutil.rmtree, backup, True)
        self.assertTrue(backup.is_dir())
        self.assertEqual(
            (backup / "mcp_config.json").read_bytes(),
            b'{"existing":"config"}\r\n',
        )

    def test_runtime_smoke_workspace_failure_precedes_broker_and_file_mutation(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("0", blocked_backup_parent=True)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.broker_event_lines(), [])
        self.assertEqual(fixture.snapshot(), before)

    def test_restart_failure_preserves_verified_backup(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run(
            "0,0",
            status_exit=30,
            start_exit=20,
            prior_broker_running=True,
        )

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        output = completed.stdout + completed.stderr
        match = re.search(r"RECOVERY_BACKUP=(?P<path>[^\r\n]+)", output)
        self.assertIsNotNone(match, output)
        backup = Path(match.group("path").strip())
        self.addCleanup(shutil.rmtree, backup, True)
        self.assertTrue(backup.is_dir())
        self.assertEqual(
            (backup / "mcp_config.json").read_bytes(),
            b'{"existing":"config"}\r\n',
        )

    def test_runtime_build_validate_install_and_smoke_precede_bridge_and_copy(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime(None)

        completed = fixture.run("0", skip_dependency_install=False)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = fixture.event_lines()
        expected = [
            "dependency-install",
            "runtime-build",
            f"wheel-validate:avaya_case_review_runtime-{fixture.plugin_version}-py3-none-any.whl",
            f"runtime-install:avaya_case_review_runtime-{fixture.plugin_version}-py3-none-any.whl",
            "runtime-smoke",
            "verify-bridge",
        ]
        positions = [events.index(event) for event in expected]
        self.assertEqual(positions, sorted(positions), events)
        self.assertEqual(fixture.runtime_version(), fixture.plugin_version)
        self.assertTrue(
            (
                fixture.local_app_data
                / "AvayaCaseReview/runtime-wheels"
                / f"avaya_case_review_runtime-{fixture.plugin_version}-py3-none-any.whl"
            ).is_file()
        )
        self.assertEqual(
            (fixture.target_plugin / "new-plugin.txt").read_text(encoding="utf-8"),
            "new plugin",
        )

    def test_skip_dependency_install_requires_exact_runtime_and_never_changes_pip(self):
        for installed, succeeds in (
            (None, False),
            ("1.9.0", False),
            ("1.11.0", True),
        ):
            with self.subTest(installed=installed):
                fixture = SetupInstallFixture()
                self.addCleanup(fixture.close)
                fixture.set_runtime(installed)
                before = fixture.snapshot()

                completed = fixture.run("0")

                self.assertEqual(completed.returncode == 0, succeeds, completed.stderr)
                events = fixture.event_lines()
                self.assertFalse(any(event.startswith("dependency-") for event in events))
                self.assertFalse(any(event.startswith("runtime-install:") for event in events))
                self.assertNotIn("runtime-build", events)
                if succeeds:
                    self.assertLess(events.index("runtime-smoke"), events.index("verify-bridge"))
                else:
                    self.assertNotIn("verify-bridge", events)
                    self.assertEqual(fixture.snapshot(), before)

    def test_prior_runtime_without_retained_wheel_blocks_before_every_mutation(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime("1.9.0")
        before = fixture.snapshot()

        completed = fixture.run("0", skip_dependency_install=False)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("retained wheel", (completed.stdout + completed.stderr).lower())
        events = fixture.event_lines()
        self.assertFalse(any(event.startswith("dependency-") for event in events))
        self.assertNotIn("runtime-build", events)
        self.assertNotIn("verify-bridge", events)
        self.assertNotIn("stop", events)
        self.assertEqual(fixture.snapshot(), before)

    def test_candidate_preflight_failure_restores_previous_runtime_and_prior_broker(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime("1.9.0", retain=True)
        before = fixture.snapshot()

        completed = fixture.run(
            "30",
            skip_dependency_install=False,
            prior_broker_running=True,
        )

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.runtime_version(), "1.9.0")
        events = fixture.event_lines()
        prior_stop = events.index("stop")
        bridge = events.index("verify-bridge")
        candidate_stop = events.index("stop", prior_stop + 1)
        rollback = events.index(
            "runtime-install:avaya_case_review_runtime-1.9.0-py3-none-any.whl"
        )
        restart = events.index("start")
        restored_status = events.index("status")
        self.assertEqual(
            [prior_stop, bridge, candidate_stop, rollback, restart, restored_status],
            sorted([prior_stop, bridge, candidate_stop, rollback, restart, restored_status]),
        )
        self.assertEqual(fixture.snapshot(), before)

    def test_deployment_failure_restores_runtime_then_files_then_prior_broker(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime("1.9.0", retain=True)
        before = fixture.snapshot()

        completed = fixture.run(
            "0,30",
            prior_broker_running=True,
            skip_dependency_install=False,
        )

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.snapshot(), before)
        self.assertEqual(fixture.runtime_version(), "1.9.0")
        events = fixture.event_lines()
        candidate_stop = events.index("stop", events.index("verify-bridge") + 1)
        runtime_restore = events.index(
            "runtime-install:avaya_case_review_runtime-1.9.0-py3-none-any.whl"
        )
        file_restore = next(
            index for index, event in enumerate(events) if event.startswith("restore-file:")
        )
        restart = events.index("start")
        restored_status = events.index("status")
        self.assertEqual(
            [candidate_stop, runtime_restore, file_restore, restart, restored_status],
            sorted([candidate_stop, runtime_restore, file_restore, restart, restored_status]),
        )

    def test_deployed_verify_completes_probe_before_status_build_check(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run("0,0")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = fixture.broker_event_lines()
        self.assertEqual(events.count("verify-bridge"), 2)
        final_verify = len(events) - 1 - events[::-1].index("verify-bridge")
        status = len(events) - 1 - events[::-1].index("status")
        self.assertLess(final_verify, status)

    def test_early_restore_failure_does_not_skip_later_targets_or_broker_restart(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime("1.9.0", retain=True)
        before = fixture.snapshot()

        completed = fixture.run(
            "0",
            status_exit=30,
            skip_dependency_install=False,
            early_restore_failure=True,
            prior_broker_running=True,
        )

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        events = fixture.event_lines()
        self.assertNotIn("start", events)
        self.assertIn(
            "runtime-install:avaya_case_review_runtime-1.9.0-py3-none-any.whl",
            events,
        )
        self.assertEqual(directory_bytes(fixture.target_gmail), before["gmail"])
        self.assertEqual(directory_bytes(fixture.target_case), before["case"])
        self.assertEqual(fixture.config.read_bytes(), before["config"])
        self.assertEqual(fixture.runtime_version(), "1.9.0")
        output = completed.stdout + completed.stderr
        match = re.search(r"RECOVERY_BACKUP=(?P<path>[^\r\n]+)", output)
        self.assertIsNotNone(match, output)
        backup = Path(match.group("path").strip())
        self.addCleanup(shutil.rmtree, backup, True)
        self.assertTrue(backup.is_dir())
        self.assertIn("plugin restoration", output.lower())

    def test_deployment_failure_without_prior_runtime_uninstalls_only_distribution(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime(None)
        before = fixture.snapshot()

        completed = fixture.run("0", status_exit=30, skip_dependency_install=False)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.snapshot(), before)
        self.assertIsNone(fixture.runtime_version())
        events = fixture.event_lines()
        self.assertEqual(events.count("runtime-uninstall:avaya-case-review-runtime"), 1)

    def test_runtime_rollback_failure_preserves_backup_and_combines_stage_names(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime("1.9.0", retain=True)

        completed = fixture.run(
            "0",
            status_exit=30,
            skip_dependency_install=False,
            runtime_rollback_exit=42,
        )

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        output = completed.stdout + completed.stderr
        self.assertIn("deployed gmail broker validation", output.lower())
        self.assertIn("runtime restoration", output.lower())
        match = re.search(r"RECOVERY_BACKUP=(?P<path>[^\r\n]+)", output)
        self.assertIsNotNone(match, output)
        backup = Path(match.group("path").strip())
        self.addCleanup(shutil.rmtree, backup, True)
        self.assertTrue(backup.is_dir())
        self.assertEqual(
            (backup / "mcp_config.json").read_bytes(),
            b'{"existing":"config"}\r\n',
        )

    def test_runtime_and_broker_commands_use_selected_install_environment(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        fixture.set_runtime(None)

        completed = fixture.run("0", skip_dependency_install=False)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        records = fixture.environment_records()
        relevant = [
            record
            for record in records
            if record["command"].startswith(("runtime-", "pip-", "deployed-shim"))
            or record["command"] in {"verify-bridge", "stop", "status"}
        ]
        self.assertTrue(relevant)
        for record in relevant:
            self.assertEqual(record["USERPROFILE"], str(fixture.user))
            self.assertEqual(record["LOCALAPPDATA"], str(fixture.local_app_data))

    def test_success_verifies_runtime_and_deployed_shims_from_unrelated_cwd(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run("0")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = fixture.event_lines()
        self.assertEqual(events.count(f"runtime-version:{fixture.plugin_version}"), 2)
        self.assertIn("deployed-shim-import", events)
        self.assertIn("deployed-shim-help", events)
        records = {
            record["command"]: record
            for record in fixture.environment_records()
            if record["command"].startswith("deployed-shim")
        }
        self.assertNotEqual(Path(records["deployed-shim-import"]["cwd"]), fixture.source)
        self.assertEqual(
            records["deployed-shim-import"]["cwd"],
            records["deployed-shim-help"]["cwd"],
        )
        runtime_records = [
            record
            for record in fixture.environment_records()
            if record["command"] == "runtime-installed-version"
        ]
        self.assertEqual(len(runtime_records), 2)
        self.assertNotEqual(Path(runtime_records[-1]["cwd"]), fixture.source)
        self.assertEqual(
            runtime_records[-1]["cwd"],
            records["deployed-shim-import"]["cwd"],
        )

    def test_deployed_bridge_unavailable_is_retried_once_before_rollback(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run("0,20,0")

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(
            fixture.broker_event_lines(),
            ["verify-bridge", "stop", "verify-bridge", "verify-bridge", "status"],
        )

    def test_deployed_allowlist_supports_real_brokerctl_help_and_status(self):
        cloud_match = re.search(
            r"\$GmailCloudDeploymentFiles\s*=\s*@\((.*?)\n\)",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(cloud_match, "cloud Python deployment allowlist missing")
        cloud_files = re.findall(r'"([a-z0-9_]+\.py)"', cloud_match.group(1))
        self.assertEqual(cloud_files, ["bridge_identity.py"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(
                ROOT / "avaya_case_review_runtime",
                root / "avaya_case_review_runtime",
            )
            deployed = root / "tools/gmail"
            deployed.mkdir(parents=True)
            for name in SetupInstallFixture.gmail_files:
                shutil.copy2(GMAIL_SOURCE / name, deployed / name)
            (deployed / "cloud").mkdir()
            for name in cloud_files:
                shutil.copy2(GMAIL_SOURCE / "cloud" / name, deployed / "cloud" / name)

            help_result = subprocess.run(
                ["python", str(deployed / "gmail_brokerctl.py"), "--help"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            status_code = '''
from tools.gmail import gmail_brokerctl

class Client:
    def request(self, method, params):
        assert method == "health"
        return {"edge_state": "AUTHENTICATED", "build_id": "source"}

raise SystemExit(gmail_brokerctl.main(["status"], client=Client()))
'''
            status_result = subprocess.run(
                ["python", "-c", status_code],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            self.assertIn('"ok": true', status_result.stdout)
            self.assertFalse((deployed / "cloud/GmailMcpBridge.gs").exists())

    def test_gmail_deployment_is_an_explicit_allowlist(self):
        expected_modules = {
            "gmail_broker_client.py",
            "gmail_broker_protocol.py",
            "gmail_broker_state.py",
            "gmail_brokerctl.py",
            "gmail_edge_broker.py",
            "gmail_edge_common.py",
            "gmail_edge_poc.py",
            "gmail_legacy_backend.py",
            "gmail_mcp_server.py",
            "gmail_playwright.py",
        }
        match = re.search(
            r"\$GmailDeploymentFiles\s*=\s*@\((.*?)\n\)",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "explicit Gmail deployment allowlist is missing")
        manifest_lines = [
            line.strip()
            for line in match.group(1).splitlines()
            if line.strip()
        ]
        for line in manifest_lines[:-1]:
            self.assertTrue(line.endswith(","), f"missing array separator: {line}")
        deployed = set(re.findall(r'"([a-z0-9_]+\.py)"', match.group(1)))
        self.assertEqual(deployed, expected_modules)
        actual_modules = {p.name for p in (ROOT / "tools" / "gmail").glob("*.py")}
        self.assertEqual(
            deployed,
            actual_modules,
            "GmailDeploymentFiles drifted from tools/gmail/*.py; a new runtime "
            "module would be silently missing from Antigravity installs",
        )
        self.assertNotRegex(
            self.script,
            r'Copy-Item\s+-Path\s+"\$SourceGmailDir\\\*"',
        )

    def test_profile_contents_are_compared_around_deployment(self):
        for marker in (
            "Get-ProfileBaseline",
            "Assert-ProfileBaselineUnchanged",
            "Get-FileSha256",
            "chrome_profile",
            "edge_broker_profile",
        ):
            self.assertIn(marker, self.script)

        before = self.script.index("$LegacyProfileBaselineBefore")
        deploy = self.script.index("foreach ($GmailDeploymentFile")
        after = self.script.find("Assert-ProfileBaselineUnchanged `", deploy)
        self.assertLess(before, deploy)
        self.assertLess(deploy, after)

    def test_config_migration_is_powershell_51_safe_and_preserving(self):
        self.assertNotIn("ConvertFrom-Json -AsHashtable", self.script)
        for marker in (
            "Update-McpConfiguration",
            "Set-ObjectProperty",
            "Add-Member",
            '"GMAIL_BACKEND"',
            '"edge_broker"',
        ):
            self.assertIn(marker, self.script)

    def test_state_directory_is_created_and_secured_by_shared_acl_code(self):
        for marker in (
            '"AvayaCaseReview\\gmail-broker"',
            "New-Item -ItemType Directory -Path $BrokerStateDir -Force",
            "apply_windows_acl",
        ):
            self.assertIn(marker, self.script)

    def test_login_is_conditional_on_auth_required_preflight(self):
        verify_match = re.search(
            r"\$BridgeVerifyResult\s*=\s*Invoke-BoundedCommand.*?"
            r"if\s*\(\$BridgeVerifyResult\.ExitCode\s+-eq\s+10\)\s*\{.*?"
            r'-Arguments\s+@\("-B",\s+\$SourceBrokerCtlPath,\s+"login"\).*?'
            r'\-Stage\s+"verify-bridge retry"',
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(verify_match)
        self.assertEqual(
            len(
                re.findall(
                    r'(?m)^\s*-Arguments\s+@\("-B",\s+\$SourceBrokerCtlPath,\s+"login"\)\s*`$',
                    self.script,
                )
            ),
            1,
        )

    def test_running_build_id_is_checked_against_canonical_runtime_package(self):
        for marker in (
            "function Get-CanonicalBrokerBuildId",
            '$CanonicalRuntimePackageRoot = Join-Path $ScriptDir "avaya_case_review_runtime"',
            "$ExpectedBrokerBuildId = Get-CanonicalBrokerBuildId `",
            "-RuntimePackageRoot $CanonicalRuntimePackageRoot",
            "Assert-BrokerBuildId",
            'result.build_id',
        ):
            self.assertIn(marker, self.script)
        self.assertNotIn("$InstalledBrokerScript", self.script)
        self.assertNotIn("Get-InstalledBrokerBuildId", self.script)

    def test_powershell_fixture_preserves_existing_config(self):
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(FIXTURE),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["result"], "CONFIG_MIGRATION_OK")
        self.assertTrue(payload["unrelated_server_preserved"])
        self.assertTrue(payload["gmail_keys_preserved"])
        self.assertTrue(payload["gmail_env_preserved"])
        self.assertEqual(payload["backend"], "edge_broker")
        self.assertTrue(payload["profile_baseline_verified"])
        self.assertEqual(payload["build_id"], BROKER_BUILD_ID)
        self.assertTrue(payload["stale_state_ignored"])
        self.assertEqual(payload["deployment_allowlist_count"], 10)

    def test_windows_scripts_keep_bom_and_crlf(self):
        for path in (SETUP, FIXTURE):
            with self.subTest(path=path.name):
                content = path.read_bytes()
                self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
                self.assertNotRegex(content.decode("utf-8-sig"), r"(?<!\r)\n")


if __name__ == "__main__":
    unittest.main()
