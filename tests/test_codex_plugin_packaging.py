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
GMAIL_CLOUD_BRIDGE_MD = ROOT / "docs/GMAIL_CLOUD_BRIDGE.md"
MANAGER_MD = ROOT / "docs/MANAGER_ONBOARDING_GUIDE.md"
MANAGER_HTML = ROOT / "docs/MANAGER_ONBOARDING_GUIDE.html"
TDD_MD = ROOT / "docs/TECHNICAL_DESIGN_DOCUMENT.md"
TDD_HTML = ROOT / "docs/TECHNICAL_DESIGN_DOCUMENT.html"
RELEASE_NOTES_MD = ROOT / "docs/RELEASE_NOTES.md"
RELEASE_NOTES_HTML = ROOT / "docs/RELEASE_NOTES.html"
RELEASE_CHECKLIST = ROOT / "docs/CODEX_PLUGIN_RELEASE_CHECKLIST.md"
IMPLEMENTATION_PLAN = (
    ROOT / "docs/superpowers/plans/2026-09-09-codex-url-install-repair.md"
)
URL_INSTALL_DOCS = (
    README_MD,
    README_HTML,
    AGENTS,
    INSTALL_CONTRACT,
    GMAIL_CLOUD_BRIDGE_MD,
    MANAGER_MD,
    MANAGER_HTML,
    TDD_MD,
    TDD_HTML,
    RELEASE_NOTES_MD,
    RELEASE_NOTES_HTML,
)
DEPENDENCY_CONTRACT_DOCS = (
    README_MD,
    README_HTML,
    MANAGER_MD,
    MANAGER_HTML,
    TDD_MD,
    TDD_HTML,
    RELEASE_NOTES_MD,
    RELEASE_NOTES_HTML,
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
                "avaya_case_review_runtime/__init__.py",
                "avaya_case_review_runtime/bridge_identity.py",
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
        self.assertIn("mcp==1.28.1", dry_run.stdout)
        self.assertIn("Planned stage: new marketplace add", dry_run.stdout)
        self.assertIn("Planned stage: new plugin add", dry_run.stdout)
        self.assertIn("no state changes were made", dry_run.stdout)

    def test_github_bootstrap_is_first_and_uses_stable_plugin_release(self):
        readme = README_MD.read_text(encoding="utf-8")
        bootstrap = readme.index("AI Agent Installation")
        overview = readme.index("Overview")
        self.assertLess(bootstrap, overview)
        self.assertIn("Codex plugin marketplace, not a standalone skill", readme)
        self.assertIn("git clone --depth 1 --branch v1.10.1", readme)
        self.assertIn("git describe --exact-match --tags HEAD", readme)
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

    def test_docs_publish_the_v1_10_1_stable_url_install_contract(self):
        for path in URL_INSTALL_DOCS:
            with self.subTest(document=path.name):
                text = path.read_text(encoding="utf-8-sig")
                self.assertIn("v1.10.1", text)
                self.assertIn("install-codex.ps1", text)
                self.assertNotIn("Before either local installation, deploy", text)
                self.assertIn("git clone --depth 1 --branch v1.10.1", text)
                self.assertIn("git describe --exact-match --tags HEAD", text)
                self.assertNotRegex(
                    text,
                    re.compile(
                        r"v1\.10\.1.{0,80}(?:unreleased|not published|do not (?:install|clone|run))"
                        r"|(?:unreleased|not published|do not (?:install|clone|run)).{0,80}v1\.10\.1",
                        re.IGNORECASE | re.DOTALL,
                    ),
                )

        install_contract = INSTALL_CONTRACT.read_text(encoding="utf-8")
        self.assertIn("install.bat", install_contract)
        self.assertIn("SSO/MFA", install_contract)
        self.assertIn("start a new Codex task", install_contract)
        self.assertIn("restart Antigravity", install_contract)
        self.assertIn("End users do not deploy", install_contract)
        self.assertIn("production Case ID", install_contract)

    def test_release_docs_gate_main_tag_url_acceptance_and_tagged_zip_in_order(self):
        publication_docs = (AGENTS, IMPLEMENTATION_PLAN, RELEASE_CHECKLIST)
        ordered_markers = (
            "Push the candidate branch and verify its exact remote SHA",
            "Run explicit-SHA clean-profile acceptance",
            "git push origin HEAD:main",
            "$RemoteMainSha",
            "Verify the default-branch README",
            "git tag -a v1.10.1 $CandidateSha",
            "Run URL-only acceptance",
            "Build and verify the release ZIP",
            "gh release create v1.10.1",
        )
        for path in publication_docs:
            with self.subTest(document=path.name):
                content = re.sub(
                    r"\s+", " ", path.read_text(encoding="utf-8-sig")
                )
                positions = []
                for marker in ordered_markers:
                    self.assertIn(marker, content)
                    positions.append(content.index(marker))
                self.assertEqual(positions, sorted(positions))
                self.assertIn("git clone --depth 1 --branch main", content)
                self.assertIn("$StableBootstrap", content)
                self.assertIn("never force", content)
                self.assertIn("refs/tags/v1.10.1^{}", content)
                self.assertIn("fresh, clean, detached checkout", content)
                self.assertIn("git clone --no-checkout", content)
                self.assertIn("checkout --detach", content)
                self.assertIn("status --porcelain", content)

        for path in (IMPLEMENTATION_PLAN, RELEASE_CHECKLIST):
            with self.subTest(zip_verification=path.name):
                content = re.sub(
                    r"\s+", " ", path.read_text(encoding="utf-8-sig")
                )
                self.assertIn("$TaggedSha -cne $CandidateSha", content)
                self.assertIn("actual != manifest", content)
                self.assertIn(
                    "archive.read(name) != (checkout / name).read_bytes()",
                    content,
                )
                self.assertIn("Do not build from the candidate worktree", content)

        checklist = RELEASE_CHECKLIST.read_text(encoding="utf-8-sig")
        self.assertNotIn("Build the ZIP strictly from `release-manifest.txt`", checklist)

    def test_release_commands_publish_the_archive_built_by_the_tagged_checkout(self):
        for path in (AGENTS, IMPLEMENTATION_PLAN, RELEASE_CHECKLIST):
            with self.subTest(document=path.name):
                content = path.read_text(encoding="utf-8-sig")
                build_start = content.index("Build and verify the release ZIP")
                publish_start = content.index("Publish", build_start)
                build = content[build_start:publish_start]
                publish = content[publish_start:]
                assignment = re.search(r"(?m)^\s*(\$ArchivePath)\s*=", build)
                self.assertIsNotNone(assignment)
                archive_variable = assignment.group(1)
                if path != AGENTS:
                    self.assertIn(
                        f"python - $ReleaseCheckout {archive_variable}",
                        build,
                    )
                release_command = re.search(
                    r"(?m)^\s*gh release create v1\.10\.1\s+(\S+)",
                    publish,
                )
                self.assertIsNotNone(release_command)
                self.assertEqual(archive_variable, release_command.group(1))

    def test_dependency_docs_publish_the_tested_mcp_pin(self):
        for path in DEPENDENCY_CONTRACT_DOCS:
            with self.subTest(document=path.name):
                text = path.read_text(encoding="utf-8-sig")
                self.assertIn("mcp==1.28.1", text)
                self.assertIn("MCP 2.x", text)

        expected_command = "pip install mcp==1.28.1 playwright setuptools>=68"
        for path in (TDD_MD, TDD_HTML):
            with self.subTest(dependency_command=path.name):
                commands = [
                    line.strip()
                    for line in path.read_text(encoding="utf-8-sig").splitlines()
                    if line.strip().startswith("pip install mcp")
                ]
                self.assertEqual([expected_command], commands)

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
