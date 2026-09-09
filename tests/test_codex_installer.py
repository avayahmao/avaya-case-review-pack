import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install-codex.ps1"
WINDOWS_COMMON = ROOT / "tools" / "installer" / "windows_common.ps1"


CODEX_SHIM = r"""
function Add-TestEvent {
    param([Parameter(Mandatory = $true)][string]$Name)
    Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG -Value $Name -Encoding UTF8
}

if ($args.Count -ge 4 -and $args[0] -eq "plugin" -and $args[1] -eq "marketplace" -and $args[2] -eq "add") {
    Add-TestEvent "marketplace-add"
    Add-TestEvent ("source=" + [string]$args[3])
    if ($env:AVAYA_INSTALL_TEST_MODE -eq "hang-marketplace") {
        & powershell.exe -NoProfile -Command 'Start-Sleep -Seconds 2; Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG -Value "descendant-survived" -Encoding UTF8'
        Start-Sleep -Seconds 30
    }
    if ($env:AVAYA_INSTALL_TEST_MODE -eq "cleanup-failure") {
        Start-Sleep -Seconds 3
        Add-TestEvent "resistant-child-mutated"
    }
    exit 0
}

if ($args.Count -ge 4 -and $args[0] -eq "plugin" -and $args[1] -eq "marketplace" -and $args[2] -eq "list") {
    Add-TestEvent "marketplace-list"
    Write-Output '{"marketplaces":[]}'
    exit 0
}

if ($args.Count -ge 3 -and $args[0] -eq "plugin" -and $args[1] -eq "add") {
    Add-TestEvent "plugin-add"
    exit 0
}

Write-Error "Unexpected codex arguments"
exit 91
"""


PYTHON_SHIM = r"""
Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG -Value "python" -Encoding UTF8
exit 0
"""


class CodexInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.temp_root = Path(self.temporary.name)
        self.bin_dir = self.temp_root / "bin"
        self.bin_dir.mkdir()
        self.log_path = self.temp_root / "events.log"
        self._write_shim("codex.ps1", CODEX_SHIM)
        self._write_shim("python.ps1", PYTHON_SHIM)

    def _write_shim(self, name, source):
        (self.bin_dir / name).write_text(
            source.strip() + "\n", encoding="utf-8-sig", newline="\r\n"
        )

    def _environment(self, mode="normal"):
        environment = os.environ.copy()
        environment["PATH"] = str(self.bin_dir) + os.pathsep + environment["PATH"]
        environment["AVAYA_INSTALL_TEST_LOG"] = str(self.log_path)
        environment["AVAYA_INSTALL_TEST_MODE"] = mode
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
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(INSTALLER),
            "-CloudBridgeVerified",
            "-SkipDependencyInstall",
            "-SkipLogin",
            "-MarketplaceSource",
            source,
            *extra_arguments,
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=self._environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        return result, self._events()

    def _short_marketplace_timeout_fixture(self):
        fixture_root = self.temp_root / "installer"
        for relative_path in (
            ".codex-plugin/plugin.json",
            ".agents/plugins/marketplace.json",
            "tools/gmail/gmail_brokerctl.py",
        ):
            destination = fixture_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative_path, destination)

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
            timeout=10,
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

    def test_unconfirmed_cleanup_is_bounded_sanitized_and_stops_child_mutation(self):
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
        self.assertIn("cleanup failed", result.stderr.lower())
        self.assertIn("marketplace-add", events)
        self.assertNotIn("resistant-child-mutated", events)

    def test_literal_arguments_are_not_reparsed_by_a_shell(self):
        result, events = self.run_installer(source=r"C:\path with spaces\repo")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(r"source=C:\path with spaces\repo", events)

    def test_dry_run_is_offline_and_has_no_state_events(self):
        result, events = self.run_installer("-DryRun")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], events)
        self.assertIn("validate release attestation", result.stdout.lower())
        self.assertIn("verify-bridge", result.stdout)
        self.assertIn("plugin add", result.stdout)


if __name__ == "__main__":
    unittest.main()
