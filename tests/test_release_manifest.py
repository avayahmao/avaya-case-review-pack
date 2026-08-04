import os
import re
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release-manifest.txt"
SETUP_ENV = ROOT / "setup_env.ps1"

EXPECTED_GMAIL_DEPLOYMENT_FILES = frozenset(
    {
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
)

REQUIRED_RELEASE_PATHS = frozenset(
    {
        "release-manifest.txt",
        "docs/GMAIL_EDGE_BROKER.md",
        "tools/casetomd/casetomd_mcp_bridge.py",
        "plugins/avaya-case-review/plugin.json",
        "plugins/avaya-case-review/skills/case-review/SKILL.md",
        "plugins/avaya-case-review/skills/gmail-capability/SKILL.md",
    }
)


def manifest_entries():
    return [
        line.strip()
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def installer_gmail_deployment_files():
    setup = SETUP_ENV.read_text(encoding="utf-8-sig")
    match = re.search(
        r"^\s*\$GmailDeploymentFiles\s*=\s*@\((?P<body>.*?)^\s*\)",
        setup,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError("setup_env.ps1 does not define $GmailDeploymentFiles")
    return re.findall(
        r'^\s*"([^"]+)"\s*,?\s*$',
        match.group("body"),
        flags=re.MULTILINE,
    )


class ReleaseManifestTests(unittest.TestCase):
    # Regression hardening: the manifest already met this contract when these
    # assertions were added. Removing an installer file or adding a runtime
    # profile/state artifact must make the corresponding assertion fail.
    def test_manifest_entries_are_unique_safe_relative_files(self):
        entries = manifest_entries()
        self.assertEqual(len(entries), len(set(entries)), "manifest contains duplicates")

        for name in entries:
            with self.subTest(name=name):
                posix_path = PurePosixPath(name)
                windows_path = PureWindowsPath(name)
                self.assertFalse(posix_path.is_absolute())
                self.assertFalse(windows_path.is_absolute())
                self.assertFalse(windows_path.drive)
                self.assertNotIn("..", posix_path.parts)
                self.assertNotIn("\\", name)
                self.assertNotIn("*", name)
                self.assertEqual(posix_path.as_posix(), name)
                self.assertTrue((ROOT / name).is_file())

    def test_manifest_contains_installer_runtime_and_plugin_content(self):
        entries = set(manifest_entries())
        installer_files = installer_gmail_deployment_files()

        self.assertEqual(len(installer_files), len(set(installer_files)))
        self.assertSetEqual(set(installer_files), set(EXPECTED_GMAIL_DEPLOYMENT_FILES))

        required_gmail_paths = {
            f"tools/gmail/{name}" for name in EXPECTED_GMAIL_DEPLOYMENT_FILES
        }
        self.assertFalse(
            required_gmail_paths - entries,
            f"missing Gmail deployment files: {sorted(required_gmail_paths - entries)}",
        )
        self.assertFalse(
            REQUIRED_RELEASE_PATHS - entries,
            f"missing required release paths: {sorted(REQUIRED_RELEASE_PATHS - entries)}",
        )

        reference_root = (
            ROOT / "plugins/avaya-case-review/skills/case-review/references"
        )
        required_references = {
            path.relative_to(ROOT).as_posix() for path in reference_root.glob("*.md")
        }
        self.assertTrue(required_references, "case-review references are missing")
        self.assertFalse(
            required_references - entries,
            f"missing case-review references: {sorted(required_references - entries)}",
        )

    def test_manifest_excludes_runtime_profiles_state_and_optional_examples(self):
        entries = manifest_entries()
        self.assertNotIn("examples/optional-appsscript/Code.gs", entries)

        for name in entries:
            with self.subTest(name=name):
                path = PurePosixPath(name)
                lower_parts = {part.lower() for part in path.parts}
                lower_name = path.name.lower()

                self.assertTrue(
                    {"chrome_profile", "edge_broker_profile"}.isdisjoint(lower_parts)
                )
                self.assertNotEqual(path.suffix.lower(), ".zip")
                self.assertFalse(lower_name.endswith(".log"))
                self.assertNotIn(
                    lower_name, {"state.json", "broker-state.json", "broker_state.json"}
                )
                self.assertIsNone(
                    re.search(
                        r"(?:^|[-_.])(?:token|cookies?|credentials?)(?:[-_.]|$)",
                        lower_name,
                    )
                )

    def test_clean_extracted_manifest_imports_and_control_help(self):
        entries = manifest_entries()
        with TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            archive = temp_root / "release.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for name in entries:
                    bundle.write(ROOT / name, name)
            extracted = temp_root / "extracted"
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extracted)

            env = os.environ.copy()
            env.pop("GMAIL_BACKEND", None)
            import_code = (
                "import sys; "
                "import tools.gmail.gmail_broker_client; "
                "import tools.gmail.gmail_broker_protocol; "
                "import tools.gmail.gmail_broker_state; "
                "import tools.gmail.gmail_mcp_server; "
                "assert not any(name.startswith('playwright') for name in sys.modules); "
                "import tools.gmail.gmail_edge_broker"
            )
            imported = subprocess.run(
                [sys.executable, "-c", import_code],
                cwd=extracted,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
                check=False,
            )
            self.assertEqual(imported.returncode, 0, imported.stderr)

            for script in ("tools/gmail/gmail_brokerctl.py", "tools/gmail/gmail_edge_broker.py"):
                completed = subprocess.run(
                    [sys.executable, str(extracted / script), "--help"],
                    cwd=extracted,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=20,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("help", completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
