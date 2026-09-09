import json
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install-codex.ps1"
WINDOWS_COMMON = ROOT / "tools" / "installer" / "windows_common.ps1"


CODEX_SHIM = r"""
function Add-TestEvent {
    param([Parameter(Mandatory = $true)][string]$Name)
    Add-Content -LiteralPath $env:AVAYA_INSTALL_TEST_LOG -Value $Name -Encoding UTF8
}

function Read-TestState {
    return Get-Content -LiteralPath $env:AVAYA_INSTALL_TEST_STATE -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-TestState {
    param([Parameter(Mandatory = $true)][pscustomobject]$State)
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $env:AVAYA_INSTALL_TEST_STATE -Encoding UTF8
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
        Write-Error "UNSANITIZED_NEW_MARKETPLACE_ADD"
        exit 32
    }
    $State.marketplace_exists = $true
    $State.marketplace_source = [string]$args[3]
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
                        sourceType = "git"
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
        Write-Error "UNSANITIZED_MARKETPLACE_REMOVE"
        exit 33
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
                version = "1.10.1"
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
    if ($State.fail_stage -like "*new-plugin-add*" -and $State.marketplace_sha -eq $State.target_sha) {
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
        Write-Error "UNSANITIZED_PLUGIN_REMOVE"
        exit 35
    }
    $State.plugin_installed = $false
    $State.plugin_enabled = $false
    Write-TestState $State
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
if ($args.Count -ge 3 -and $args[0] -eq "ls-remote") {
    if ($args.Count -eq 3) {
        Add-TestEvent "git-ls-remote:all"
        Write-Output (([string]$State.target_sha) + "`trefs/heads/release-candidate")
        exit 0
    }
    $RequestedRef = [string]$args[3]
    Add-TestEvent ("git-ls-remote:" + $RequestedRef)
    if ($RequestedRef -match '^[0-9a-fA-F]{40}$') {
        exit 2
    }
    if ($State.annotated_tag) {
        Write-Output ("tag-object-sha`trefs/tags/" + $RequestedRef)
        Write-Output (([string]$State.target_sha) + "`trefs/tags/" + $RequestedRef + "^{}")
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
        existing_sha="",
        target_sha="new-sha",
        target_ref="v1.10.0",
        plugin_installed=False,
        plugin_enabled=False,
        fail_stage="",
        annotated_tag=False,
    ):
        state = {
            "marketplace_exists": bool(existing_sha),
            "marketplace_source": existing_source,
            "marketplace_sha": existing_sha,
            "original_sha": existing_sha,
            "target_sha": target_sha,
            "target_ref": target_ref,
            "plugin_installed": plugin_installed,
            "plugin_enabled": plugin_enabled,
            "fail_stage": fail_stage,
            "annotated_tag": annotated_tag,
        }
        self.state_path.write_text(json.dumps(state), encoding="utf-8-sig")

    def _read_state(self):
        value = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        return SimpleNamespace(**value)

    def _environment(self, mode="normal"):
        environment = os.environ.copy()
        environment["PATH"] = str(self.bin_dir) + os.pathsep + environment["PATH"]
        environment["AVAYA_INSTALL_TEST_LOG"] = str(self.log_path)
        environment["AVAYA_INSTALL_TEST_MODE"] = mode
        environment["AVAYA_INSTALL_TEST_STATE"] = str(self.state_path)
        environment["AVAYA_INSTALL_TEST_MARKETPLACE_ROOT"] = str(
            self.marketplace_root
        )
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

    def run_stateful_installer(
        self,
        *,
        plugin_version="1.10.1",
        existing_source="https://example.invalid/repo",
        existing_sha="",
        target_sha="new-sha",
        plugin_installed=False,
        plugin_enabled=False,
        fail_stage="",
        annotated_tag=False,
        extra_arguments=(),
    ):
        fixture_root = self.temp_root / "stateful-installer"
        for relative_path in (
            ".codex-plugin/plugin.json",
            ".agents/plugins/marketplace.json",
            "tools/gmail/gmail_brokerctl.py",
            "tools/installer/windows_common.ps1",
        ):
            destination = fixture_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative_path, destination)
        shutil.copy2(INSTALLER, fixture_root / INSTALLER.name)

        manifest_path = fixture_root / ".codex-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        manifest["version"] = plugin_version
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8-sig"
        )
        target_ref = f"v{plugin_version}"
        if "-MarketplaceRef" in extra_arguments:
            target_ref = extra_arguments[extra_arguments.index("-MarketplaceRef") + 1]
        self._write_state(
            existing_source=existing_source,
            existing_sha=existing_sha,
            target_sha=target_sha,
            target_ref=target_ref,
            plugin_installed=plugin_installed,
            plugin_enabled=plugin_enabled,
            fail_stage=fail_stage,
            annotated_tag=annotated_tag,
        )
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(fixture_root / INSTALLER.name),
                "-CloudBridgeVerified",
                "-SkipDependencyInstall",
                "-SkipLogin",
                "-MarketplaceSource",
                "https://example.invalid/repo",
                *extra_arguments,
            ],
            cwd=fixture_root,
            env=self._environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        return result, self._events(), self._read_state()

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
        self.assertEqual([], events)
        self.assertIn("validate release attestation", result.stdout.lower())
        self.assertIn("verify-bridge", result.stdout)
        self.assertIn("plugin add", result.stdout)


if __name__ == "__main__":
    unittest.main()
