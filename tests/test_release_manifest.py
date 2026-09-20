import json
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

INSTALLER_ENTRY_POINTS = frozenset(
    {"install.bat", "install-codex.ps1", "setup_env.ps1"}
)

REQUIRED_RELEASE_PATHS = INSTALLER_ENTRY_POINTS | frozenset(
    {
        "pyproject.toml",
        "release-manifest.txt",
        ".agents/plugins/marketplace.json",
        ".codex-plugin/plugin.json",
        ".mcp.json",
        "INSTALL.md",
        "docs/CODEX_PLUGIN_RELEASE_CHECKLIST.md",
        "docs/GMAIL_CLOUD_BRIDGE.md",
        "docs/GMAIL_EDGE_BROKER.md",
        "tools/casetomd/casetomd_mcp_bridge.py",
        "tools/installer/runtime_package.py",
        "plugins/avaya-case-review/plugin.json",
        "plugins/avaya-case-review/skills/case-review/SKILL.md",
        "plugins/avaya-case-review/skills/gmail-capability/SKILL.md",
        "skills/case-review/SKILL.md",
        "skills/gmail-capability/SKILL.md",
    }
)

RUNTIME_PACKAGE_FILES = frozenset(
    {
        "__init__.py",
        "bridge_identity.py",
        "casetomd_mcp_bridge.py",
        "gmail_broker_client.py",
        "gmail_broker_protocol.py",
        "gmail_broker_state.py",
        "gmail_brokerctl.py",
        "gmail_edge_broker.py",
        "gmail_edge_common.py",
        "gmail_legacy_backend.py",
        "gmail_mcp_server.py",
    }
)

CLOUD_GMAIL_BRIDGE = "tools/gmail/cloud/GmailMcpBridge.gs"
CLOUD_BRIDGE_IDENTITY = "tools/gmail/cloud/bridge_identity.py"
CLOUD_BRIDGE_ATTESTATION = "tools/gmail/cloud/bridge_release_attestation.json"
CLOUD_RELEASE_FILES = frozenset(
    {CLOUD_GMAIL_BRIDGE, CLOUD_BRIDGE_IDENTITY, CLOUD_BRIDGE_ATTESTATION}
)
PROHIBITED_ATTESTATION_FIELDS = frozenset(
    {
        "identity",
        "deployment",
        "deployment_id",
        "deployment_url",
        "case",
        "case_id",
        "thread",
        "thread_id",
        "message",
        "message_id",
        "message_hash",
        "token",
        "page_token",
        "cursor",
        "body",
        "message_body",
        "body_hash",
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

    def test_windows_entry_points_preserve_utf8_bom_and_crlf(self):
        windows_scripts = [
            ROOT / name
            for name in manifest_entries()
            if PurePosixPath(name).suffix.lower() in {".ps1", ".bat", ".cmd"}
        ]
        self.assertTrue(windows_scripts, "release has no Windows entry points")

        for path in windows_scripts:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "missing UTF-8 BOM")
                self.assertIsNone(
                    re.search(rb"(?<!\r)\n", raw),
                    "Windows entry point contains LF-only line endings",
                )

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
            INSTALLER_ENTRY_POINTS - entries,
            f"missing installer entry points: {sorted(INSTALLER_ENTRY_POINTS - entries)}",
        )
        self.assertFalse(
            REQUIRED_RELEASE_PATHS - entries,
            f"missing required release paths: {sorted(REQUIRED_RELEASE_PATHS - entries)}",
        )
        required_runtime_paths = {
            f"avaya_case_review_runtime/{name}" for name in RUNTIME_PACKAGE_FILES
        }
        self.assertFalse(
            required_runtime_paths - entries,
            f"missing packaged runtime files: {sorted(required_runtime_paths - entries)}",
        )
        self.assertFalse(
            any(name.startswith("tools/codex/") for name in entries),
            "release must not contain a Codex cache materializer",
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

        scripts_root = (
            ROOT / "plugins/avaya-case-review/skills/case-review/scripts"
        )
        required_scripts = {
            path.relative_to(ROOT).as_posix() for path in scripts_root.glob("*.py")
        }
        self.assertTrue(required_scripts, "case-review scripts are missing")
        self.assertFalse(
            required_scripts - entries,
            f"case-review scripts missing from the release manifest: "
            f"{sorted(required_scripts - entries)}",
        )

    def test_cloud_bridge_is_distributed_but_not_deployed_as_a_local_script(self):
        entries = set(manifest_entries())
        installer_files = set(installer_gmail_deployment_files())

        self.assertFalse(
            CLOUD_RELEASE_FILES - entries,
            f"missing cloud release files: {sorted(CLOUD_RELEASE_FILES - entries)}",
        )
        self.assertNotIn("GmailMcpBridge.gs", installer_files)

    def test_extracted_cloud_attestation_is_valid_and_contains_no_sensitive_fields(self):
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

            for name in CLOUD_RELEASE_FILES:
                self.assertTrue((extracted / name).is_file(), name)

            validator_command = [
                sys.executable,
                str(extracted / CLOUD_BRIDGE_IDENTITY),
                "validate",
                "--source",
                str(extracted / CLOUD_GMAIL_BRIDGE),
                "--attestation",
                str(extracted / CLOUD_BRIDGE_ATTESTATION),
                "--plugin-version",
                "1.11.0",
            ]
            validation = subprocess.run(
                validator_command,
                cwd=extracted,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)

            attestation_path = extracted / CLOUD_BRIDGE_ATTESTATION
            attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
            for field in PROHIBITED_ATTESTATION_FIELDS:
                with self.subTest(prohibited_field=field):
                    prohibited = dict(attestation)
                    prohibited[field] = "PROHIBITED"
                    attestation_path.write_text(
                        json.dumps(prohibited), encoding="utf-8"
                    )
                    rejected = subprocess.run(
                        validator_command,
                        cwd=extracted,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        timeout=20,
                        check=False,
                    )
                    self.assertNotEqual(rejected.returncode, 0)

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

            runtime_helper = extracted / "tools/installer/runtime_package.py"
            self.assertTrue(runtime_helper.is_file())
            self.assertTrue((extracted / "pyproject.toml").is_file())
            for name in RUNTIME_PACKAGE_FILES:
                self.assertTrue((extracted / "avaya_case_review_runtime" / name).is_file())
            helper_result = subprocess.run(
                [sys.executable, str(runtime_helper), "installed-version"],
                cwd=temp_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
                check=False,
            )
            self.assertEqual(helper_result.returncode, 0, helper_result.stderr)
            self.assertEqual(
                json.loads(helper_result.stdout)["distribution"],
                "avaya-case-review-runtime",
            )

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
