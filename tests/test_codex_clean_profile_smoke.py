import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.gmail.cloud.bridge_identity import write_attestation


ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = ROOT / "tests" / "fixtures" / "run_codex_clean_profile_smoke.ps1"


class CodexCleanProfileSmokeTests(unittest.TestCase):
    def test_smoke_script_is_a_windows_safe_entry_point(self):
        raw = SMOKE_SCRIPT.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_smoke_script_isolated_and_non_destructive(self):
        script = SMOKE_SCRIPT.read_text(encoding="utf-8-sig")
        self.assertIn("$TestCodexHome", script)
        self.assertIn("$PreviousCodexHome", script)
        self.assertIn("$PreviousLocalAppData", script)
        self.assertIn("finally", script)
        self.assertIn("-SkipLogin", script)
        self.assertNotIn("Remove-Item -Recurse -Force $env:CODEX_HOME", script)

    def test_automated_smoke_uses_fake_commands_and_restores_caller_profile(self):
        with TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            attestation = temporary_root / "bridge_release_attestation.json"
            write_attestation(
                ROOT / "tools/gmail/cloud/GmailMcpBridge.gs",
                attestation,
                "1.10.1",
                "2026-09-09T00:00:00Z",
            )
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(temporary_root / "caller-profile")
            environment["AVAYA_CLEAN_PROFILE_STATE"] = "caller-owned-state"
            environment["AVAYA_CLEAN_PROFILE_ADAPTER_ROOT"] = "caller-owned-adapter"
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(SMOKE_SCRIPT),
                    "-RepositoryRoot",
                    str(ROOT),
                    "-MarketplaceRef",
                    "candidate-sha",
                    "-BridgeAttestationPath",
                    str(attestation),
                    "-Automated",
                ],
                cwd=temporary_root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=45,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertTrue(summary["automated"])
        self.assertTrue(summary["profile_restored"])
        self.assertTrue(summary["clean_profile_environment_restored"])
        self.assertEqual(
            summary["tools"],
            {
                "gmail": [
                    "gmail_list_threads",
                    "gmail_read",
                    "gmail_read_thread_page",
                    "gmail_search",
                    "gmail_send",
                ],
                "CaseToMD": ["get_case_markdown"],
            },
        )
        self.assertEqual(summary["runtime"]["version"], "1.10.1")
        self.assertTrue(summary["runtime"]["real_handshake"])
        self.assertTrue(summary["marketplace"]["installed"])
        self.assertTrue(summary["plugin"]["enabled"])


if __name__ == "__main__":
    unittest.main()
