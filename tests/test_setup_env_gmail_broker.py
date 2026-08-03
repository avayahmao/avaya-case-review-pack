import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup_env.ps1"
FIXTURE = ROOT / "tests/fixtures/run_setup_config_migration.ps1"


def read_setup() -> str:
    return SETUP.read_text(encoding="utf-8-sig")


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
            "Get-FileHash",
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

    def test_login_is_conditional_on_auth_required_status(self):
        status_match = re.search(
            r"python\s+\$BrokerCtlPath\s+status.*?"
            r"\$BrokerStatusExit\s*=\s*\$LASTEXITCODE.*?"
            r"if\s*\(\$BrokerStatusExit\s+-eq\s+10\)\s*\{.*?"
            r"python\s+\$BrokerCtlPath\s+login",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(status_match)
        self.assertEqual(
            len(
                re.findall(
                    r"(?m)^\s*python\s+\$BrokerCtlPath\s+login\s*$",
                    self.script,
                )
            ),
            1,
        )

    def test_running_build_id_is_checked_against_installed_source(self):
        for marker in (
            "Get-InstalledBrokerBuildId",
            "Assert-BrokerBuildId",
            'result.build_id',
            "gmail_edge_broker.py",
        ):
            self.assertIn(marker, self.script)

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
