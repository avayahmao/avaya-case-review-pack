import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "avaya_case_review_runtime"
CANONICAL_MODULES = (
    "bridge_identity",
    "casetomd_mcp_bridge",
    "gmail_broker_client",
    "gmail_broker_protocol",
    "gmail_broker_state",
    "gmail_brokerctl",
    "gmail_edge_broker",
    "gmail_edge_common",
    "gmail_legacy_backend",
    "gmail_mcp_server",
)
COMPATIBILITY_MODULES = {
    "tools.gmail.cloud.bridge_identity": "bridge_identity",
    "tools.casetomd.casetomd_mcp_bridge": "casetomd_mcp_bridge",
    "tools.gmail.gmail_broker_client": "gmail_broker_client",
    "tools.gmail.gmail_broker_protocol": "gmail_broker_protocol",
    "tools.gmail.gmail_broker_state": "gmail_broker_state",
    "tools.gmail.gmail_brokerctl": "gmail_brokerctl",
    "tools.gmail.gmail_edge_broker": "gmail_edge_broker",
    "tools.gmail.gmail_edge_common": "gmail_edge_common",
    "tools.gmail.gmail_legacy_backend": "gmail_legacy_backend",
    "tools.gmail.gmail_mcp_server": "gmail_mcp_server",
}


def install_runtime(target: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            str(target),
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stdout + completed.stderr)


def installed_environment(target: Path) -> dict[str, str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(target) if not existing else os.pathsep.join((str(target), existing))
    )
    return environment


def mcp_handshake_command(
    command: list[str], target: Path, cwd: Path
) -> list[dict]:
    messages = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "runtime-package-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    completed = subprocess.run(
        command,
        input="".join(json.dumps(message) + "\n" for message in messages),
        cwd=cwd,
        env=installed_environment(target),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def mcp_handshake(module: str, target: Path, cwd: Path) -> list[dict]:
    return mcp_handshake_command(
        [sys.executable, "-m", module],
        target,
        cwd,
    )


class RuntimePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = TemporaryDirectory()
        cls.temp_root = Path(cls.temporary.name)
        cls.target = cls.temp_root / "target"
        cls.outside = cls.temp_root / "outside"
        cls.outside.mkdir()
        install_runtime(cls.target)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_distribution_metadata_and_package_are_installable(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('name = "avaya-case-review-runtime"', pyproject)
        self.assertIn('version = "1.10.0"', pyproject)
        self.assertIn('requires-python = ">=3.10"', pyproject)
        self.assertIn('packages = ["avaya_case_review_runtime"]', pyproject)
        self.assertNotIn("dependencies", pyproject)
        self.assertTrue((self.target / "avaya_case_review_runtime").is_dir())
        self.assertFalse((self.target / "tools").exists())

    def test_module_entry_points_handshake_from_outside_source_tree(self):
        expected_tools = {
            "avaya_case_review_runtime.gmail_mcp_server": {
                "gmail_search",
                "gmail_read",
                "gmail_send",
                "gmail_list_threads",
                "gmail_read_thread_page",
            },
            "avaya_case_review_runtime.casetomd_mcp_bridge": {
                "get_case_markdown"
            },
        }
        for module, expected in expected_tools.items():
            with self.subTest(module=module):
                responses = mcp_handshake(module, self.target, self.outside)
                initialized = next(item for item in responses if item.get("id") == 1)
                listed = next(item for item in responses if item.get("id") == 2)
                self.assertIn("protocolVersion", initialized["result"])
                self.assertSetEqual(
                    expected,
                    {tool["name"] for tool in listed["result"]["tools"]},
                )

    def test_compatibility_imports_alias_canonical_module_objects(self):
        statements = []
        for compatibility, canonical in COMPATIBILITY_MODULES.items():
            statements.append(
                "import importlib; "
                f"assert importlib.import_module({compatibility!r}) is "
                f"importlib.import_module('avaya_case_review_runtime.{canonical}')"
            )
        environment = installed_environment(self.target)
        environment["PYTHONPATH"] = os.pathsep.join(
            (str(self.target), str(ROOT))
        )
        completed = subprocess.run(
            [sys.executable, "-c", "; ".join(statements)],
            cwd=self.outside,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_canonical_modules_do_not_import_repository_tools_package(self):
        for name in CANONICAL_MODULES:
            with self.subTest(module=name):
                source = (PACKAGE / f"{name}.py").read_text(encoding="utf-8")
                self.assertNotIn("tools.gmail", source)

    def test_compatibility_control_shims_run_from_outside_source_tree(self):
        scripts = (
            ROOT / "tools/gmail/gmail_brokerctl.py",
            ROOT / "tools/gmail/gmail_edge_broker.py",
        )
        for script in scripts:
            with self.subTest(script=script.name):
                completed = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    cwd=self.outside,
                    env=installed_environment(self.target),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=20,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("help", completed.stdout.lower())

    def test_compatibility_mcp_shims_handshake_from_outside_source_tree(self):
        expected_tools = {
            ROOT / "tools/gmail/gmail_mcp_server.py": {
                "gmail_search",
                "gmail_read",
                "gmail_send",
                "gmail_list_threads",
                "gmail_read_thread_page",
            },
            ROOT / "tools/casetomd/casetomd_mcp_bridge.py": {
                "get_case_markdown"
            },
        }
        for script, expected in expected_tools.items():
            with self.subTest(script=script.name):
                responses = mcp_handshake_command(
                    [sys.executable, str(script)],
                    self.target,
                    self.outside,
                )
                initialized = next(item for item in responses if item.get("id") == 1)
                listed = next(item for item in responses if item.get("id") == 2)
                self.assertIn("protocolVersion", initialized["result"])
                self.assertSetEqual(
                    expected,
                    {tool["name"] for tool in listed["result"]["tools"]},
                )

    def test_packaged_control_modules_run_from_outside_source_tree(self):
        modules = (
            "avaya_case_review_runtime.gmail_brokerctl",
            "avaya_case_review_runtime.gmail_edge_broker",
        )
        for module in modules:
            with self.subTest(module=module):
                completed = subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    cwd=self.outside,
                    env=installed_environment(self.target),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=20,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("help", completed.stdout.lower())

    def test_legacy_profile_is_stable_per_user_and_overridable(self):
        fake_home = self.temp_root / "user"
        override = self.temp_root / "override"
        code = (
            "import avaya_case_review_runtime.gmail_legacy_backend as legacy; "
            "print(legacy.PROFILE_DIR)"
        )
        environment = installed_environment(self.target)
        environment["USERPROFILE"] = str(fake_home)
        environment.pop("GMAIL_LEGACY_PROFILE_DIR", None)
        default = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.outside,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(
            Path(default.stdout.strip()),
            fake_home / ".gemini/tools/gmail/chrome_profile",
        )

        environment["GMAIL_LEGACY_PROFILE_DIR"] = str(override)
        overridden = subprocess.run(
            [sys.executable, "-c", code],
            cwd=self.outside,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertEqual(overridden.returncode, 0, overridden.stderr)
        self.assertEqual(Path(overridden.stdout.strip()), override)


if __name__ == "__main__":
    unittest.main()
