import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.gmail.cloud.bridge_identity import write_attestation


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

build_id: str = "source"
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
    exits = [int(value) for value in os.environ["SETUP_FIXTURE_VERIFY_EXITS"].split(",")]
    index = int(counter_path.read_text(encoding="ascii")) if counter_path.exists() else 0
    counter_path.write_text(str(index + 1), encoding="ascii")
    raise SystemExit(exits[min(index, len(exits) - 1)])
if command == "login":
    time.sleep(float(os.environ.get("SETUP_FIXTURE_LOGIN_SLEEP", "0")))
    raise SystemExit(int(os.environ.get("SETUP_FIXTURE_LOGIN_EXIT", "0")))
if command == "stop":
    raise SystemExit(int(os.environ.get("SETUP_FIXTURE_STOP_EXIT", "20")))
if command == "status":
    if os.environ.get("SETUP_FIXTURE_ROLLBACK_BLOCK") == "1":
        target = Path(os.environ["SETUP_FIXTURE_CONFIG"])
        target.unlink()
        target.mkdir()
        (target / "block.txt").write_text("block", encoding="ascii")
    print(json.dumps({"ok": True, "result": {"build_id": "source"}}))
    raise SystemExit(int(os.environ.get("SETUP_FIXTURE_STATUS_EXIT", "0")))
if command == "start":
    raise SystemExit(int(os.environ.get("SETUP_FIXTURE_START_EXIT", "0")))
raise SystemExit(30)
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
        self.target_plugin = (
            self.user / ".gemini/config/plugins/avaya-case-review"
        )
        self.target_gmail = self.user / ".gemini/tools/gmail"
        self.target_case = self.user / ".gemini/tools/casetomd"
        self.config = self.user / ".gemini/config/mcp_config.json"
        self._build_source()
        self._build_existing_install()

    def close(self):
        self.temporary.cleanup()

    def _write(self, relative: str, content: str):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return path

    def _build_source(self):
        (self.source / "tools/installer").mkdir(parents=True)
        shutil.copy2(SETUP, self.source / "setup_env.ps1")
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
    ) -> subprocess.CompletedProcess:
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
            }
        )
        if blocked_backup_parent:
            blocked = self.root / "blocked-temp"
            blocked.write_bytes(b"not a directory")
            environment["TEMP"] = str(blocked)
            environment["TMP"] = str(blocked)
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.source / "setup_env.ps1"),
                "-SkipDependencyInstall",
                "-InstallUserHome",
                str(self.user),
                "-InstallLocalAppData",
                str(self.local_app_data),
                "-LoginTimeoutSeconds",
                str(login_timeout),
            ],
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
        return self.events.read_text(encoding="utf-8").splitlines()

    def environment_records(self):
        if not self.environments.exists():
            return []
        return [
            json.loads(line)
            for line in self.environments.read_text(encoding="utf-8").splitlines()
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
                self.assertEqual(fixture.event_lines(), [])
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
        self.assertEqual(fixture.event_lines(), ["verify-bridge"])
        self.assertEqual(fixture.snapshot(), before)

    def test_invalid_local_attestation_stops_before_broker_or_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()
        attestation = fixture.source / "tools/gmail/cloud/bridge_release_attestation.json"
        attestation.write_text('{"invalid":true}', encoding="utf-8")

        completed = fixture.run("0")

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.event_lines(), [])
        self.assertEqual(fixture.snapshot(), before)

    def test_auth_required_runs_one_login_and_one_preflight_retry(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run("10,0")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = fixture.event_lines()
        self.assertEqual(events.count("login"), 1)
        self.assertEqual(events.count("verify-bridge"), 2)
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
        self.assertEqual(fixture.event_lines(), ["verify-bridge"])
        self.assertEqual(fixture.snapshot(), before)

    def test_login_failure_stops_before_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("10", login_exit=30)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.event_lines(), ["verify-bridge", "login"])
        self.assertEqual(fixture.snapshot(), before)

    def test_auth_required_after_retry_stops_before_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("10,10")

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(
            fixture.event_lines(),
            ["verify-bridge", "login", "verify-bridge"],
        )
        self.assertEqual(fixture.snapshot(), before)

    def test_login_timeout_stops_before_replacement(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("10", login_sleep=5, login_timeout=1)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("timed out", (completed.stdout + completed.stderr).lower())
        self.assertEqual(fixture.event_lines(), ["verify-bridge", "login"])
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
            fixture.event_lines(),
            ["verify-bridge", "stop", "status"],
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

    def test_backup_failure_after_stop_restarts_prior_broker_without_mutation(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)
        before = fixture.snapshot()

        completed = fixture.run("0", stop_exit=0, blocked_backup_parent=True)

        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(fixture.event_lines(), ["verify-bridge", "stop", "start"])
        self.assertEqual(fixture.snapshot(), before)

    def test_restart_failure_preserves_verified_backup(self):
        fixture = SetupInstallFixture()
        self.addCleanup(fixture.close)

        completed = fixture.run("0", status_exit=30, stop_exit=0, start_exit=20)

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
        self.assertEqual(payload["build_id"], "source")
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
