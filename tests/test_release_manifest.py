import os
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release-manifest.txt"


def manifest_entries():
    return [
        line.strip()
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_is_explicit_and_contains_all_broker_runtime_files(self):
        entries = manifest_entries()
        self.assertEqual(len(entries), len(set(entries)))
        self.assertIn("release-manifest.txt", entries)
        self.assertIn("docs/GMAIL_EDGE_BROKER.md", entries)
        for name in (
            "tools/gmail/gmail_broker_client.py",
            "tools/gmail/gmail_broker_protocol.py",
            "tools/gmail/gmail_broker_state.py",
            "tools/gmail/gmail_brokerctl.py",
            "tools/gmail/gmail_edge_broker.py",
            "tools/gmail/gmail_edge_common.py",
            "tools/gmail/gmail_legacy_backend.py",
            "tools/gmail/gmail_mcp_server.py",
        ):
            self.assertIn(name, entries)
        self.assertTrue(all("*" not in name and not name.endswith(".zip") for name in entries))
        self.assertTrue(all((ROOT / name).is_file() for name in entries))

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
