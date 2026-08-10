import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
CODEX_MANIFEST = ROOT / ".codex-plugin/plugin.json"
ANTIGRAVITY_MANIFEST = ROOT / "plugins/avaya-case-review/plugin.json"
MARKETPLACE = ROOT / ".agents/plugins/marketplace.json"
MCP_MANIFEST = ROOT / ".mcp.json"
INSTALLER = ROOT / "install-codex.ps1"
INSTALL_CONTRACT = ROOT / "INSTALL.md"
RELEASE_MANIFEST = ROOT / "release-manifest.txt"
README_MD = ROOT / "README.md"
README_HTML = ROOT / "README.html"
MANAGER_MD = ROOT / "docs/MANAGER_ONBOARDING_GUIDE.md"
MANAGER_HTML = ROOT / "docs/MANAGER_ONBOARDING_GUIDE.html"
TDD_MD = ROOT / "docs/TECHNICAL_DESIGN_DOCUMENT.md"
TDD_HTML = ROOT / "docs/TECHNICAL_DESIGN_DOCUMENT.html"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class CodexPluginPackagingTests(unittest.TestCase):
    def test_codex_manifest_matches_shared_plugin_contract(self):
        codex = load_json(CODEX_MANIFEST)
        antigravity = load_json(ANTIGRAVITY_MANIFEST)

        self.assertEqual("avaya-case-review", codex["name"])
        self.assertEqual(antigravity["name"], codex["name"])
        self.assertEqual(antigravity["version"], codex["version"])
        self.assertEqual("./skills/", codex["skills"])
        self.assertEqual("./.mcp.json", codex["mcpServers"])

        interface = codex["interface"]
        for field in (
            "displayName",
            "shortDescription",
            "longDescription",
            "developerName",
            "category",
            "websiteURL",
        ):
            self.assertTrue(interface[field])
        self.assertLessEqual(len(interface["defaultPrompt"]), 3)
        self.assertTrue(all(len(prompt) <= 128 for prompt in interface["defaultPrompt"]))

    def test_marketplace_installs_the_repository_root_plugin(self):
        marketplace = load_json(MARKETPLACE)
        self.assertEqual("avaya-case-review-pack", marketplace["name"])
        self.assertEqual(1, len(marketplace["plugins"]))

        entry = marketplace["plugins"][0]
        self.assertEqual("avaya-case-review", entry["name"])
        self.assertEqual({"source": "local", "path": "./"}, entry["source"])
        self.assertEqual("AVAILABLE", entry["policy"]["installation"])
        self.assertEqual("ON_INSTALL", entry["policy"]["authentication"])
        self.assertEqual("Productivity", entry["category"])

    def test_bundled_mcp_paths_resolve_inside_plugin_root(self):
        servers = load_json(MCP_MANIFEST)["mcpServers"]
        self.assertSetEqual({"gmail", "CaseToMD"}, set(servers))

        for name, server in servers.items():
            with self.subTest(server=name):
                self.assertEqual("python", server["command"])
                self.assertEqual(1, len(server["args"]))
                argument = server["args"][0]
                self.assertTrue(argument.startswith("${CLAUDE_PLUGIN_ROOT}/"))
                relative = argument.removeprefix("${CLAUDE_PLUGIN_ROOT}/")
                self.assertTrue((ROOT / relative).is_file())
                self.assertEqual("utf-8", server["env"]["PYTHONIOENCODING"])

        self.assertEqual("edge_broker", servers["gmail"]["env"]["GMAIL_BACKEND"])

    def test_codex_skills_route_to_the_canonical_shared_workflows(self):
        routes = {
            "skills/case-review/SKILL.md": (
                "plugins/avaya-case-review/skills/case-review/SKILL.md"
            ),
            "skills/gmail-capability/SKILL.md": (
                "plugins/avaya-case-review/skills/gmail-capability/SKILL.md"
            ),
        }
        for entrypoint, canonical in routes.items():
            with self.subTest(skill=entrypoint):
                text = (ROOT / entrypoint).read_text(encoding="utf-8")
                self.assertTrue((ROOT / canonical).is_file())
                self.assertIn("../../" + canonical, text)

    def test_installer_is_windows_safe_and_cloud_gated(self):
        raw = INSTALLER.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "PowerShell file needs UTF-8 BOM")
        self.assertIsNone(re.search(rb"(?<!\r)\n", raw), "PowerShell file needs CRLF")

        source = raw.decode("utf-8-sig")
        for marker in (
            "$CloudBridgeVerified",
            "docs/GMAIL_CLOUD_BRIDGE.md",
            '"plugin", "marketplace", "add"',
            '"plugin", "add"',
            "codex plugin marketplace list --json",
            "gmail_brokerctl.py",
        ):
            self.assertIn(marker, source)

        powershell = shutil.which("powershell")
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")
        blocked = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(INSTALLER),
                "-SkipDependencyInstall",
                "-SkipLogin",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertNotEqual(0, blocked.returncode)
        self.assertIn("Cloud bridge verification is required", blocked.stderr)

        dry_run = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(INSTALLER),
                "-DryRun",
                "-SkipDependencyInstall",
                "-SkipLogin",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(0, dry_run.returncode, dry_run.stderr)
        self.assertIn(
            "codex plugin marketplace add https://github.com/avayahmao/avaya-case-review-pack --ref main",
            dry_run.stdout,
        )
        self.assertIn(
            "codex plugin add avaya-case-review@avaya-case-review-pack",
            dry_run.stdout,
        )
        self.assertIn("no state changes were made", dry_run.stdout)

    def test_agent_contract_has_both_supported_install_modes(self):
        contract = INSTALL_CONTRACT.read_text(encoding="utf-8")
        for marker in (
            "install this plugin: https://github.com/avayahmao/avaya-case-review-pack",
            "install-codex.ps1 -CloudBridgeVerified",
            "codex plugin marketplace add https://github.com/avayahmao/avaya-case-review-pack --ref main",
            "codex plugin add avaya-case-review@avaya-case-review-pack",
            ".\\install.bat",
            "Claude Code is not an installation target",
        ):
            self.assertIn(marker, contract)

        for path in (README_MD, README_HTML, AGENTS):
            with self.subTest(document=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn(
                    "install this plugin: https://github.com/avayahmao/avaya-case-review-pack",
                    content,
                )
                self.assertIn("install-codex.ps1", content)
                self.assertIn("install.bat", content)

        self.assertLess(
            contract.index("Mandatory cloud gate"),
            contract.index("Codex installation"),
        )
        self.assertLess(
            contract.index("Mandatory cloud gate"),
            contract.index("Antigravity installation"),
        )

        for path in (MANAGER_MD, MANAGER_HTML, TDD_MD, TDD_HTML):
            with self.subTest(dual_host_document=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn("install-codex.ps1", content)
                self.assertIn("install.bat", content)
                self.assertLess(
                    content.index("Cloud deployment and verification"),
                    content.index("install-codex.ps1"),
                )

    def test_codex_files_are_in_the_release_manifest(self):
        entries = {
            line.strip()
            for line in RELEASE_MANIFEST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
        required = {
            ".agents/plugins/marketplace.json",
            ".codex-plugin/plugin.json",
            ".mcp.json",
            "INSTALL.md",
            "install-codex.ps1",
            "skills/case-review/SKILL.md",
            "skills/gmail-capability/SKILL.md",
        }
        self.assertFalse(required - entries, f"missing Codex files: {sorted(required - entries)}")
        self.assertFalse((ROOT / ".claude-plugin").exists())


if __name__ == "__main__":
    unittest.main()
