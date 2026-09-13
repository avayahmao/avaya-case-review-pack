import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.gmail.cloud.bridge_identity import write_attestation


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
URL_INSTALL_DOCS = (
    README_MD,
    README_HTML,
    AGENTS,
    INSTALL_CONTRACT,
    MANAGER_MD,
    MANAGER_HTML,
    TDD_MD,
    TDD_HTML,
)


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

    def test_bundled_mcp_servers_launch_installed_runtime_modules(self):
        servers = load_json(MCP_MANIFEST)["mcpServers"]
        self.assertSetEqual({"gmail", "CaseToMD"}, set(servers))

        expected_args = {
            "gmail": ["-m", "avaya_case_review_runtime.gmail_mcp_server"],
            "CaseToMD": ["-m", "avaya_case_review_runtime.casetomd_mcp_bridge"],
        }

        for name, server in servers.items():
            with self.subTest(server=name):
                self.assertEqual("python", server["command"])
                self.assertEqual(expected_args[name], server["args"])
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

    def test_installer_is_windows_safe_and_validates_release_locally_in_dry_run(self):
        raw = INSTALLER.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "PowerShell file needs UTF-8 BOM")
        self.assertIsNone(re.search(rb"(?<!\r)\n", raw), "PowerShell file needs CRLF")

        source = raw.decode("utf-8-sig")
        for marker in (
            "$CloudBridgeVerified",
            "Get-CodexMarketplaceSnapshot",
            "Set-CodexMarketplaceAtRef",
            "Restore-CodexMarketplaceSnapshot",
            "gmail_brokerctl.py",
            "bridge_release_attestation.json",
            "runtime_package.py",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("Remove-Item", source)

        powershell = shutil.which("powershell")
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            for relative in (
                ".codex-plugin/plugin.json",
                ".agents/plugins/marketplace.json",
                ".mcp.json",
                "pyproject.toml",
                "tools/gmail/gmail_brokerctl.py",
                "tools/gmail/cloud/GmailMcpBridge.gs",
                "tools/gmail/cloud/bridge_identity.py",
                "tools/installer/runtime_package.py",
                "tools/installer/windows_common.ps1",
            ):
                destination = fixture / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            shutil.copy2(INSTALLER, fixture / INSTALLER.name)
            write_attestation(
                fixture / "tools/gmail/cloud/GmailMcpBridge.gs",
                fixture / "tools/gmail/cloud/bridge_release_attestation.json",
                "1.10.1",
                "2026-09-09T00:00:00Z",
            )
            dry_run = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(fixture / INSTALLER.name),
                    "-DryRun",
                ],
                cwd=fixture,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
                check=False,
            )
        self.assertEqual(0, dry_run.returncode, dry_run.stderr)
        self.assertIn("Ref:         v1.10.1", dry_run.stdout)
        self.assertIn("Planned stage: new marketplace add", dry_run.stdout)
        self.assertIn("Planned stage: new plugin add", dry_run.stdout)
        self.assertIn("no state changes were made", dry_run.stdout)

    def test_github_bootstrap_is_first_and_rejects_skill_installer(self):
        readme = README_MD.read_text(encoding="utf-8")
        bootstrap = readme.index("AI Agent Installation")
        overview = readme.index("Overview")
        self.assertLess(bootstrap, overview)
        self.assertIn("Codex plugin marketplace, not a standalone skill", readme)
        self.assertIn("git clone --depth 1 --branch v1.10.1", readme)
        self.assertNotIn("install-codex.ps1 -CloudBridgeVerified", readme)

        for path in (README_MD, README_HTML, AGENTS, INSTALL_CONTRACT, MANAGER_MD, MANAGER_HTML):
            with self.subTest(document=path.name):
                content = path.read_text(encoding="utf-8-sig")
                self.assertIn(
                    "install this plugin: https://github.com/avayahmao/avaya-case-review-pack",
                    content,
                )
                self.assertNotIn("Use a skill-only install for the full product", content)

        self.assertFalse((ROOT / "SKILL.md").exists())

    def test_docs_share_stable_tag_and_no_end_user_cloud_deployment(self):
        for path in URL_INSTALL_DOCS:
            with self.subTest(document=path.name):
                text = path.read_text(encoding="utf-8-sig")
                self.assertIn("v1.10.1", text)
                self.assertIn("install-codex.ps1", text)
                self.assertNotIn("Before either local installation, deploy", text)

    def test_readme_has_a_github_mermaid_workflow_and_html_equivalent(self):
        markdown = README_MD.read_text(encoding="utf-8")
        html = README_HTML.read_text(encoding="utf-8")

        for marker in (
            "## How does it work",
            "```mermaid",
            "flowchart TD",
            'Gate{"Complete Context gate passed?"}',
            "Context collection incomplete",
            "Evidence Register",
        ):
            self.assertIn(marker, markdown)
        self.assertLess(
            markdown.index("## How does it work"),
            markdown.index("## Evidence-Grounded Review Contract"),
        )

        for marker in (
            "<h2>How does it work</h2>",
            'class="workflow-flow"',
            "Complete Context gate passed?",
            "Context collection incomplete",
            "Evidence Register",
        ):
            self.assertIn(marker, html)
        self.assertLess(
            html.index("<h2>How does it work</h2>"),
            html.index("<h2>Evidence-Grounded Review Contract</h2>"),
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
