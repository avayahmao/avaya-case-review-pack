import json
import os
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "avaya_case_review_runtime"
RUNTIME_HELPER = ROOT / "tools" / "installer" / "runtime_package.py"
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
        self.assertIn('version = "1.10.1"', pyproject)
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


class RuntimePackageInstallerHelperTests(unittest.TestCase):
    def run_helper(self, *arguments, environment=None):
        return subprocess.run(
            [sys.executable, str(RUNTIME_HELPER), *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )

    @staticmethod
    def write_wheel(path, *, name="avaya-case-review-runtime", version="1.10.1", members=()):
        distribution = name.replace("-", "_")
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        with zipfile.ZipFile(path, "w") as wheel:
            wheel.writestr(f"{distribution}-{version}.dist-info/METADATA", metadata)
            for member in members:
                wheel.writestr(member, "# fixture\n")

    def test_installed_version_reports_explicit_absence(self):
        with TemporaryDirectory() as temporary:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = temporary
            completed = self.run_helper("installed-version", environment=environment)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout),
            {"distribution": "avaya-case-review-runtime", "installed": False},
        )

    def test_validate_wheel_accepts_exact_runtime_and_rejects_contract_violations(self):
        required = {
            "avaya_case_review_runtime/gmail_mcp_server.py",
            "avaya_case_review_runtime/casetomd_mcp_bridge.py",
        }
        cases = (
            ("valid", "avaya-case-review-runtime", "1.10.1", required, True),
            ("wrong-name", "different-runtime", "1.10.1", required, False),
            ("wrong-version", "avaya-case-review-runtime", "9.9.9", required, False),
            (
                "missing-module",
                "avaya-case-review-runtime",
                "1.10.1",
                {"avaya_case_review_runtime/gmail_mcp_server.py"},
                False,
            ),
            (
                "repository-tools",
                "avaya-case-review-runtime",
                "1.10.1",
                required | {"tools/gmail/gmail_mcp_server.py"},
                False,
            ),
        )
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for label, name, version, members, accepted in cases:
                with self.subTest(label=label):
                    wheel = directory / f"{label}.whl"
                    self.write_wheel(wheel, name=name, version=version, members=members)
                    completed = self.run_helper(
                        "validate-wheel", "--wheel", str(wheel), "--version", "1.10.1"
                    )
                    self.assertEqual(completed.returncode == 0, accepted, completed.stderr)
                    combined = completed.stdout + completed.stderr
                    self.assertNotIn("tools/gmail/gmail_mcp_server.py", combined)

    def test_validate_wheel_rejects_noncanonical_and_aliased_member_paths(self):
        required = {
            "avaya_case_review_runtime/gmail_mcp_server.py",
            "avaya_case_review_runtime/casetomd_mcp_bridge.py",
        }
        unsafe = (
            "/avaya_case_review_runtime/extra.py",
            "C:/avaya_case_review_runtime/extra.py",
            "//server/share/extra.py",
            "avaya_case_review_runtime//extra.py",
            "avaya_case_review_runtime/./extra.py",
            "avaya_case_review_runtime/../extra.py",
            "TOOLS/extra.py",
            "ＴＯＯＬＳ/extra.py",
            "tools./extra.py",
            "TOOLS／extra.py",
            "avaya_case_review_runtime/gmail_mcp_server.py.",
            "avaya_case_review_runtime/gmail_mcp_server.py ",
            "CON/extra.py",
            "package/NUL.txt",
        )
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for index, member in enumerate(unsafe):
                with self.subTest(member=member):
                    wheel = directory / f"unsafe-{index}.whl"
                    self.write_wheel(wheel, members=required | {member})
                    completed = self.run_helper(
                        "validate-wheel", "--wheel", str(wheel), "--version", "1.10.1"
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    combined = completed.stdout + completed.stderr
                    self.assertNotIn(member, combined)
                    self.assertNotIn(str(wheel), combined)
                    self.assertNotIn("Traceback", combined)

            backslash_wheel = directory / "unsafe-backslash.whl"
            placeholder = "avaya_case_review_runtime!extra.py"
            self.write_wheel(backslash_wheel, members=required | {placeholder})
            raw = backslash_wheel.read_bytes().replace(
                placeholder.encode("ascii"),
                rb"avaya_case_review_runtime\extra.py",
            )
            backslash_wheel.write_bytes(raw)
            completed = self.run_helper(
                "validate-wheel",
                "--wheel",
                str(backslash_wheel),
                "--version",
                "1.10.1",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stdout + completed.stderr)

    def test_validate_wheel_rejects_casefolded_member_aliases(self):
        required = {
            "avaya_case_review_runtime/gmail_mcp_server.py",
            "avaya_case_review_runtime/casetomd_mcp_bridge.py",
        }
        with TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "case-alias.whl"
            self.write_wheel(
                wheel,
                members=required
                | {"AVAYA_CASE_REVIEW_RUNTIME/GMAIL_MCP_SERVER.PY"},
            )
            completed = self.run_helper(
                "validate-wheel", "--wheel", str(wheel), "--version", "1.10.1"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)

    def test_cli_sanitizes_malformed_encrypted_and_invalid_utf8_wheels(self):
        required = {
            "avaya_case_review_runtime/gmail_mcp_server.py",
            "avaya_case_review_runtime/casetomd_mcp_bridge.py",
        }
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            malformed = directory / "SENTINEL_MALFORMED.whl"
            malformed.write_bytes(b"SENTINEL_ARCHIVE_BYTES")

            encrypted = directory / "SENTINEL_ENCRYPTED.whl"
            self.write_wheel(encrypted, members=required)
            encrypted_bytes = bytearray(encrypted.read_bytes())
            for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
                position = 0
                while True:
                    position = encrypted_bytes.find(signature, position)
                    if position < 0:
                        break
                    current = int.from_bytes(
                        encrypted_bytes[position + flag_offset : position + flag_offset + 2],
                        "little",
                    )
                    encrypted_bytes[position + flag_offset : position + flag_offset + 2] = (
                        current | 1
                    ).to_bytes(2, "little")
                    position += 4
            encrypted.write_bytes(encrypted_bytes)

            invalid_utf8 = directory / "SENTINEL_UTF8.whl"
            distribution = "avaya_case_review_runtime-1.10.1.dist-info/METADATA"
            with zipfile.ZipFile(invalid_utf8, "w") as wheel:
                wheel.writestr(distribution, b"Name: avaya-case-review-runtime\nVersion: \xffSENTINEL\n")
                for member in required:
                    wheel.writestr(member, "# fixture\n")

            for wheel in (malformed, encrypted, invalid_utf8):
                with self.subTest(wheel=wheel.name):
                    completed = self.run_helper(
                        "validate-wheel", "--wheel", str(wheel), "--version", "1.10.1"
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    combined = completed.stdout + completed.stderr
                    self.assertNotIn("SENTINEL", combined)
                    self.assertNotIn(str(wheel), combined)
                    self.assertNotIn("Traceback", combined)
                    self.assertEqual(
                        set(json.loads(completed.stderr)), {"error", "ok"}
                    )

    def test_smoke_cli_sanitizes_invalid_json_and_invalid_utf8_child_output(self):
        variants = {
            "invalid-json": 'print("SENTINEL_RESPONSE not-json", flush=True)',
            "invalid-utf8": (
                'import sys; sys.stdout.buffer.write(b"\\xffSENTINEL_CHILD_BYTES"); '
                "sys.stdout.buffer.flush()"
            ),
        }
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            outside = directory / "outside"
            outside.mkdir()
            for label, body in variants.items():
                with self.subTest(label=label):
                    site = directory / label / "avaya_case_review_runtime"
                    site.mkdir(parents=True)
                    (site / "__init__.py").write_text("", encoding="utf-8")
                    for module in ("gmail_mcp_server", "casetomd_mcp_bridge"):
                        (site / f"{module}.py").write_text(body, encoding="utf-8")
                    environment = os.environ.copy()
                    environment["PYTHONPATH"] = str(site.parent)
                    completed = self.run_helper(
                        "smoke",
                        "--python",
                        sys.executable,
                        "--work-dir",
                        str(outside),
                        environment=environment,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    combined = completed.stdout + completed.stderr
                    self.assertNotIn("SENTINEL", combined)
                    self.assertNotIn("Traceback", combined)
                    self.assertEqual(set(json.loads(completed.stderr)), {"error", "ok"})

    def test_smoke_verifies_both_exact_mcp_tool_sets_from_unrelated_cwd(self):
        fake_module = '''\
import json
import sys

module = "MODULE_NAME"
tools = {
    "gmail_mcp_server": [
        "gmail_search", "gmail_read", "gmail_send",
        "gmail_list_threads", "gmail_read_thread_page",
    ],
    "casetomd_mcp_bridge": ["get_case_markdown"],
}[module]
for line in sys.stdin:
    request = json.loads(line)
    if request.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": module, "version": "1"}}}), flush=True)
    elif request.get("method") == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {"tools": [{"name": name} for name in tools]}}), flush=True)
        break
'''
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            package = directory / "site" / "avaya_case_review_runtime"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            for module in ("gmail_mcp_server", "casetomd_mcp_bridge"):
                (package / f"{module}.py").write_text(
                    fake_module.replace("MODULE_NAME", module), encoding="utf-8"
                )
            outside = directory / "outside"
            outside.mkdir()
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(directory / "site")

            completed = self.run_helper(
                "smoke",
                "--python",
                sys.executable,
                "--work-dir",
                str(outside),
                environment=environment,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"smoke": "ok"})


if __name__ == "__main__":
    unittest.main()
