import html
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/avaya-case-review/skills/case-review/SKILL.md"
GMAIL_CAPABILITY_SKILL = ROOT / "plugins/avaya-case-review/skills/gmail-capability/SKILL.md"
MANAGER_MD = ROOT / "docs/MANAGER_ONBOARDING_GUIDE.md"
MANAGER_HTML = ROOT / "docs/MANAGER_ONBOARDING_GUIDE.html"
TDD_MD = ROOT / "docs/TECHNICAL_DESIGN_DOCUMENT.md"
TDD_HTML = ROOT / "docs/TECHNICAL_DESIGN_DOCUMENT.html"
GMAIL_EDGE_BROKER_MD = ROOT / "docs/GMAIL_EDGE_BROKER.md"
GMAIL_CLOUD_BRIDGE_MD = ROOT / "docs/GMAIL_CLOUD_BRIDGE.md"
RELEASE_MD = ROOT / "docs/RELEASE_NOTES.md"
RELEASE_HTML = ROOT / "docs/RELEASE_NOTES.html"
ADM_SPEC = ROOT / "docs/superpowers/specs/2026-08-02-adm-adaptive-integration-design.md"
PRESENTATION_HTML = ROOT / "docs/PRESENTATION.html"
README_MD = ROOT / "README.md"
README_HTML = ROOT / "README.html"
RELEASE_MANIFEST = ROOT / "release-manifest.txt"
PLUGIN_JSON = ROOT / "plugins/avaya-case-review/plugin.json"
AGENTS_MD = ROOT / "AGENTS.md"
APPS_SCRIPT = ROOT / "examples/optional-appsscript/Code.gs"
SCENARIOS = ROOT / "tests/case_review_scenarios.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def extract_report_template(skill: str) -> str:
    match = re.search(r"```markdown\n(.*?)\n```", skill, re.DOTALL)
    if not match:
        raise AssertionError("Rendered report template not found")
    return match.group(1)


def extract_template_section(template: str, heading: str, next_heading: str) -> str:
    start = template.index(heading) + len(heading)
    end = template.index(next_heading, start)
    return template[start:end]


def extract_contract_window(content: str) -> str:
    anchor = content.index("6-8 sentence")
    return content[max(0, anchor - 200) : min(len(content), anchor + 4200)]


def extract_between(content: str, start_marker: str, end_marker: str) -> str:
    start = content.index(start_marker)
    end = content.index(end_marker, start)
    return content[start:end]


def extract_fenced_block_after(content: str, anchor: str, language: str) -> str:
    start = content.index(anchor)
    match = re.search(
        rf"```{re.escape(language)}\n(.*?)\n```",
        content[start:],
        re.DOTALL,
    )
    if not match:
        raise AssertionError(f"{language} fenced block not found after {anchor}")
    return match.group(1)


def extract_html_pre_after(content: str, anchor: str) -> str:
    start = content.index(anchor)
    match = re.search(r"<pre>(.*?)</pre>", content[start:], re.DOTALL)
    if not match:
        raise AssertionError(f"HTML pre block not found after {anchor}")
    return html.unescape(match.group(1))


class StrictHTMLParser(HTMLParser):
    VOID_ELEMENTS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self.open_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag not in self.VOID_ELEMENTS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if not self.open_tags:
            raise AssertionError(f"Unexpected closing tag </{tag}>")
        expected = self.open_tags[-1]
        if tag != expected:
            raise AssertionError(
                f"Closing tag </{tag}> does not match open tag <{expected}>"
            )
        self.open_tags.pop()

    def close(self) -> None:
        super().close()
        if self.open_tags:
            unclosed = " > ".join(f"<{tag}>" for tag in self.open_tags)
            raise AssertionError(f"Unclosed HTML tags: {unclosed}")


def validate_html_structure(content: str) -> None:
    parser = StrictHTMLParser()
    parser.feed(content)
    parser.close()


def normalize_contract_item(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", "", value))
    value = re.sub(r"(?:\*\*|`)", "", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_markdown_list_items(section: str) -> list[str]:
    return [
        normalize_contract_item(match.group(1))
        for match in re.finditer(r"(?m)^(?:\d+\.|-)\s+(.*)$", section)
    ]


def extract_html_list_items(section: str) -> list[str]:
    return [
        normalize_contract_item(item)
        for item in re.findall(r"<li>(.*?)</li>", section, re.DOTALL)
    ]


def extract_release_unreleased_section(content: str, html_document: bool) -> str:
    if html_document:
        return extract_between(
            content,
            "<!-- UNRELEASED -->",
            "<!-- VERSION 1.7.0 -->",
        )
    return extract_between(content, "## [Unreleased]", "## [v1.7.0]")


def extract_release_unreleased_items(section: str, html_document: bool) -> list[str]:
    if html_document:
        return extract_html_list_items(section)
    return [
        normalize_contract_item(match.group(1))
        for match in re.finditer(r"(?m)^\*\s+(.*)$", section)
    ]


def normalized_function_signatures(source: str) -> list[str]:
    functions = (
        "doPost",
        "updateCaseTrackingSheet",
        "createGoogleDocReport",
        "sendDailyManagerDigest",
    )
    pattern = rf"^\s*function\s+({'|'.join(functions)})\s*\(([^)]*)\)"
    signatures = []
    for match in re.finditer(pattern, source, re.MULTILINE):
        parameters = ",".join(
            parameter.strip()
            for parameter in match.group(2).split(",")
            if parameter.strip()
        )
        signatures.append(f"{match.group(1)}({parameters})")
    return signatures


class CaseReviewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = read(SKILL)
        cls.contract_docs = {
            "manager_md": read(MANAGER_MD),
            "manager_html": read(MANAGER_HTML),
            "tdd_md": read(TDD_MD),
            "tdd_html": read(TDD_HTML),
            "readme_md": read(README_MD),
            "readme_html": read(README_HTML),
        }
        cls.workflow_docs = {
            "agents": read(AGENTS_MD),
            "gmail_capability": read(GMAIL_CAPABILITY_SKILL),
            "manager_md": cls.contract_docs["manager_md"],
            "manager_html": cls.contract_docs["manager_html"],
            "tdd_md": cls.contract_docs["tdd_md"],
            "tdd_html": cls.contract_docs["tdd_html"],
        }

    def test_dynamic_evidence_gate_is_explicit(self):
        required = [
            "E1..EN",
            "Source",
            "Date",
            "Verbatim evidence / data",
            "Supports",
            "output exactly `unknown`",
            "Do not split, duplicate, or invent evidence",
        ]
        for marker in required:
            self.assertIn(marker, self.skill)

    def test_staleness_has_status_gate_and_two_clocks(self):
        for marker in [
            "Closed/Resolved",
            "Case record freshness",
            "Last substantive progress age",
        ]:
            self.assertIn(marker, self.skill)
        self.assertNotRegex(
            self.skill,
            r"today \(>7 days = .*STALE, >30 days = .*CRITICAL STALL\)",
        )

    def test_tool_contract_and_failure_branches_are_explicit(self):
        for marker in [
            "pass the raw ID without normalization",
            "INC, SR, Activity, CTASK, CHG, or PRJTASK",
            "Gmail tool is missing or the search call fails",
            "Gmail search succeeds but returns no relevant messages",
        ]:
            self.assertIn(marker, self.skill)

    def test_complete_context_gate_precedes_analysis(self):
        retrieve = extract_between(
            self.skill,
            "### Step 2 - Retrieve Required Sources",
            "### Step 4 - Analyze Only What the Evidence Supports",
        )
        for marker in [
            "Complete Context Before Analysis",
            "every discrete Case note",
            "gmail_list_threads",
            "gmail_read_thread_page",
            "next_page_token",
            "next_cursor",
            "Context Coverage Ledger",
            "Context collection incomplete — review not generated.",
        ]:
            self.assertIn(marker, retrieve)
        self.assertLess(
            self.skill.index("Complete Context Before Analysis"),
            self.skill.index("### Step 4 - Analyze Only What the Evidence Supports"),
        )

        gmail_collection = extract_between(
            retrieve,
            "#### Gmail",
            "### Step 3 - Build the Evidence Ledger",
        )
        self.assertNotIn("Read relevant messages", gmail_collection)
        self.assertNotIn("prioritizing", gmail_collection)

    def test_context_coverage_ledger_requires_complete_equalities(self):
        retrieve = extract_between(
            self.skill,
            "### Complete Context Before Analysis",
            "### Step 4 - Analyze Only What the Evidence Supports",
        )
        ledger_fields = set(
            extract_fenced_block_after(
                retrieve,
                "Maintain this internal **Context Coverage Ledger**",
                "text",
            ).splitlines()
        )
        for field in [
            "unique_threads_discovered",
            "threads_read_complete",
            "messages_expected",
            "messages_completed",
            "message_chunks_expected",
            "message_chunks_completed",
        ]:
            self.assertIn(field, ledger_fields)
        for marker in [
            "case_notes_discovered == case_notes_processed",
            "record_ids_planned == record_id_queries_completed",
            "query_pages_completed",
            "unique_threads_discovered == threads_read_complete",
            "messages_expected == messages_completed",
            "message_chunks_expected == message_chunks_completed",
            "body_hashes_verified == messages_completed",
            "all thread manifest hashes were stable",
            "gmail_threads_discovered == gmail_threads_enumerated",
            "gmail_threads_discovered == gmail_threads_read_complete",
            "gmail_messages_expected == gmail_messages_read",
            "body_chunks_expected == body_chunks_read",
            "body_hashes_verified == gmail_messages_read",
            "manifest_hashes_stable",
            "snapshot_before",
        ]:
            self.assertIn(marker, retrieve)

    def test_incomplete_context_output_contains_no_review_sections(self):
        failure = extract_fenced_block_after(
            self.skill,
            "respond with `Context collection incomplete — review not generated.` using exactly this block:",
            "text",
        )
        self.assertEqual(
            failure.splitlines(),
            [
                "Context collection incomplete — review not generated.",
                "",
                "Case notes: <processed>/<discovered>",
                "Record-ID queries: <completed>/<planned>",
                "Gmail threads: <completed>/<discovered>",
                "Gmail messages: <completed>/<expected>",
                "Blocker: <exact sanitized failure>",
            ],
        )
        for forbidden in [
            "Executive Summary",
            "Technical & Incident Assessment",
            "Progress Summary",
            "Root cause",
            "Appendix A",
        ]:
            self.assertNotIn(forbidden, failure)

    def test_snapshot_bootstrap_requires_nonempty_reuse(self):
        gmail = extract_between(
            self.skill,
            "#### Gmail",
            "#### Context Coverage Ledger",
        )
        bootstrap = gmail.index(
            "The bootstrap input for the first frozen-ID query may be empty",
        )
        bootstrap_input = gmail.index('snapshot_before: ""', bootstrap)
        bootstrap_output = gmail.index(
            "The first successful response **must return a non-empty `snapshot_before`**",
            bootstrap_input,
        )
        reused_snapshot = gmail.index(
            "Every later list/read call must pass that **exact same non-empty `snapshot_before`**",
        )
        self.assertLess(bootstrap, bootstrap_input)
        self.assertLess(bootstrap_input, bootstrap_output)
        self.assertLess(bootstrap_output, reused_snapshot)
        self.assertNotIn("non-empty on every Gmail list and read call", gmail)

    def test_snapshot_reflection_repeats_bootstrap_exception_and_reuse_rule(self):
        retrieval = extract_between(
            self.skill,
            "### Complete Context Before Analysis",
            "### Step 4 - Analyze Only What the Evidence Supports",
        )
        reflection = extract_between(
            self.skill,
            "### Step 6 - Reflection and Coverage Review",
            "### Step 7 - Produce the Review",
        )
        for marker in [
            "bootstrap request may be empty",
            "bootstrap response establishes a non-empty `snapshot_before`",
            "subsequent list/read calls reuse that exact value",
        ]:
            self.assertIn(marker, reflection)
        self.assertNotIn(
            "one identical non-empty `snapshot_before` across all Gmail calls",
            retrieval + reflection,
        )
        self.assertLess(
            retrieval.index("bootstrap input for the first frozen-ID query may be empty"),
            retrieval.index("Every later list/read call must pass that **exact same non-empty `snapshot_before`**"),
        )

    def test_case_to_md_failure_has_safe_pre_ledger_blocker(self):
        case_to_md = extract_between(
            self.skill,
            "#### CaseToMD",
            "### Complete Context Before Analysis",
        )
        self.assertIn("before the Context Coverage Ledger exists", case_to_md)
        failure = extract_fenced_block_after(
            case_to_md,
            "CaseToMD pre-ledger blocker:",
            "text",
        )
        self.assertEqual(
            failure.splitlines(),
            [
                "Context collection incomplete — review not generated.",
                "",
                "Case notes: 0/unknown",
                "Record-ID queries: 0/unknown",
                "Gmail threads: 0/unknown",
                "Gmail messages: 0/unknown",
                "Blocker: CaseToMD unavailable — <exact sanitized failure>",
            ],
        )

    def test_incomplete_context_retry_requires_fresh_snapshot_and_discards_partial_corpus(self):
        gate = extract_between(
            self.skill,
            "If any source, pagination chain, cursor chain",
            "### Step 3 - Build the Evidence Ledger",
        )
        retry = gate.index("A retry starts from the same raw Case ID")
        fresh = gate.index("new `snapshot_before`", retry)
        discard = gate.index("discards the partial corpus", fresh)
        self.assertLess(retry, fresh)
        self.assertLess(fresh, discard)
        self.assertIn("does not reuse it", gate)

    def test_workflow_docs_use_exhaustive_tools_and_forbid_relevance_collection(self):
        required = [
            "Complete Context Before Analysis",
            "gmail_list_threads",
            "gmail_read_thread_page",
            "Context Coverage Ledger",
            "Context collection incomplete",
            "gmail_search",
            "gmail_read",
            "backward-compatible",
        ]
        forbidden = re.compile(
            r"(?:read|retrieve|collect|find|search)\s+(?:only\s+)?"
            r"(?:relevant|prioritized|priority)\s+messages|prioritizing\s+commitments",
            re.IGNORECASE,
        )
        for name, content in self.workflow_docs.items():
            with self.subTest(document=name):
                for marker in required:
                    self.assertIn(marker, content)
                self.assertIsNone(forbidden.search(content))

    def test_core_docs_explain_the_cloud_backed_exhaustive_context_gate(self):
        required = [
            "Complete Context Before Analysis",
            "every Case note",
            "every message in every matched Gmail thread",
            "Context collection incomplete",
            "Advanced Gmail Service",
        ]
        documents = {
            **self.contract_docs,
            "gmail_edge_broker": read(GMAIL_EDGE_BROKER_MD),
        }
        for name, content in documents.items():
            with self.subTest(document=name):
                for marker in required:
                    self.assertIn(marker, content)

    def test_cloud_bridge_runbook_has_safe_order_scope_and_rollback(self):
        runbook = read(GMAIL_CLOUD_BRIDGE_MD)
        ordered_markers = [
            "existing Gmail MCP Apps Script",
            "Advanced Gmail Service",
            "Gmail v1",
            "tools/gmail/cloud/GmailMcpBridge.gs",
            "syntax check",
            "Manage deployments",
            "New version",
            "existing deployment URL",
            "controlled authorization",
            "zero-result",
            "complete=true",
            "stable snapshot",
            "page-token chain",
            "multi-message thread",
            "cursor exhaustion",
            "hash/count checks",
            "Only then",
        ]
        offsets = [runbook.index(marker) for marker in ordered_markers]
        self.assertEqual(offsets, sorted(offsets))
        for marker in [
            "optional governance example",
            "related-ID boundary",
            "Attachments are excluded",
            "Context collection incomplete",
            "gmail_search",
            "gmail_read",
            "backward-compatible",
            "prior Apps Script version",
            "Agent gate inactive",
        ]:
            self.assertIn(marker, runbook)
        for marker in [
            "If local deployment has already occurred",
            "Stop Antigravity",
            r'python "%USERPROFILE%\.gemini\tools\gmail\gmail_brokerctl.py" stop',
            r'python "%USERPROFILE%\.gemini\tools\gmail\gmail_brokerctl.py" status',
            "independent Gmail broker",
            "no running broker",
            "Do not replace local files while either is still active",
            "Restore the prior package",
            "case-review/SKILL.md",
            "tools/gmail",
        ]:
            self.assertIn(marker, runbook)

        rollback = extract_between(runbook, "## Rollback", "Keep the exhaustive Agent gate inactive")
        rollback_offsets = [
            rollback.index("Stop Antigravity"),
            rollback.index('gmail_brokerctl.py" stop'),
            rollback.index("no running broker"),
            rollback.index("Restore the prior package"),
        ]
        self.assertEqual(rollback_offsets, sorted(rollback_offsets))

    def test_cloud_bridge_verification_examples_are_exhaustive_and_sanitized(self):
        runbook = read(GMAIL_CLOUD_BRIDGE_MD)
        verification = extract_between(
            runbook,
            "## Sanitized verification examples",
            "## Collection contract",
        )
        for marker in [
            "GMAIL_VERIFY_WEB_APP_URL",
            "Invoke-RestMethod",
            "zero-result complete=true",
            "zero-result next page token empty",
            "page snapshot reused",
            "cursor complete flag matches next cursor",
            "thread count enumerated/read",
            "thread message count",
            "thread manifest hash",
            "manifest hash stable across cursors",
            "message count expected/read",
            "body byte count",
            "body hash",
            "at least one multi-message thread exercised",
            "response bodies, IDs, tokens, cursors, and secrets were not printed or logged",
            "Out-Null",
        ]:
            self.assertIn(marker, verification)
        for forbidden in [
            "script.googleusercontent.com",
            "https://",
            "1-23659220672",
            "INC7429951",
            "BEGIN PRIVATE KEY",
        ]:
            self.assertNotIn(forbidden, verification)

    def test_cloud_deployment_precedes_local_install_and_activation_in_each_core_doc(self):
        readme_md = read(README_MD)
        readme_html = read(README_HTML)
        manager_md = read(MANAGER_MD)
        manager_html = read(MANAGER_HTML)
        tdd_md = read(TDD_MD)
        tdd_html = read(TDD_HTML)
        agents = read(AGENTS_MD)
        documents = {
            "readme_md": readme_md[readme_md.index("## Cloud Prerequisite"):],
            "readme_html": readme_html[readme_html.index("<h2>Cloud Prerequisite"):],
            "manager_md": extract_between(
                manager_md,
                "## 2. Quick Start: One-Click Automated Setup",
                "## 5. Using the Case Review Capability",
            ),
            "manager_html": extract_between(
                manager_html,
                "<h2>2. Quick Start: One-Click Automated Setup</h2>",
                "<h2>5. Using the Case Review Capability</h2>",
            ),
            "tdd_md": extract_between(
                tdd_md,
                "## 5. Deployment & Installation Architecture",
                "## 6. Verification & Validation Framework",
            ),
            "tdd_html": extract_between(
                tdd_html,
                "<h2>5. Deployment & Installation Architecture</h2>",
                "<h2>6. Verification &amp; Validation Framework</h2>",
            ),
            "agents": extract_between(
                agents,
                "## 1. What this repo is",
                "## 2. When the user asks for a case review",
            ),
        }
        for name, content in documents.items():
            with self.subTest(document=name):
                cloud = content.index("Cloud deployment and verification")
                self.assertLess(
                    content.index("Advanced Gmail Service"),
                    cloud,
                )
                for local_marker in [
                    "install.bat",
                    "setup_env.ps1",
                    "local Agent SKILL",
                ]:
                    self.assertLess(
                        cloud,
                        content.index(local_marker),
                        f"{local_marker} appears before the cloud gate",
                    )

    def test_manager_guides_describe_managed_edge_default_and_chromium_rollback(self):
        stale_claim = "headless browser engine required for Gmail automation"
        for path in [MANAGER_MD, MANAGER_HTML]:
            with self.subTest(document=path.name):
                content = normalize_contract_item(read(path))
                self.assertIn(
                    "default Gmail operation uses the single Managed Edge broker",
                    content,
                )
                self.assertIn(
                    "Downloads Chromium only for the explicit legacy_playwright rollback path",
                    content,
                )
                self.assertNotIn(stale_claim, content.lower())

    def test_core_docs_do_not_claim_local_installation_is_completely_automated(self):
        for path in [TDD_MD, TDD_HTML]:
            with self.subTest(document=path.name):
                self.assertNotIn("Installation is completely automated", read(path))
        agents = read(AGENTS_MD)
        self.assertNotIn("deploys everything into", agents)
        self.assertNotIn(
            "The files in this repo get **deployed** by `install.bat`",
            agents,
        )

    def test_unreleased_notes_cover_cloud_bridge_without_version_bump(self):
        release_md = extract_release_unreleased_section(read(RELEASE_MD), html_document=False)
        release_html = extract_release_unreleased_section(read(RELEASE_HTML), html_document=True)
        md_items = extract_release_unreleased_items(release_md, html_document=False)
        html_items = extract_release_unreleased_items(release_html, html_document=True)
        self.assertEqual(md_items, html_items)
        required_claims = [
            "Advanced Gmail Service",
            "tools/gmail/cloud/GmailMcpBridge.gs",
            "existing-Web-App deployment",
            "setup_env.ps1",
            "gmail_list_threads",
            "gmail_read_thread_page",
            "one stable snapshot",
            "page-token and cursor chains",
            "message/body counts",
            "hash verification",
            "Complete Context Before Analysis",
            "every Case note",
            "every message in every matched Gmail thread",
            "related-ID boundary",
            "attachment bodies remain excluded",
            "Context collection incomplete",
            "sanitized counts and a blocker",
            "backward-compatible APIs",
            "Agent gate inactive",
            "zero-result",
            "real-case pagination",
            "multi-message cursor verification",
        ]
        for claim in required_claims:
            with self.subTest(claim=claim):
                self.assertTrue(
                    any(claim in item for item in md_items),
                    f"Unreleased MD section missing claim: {claim}",
                )

    def test_exhaustive_scenarios_are_checked_in_their_workflow_sections(self):
        scenarios = {scenario["id"]: scenario for scenario in json.loads(read(SCENARIOS))}
        gmail = extract_between(
            self.skill,
            "#### Gmail",
            "#### Context Coverage Ledger",
        )
        complete_gate = extract_between(
            self.skill,
            "### Complete Context Before Analysis",
            "### Step 4 - Analyze Only What the Evidence Supports",
        )
        windows = {
            "all_case_notes_before_gmail": complete_gate,
            "multipage_gmail_threads": gmail,
            "every_message_in_thread": complete_gate,
            "incomplete_context_blocks_review": complete_gate,
            "complete_zero_gmail_results": gmail,
            "token_and_cursor_loops_block_review": gmail,
            "disappearing_thread_blocks_review": complete_gate,
            "snapshot_after_messages_excluded": gmail,
            "attachment_metadata_out_of_scope_content": complete_gate,
        }
        for scenario_id, section in windows.items():
            with self.subTest(scenario=scenario_id):
                scenario = scenarios[scenario_id]
                self.assertTrue(scenario["expected"].strip())
                for marker in scenario["contract_markers"]:
                    self.assertIn(marker, section)

    def test_evidence_authority_is_not_management_display_priority(self):
        for marker in [
            "Evidentiary authority",
            "Management display priority",
            "Do not discard status pings before analysis",
            "unresolved source conflict",
        ]:
            self.assertIn(marker, self.skill)

    def test_rendered_date_time_content_is_ascending(self):
        for marker in [
            "Chronological output order",
            "ascending order (oldest first)",
            "undated entries after all dated entries",
            "Assign rendered `E1..EN` identifiers after this chronological sort",
            "oldest first",
            "ascending date/time order",
        ]:
            self.assertIn(marker, self.skill)
        self.assertNotIn("newest first", self.skill)

        for name, content in self.contract_docs.items():
            with self.subTest(document=name):
                self.assertIn("oldest to newest", content)

        apps_script = read(APPS_SCRIPT)
        self.assertIn("sortEvidenceByDateAscending", apps_script)
        self.assertIn("parseEvidenceTimestamp", apps_script)

    def test_mitigation_maturity_prevents_false_production_claims(self):
        for marker in [
            "Proposed",
            "Lab Validated",
            "Production Deployed",
            "Production Outcome Confirmed",
            "must not be described as production resolution",
        ]:
            self.assertIn(marker, self.skill)

    def test_conditional_schema_and_manager_judgment_boundary(self):
        conditional = extract_template_section(
            self.skill,
            "For the conditional technical section:",
            "\n---\n\n## Non-Negotiable Rules",
        )
        self.assertEqual(1, conditional.count("**Multi-problem:**"))
        self.assertEqual(1, conditional.count("**Single issue:**"))
        self.assertIn("Choose exactly one structure", conditional)
        self.assertIn("mutually exclusive", conditional)
        self.assertIn("Do not render both conditional structures", conditional)
        self.assertIn("second ADM block", conditional)
        self.assertIn("must never generate a new recommendation", self.skill)
        self.assertNotIn("All action items must live exclusively", self.skill)
        self.assertNotIn("### [Structure A:", self.skill)
        self.assertNotIn("### [Structure B:", self.skill)

    def test_executive_summary_is_one_layered_paragraph(self):
        template = extract_report_template(self.skill)
        self.assertEqual(1, template.count("## Executive Summary"))
        self.assertEqual(1, template.count("## Technical & Incident Assessment"))
        summary = extract_template_section(
            template,
            "## Executive Summary",
            "## Technical & Incident Assessment",
        )
        content_lines = [line.strip() for line in summary.splitlines() if line.strip()]
        self.assertEqual(1, len(content_lines))
        self.assertNotIn("Verdict", template)
        self.assertNotRegex(summary, r"(?m)^\s*#{1,6}\s+")
        self.assertNotRegex(summary, r"(?m)^\s*[-*+]\s+")
        self.assertNotRegex(
            summary,
            r"(?m)^\s*(?:[-*+]\s+)?(?:\*\*)?[A-Za-z][A-Za-z &/()-]{0,40}:(?:\*\*)?\s*",
        )
        for marker in [
            "Core Incident Details",
            "Impact and Response",
            "Next Steps",
            "Future prevention",
            "Existing prevention controls",
        ]:
            self.assertNotIn(marker, summary)
        executive_contract = extract_template_section(
            self.skill,
            "#### Executive Summary contract",
            "#### Technical & Incident Assessment contract",
        )
        for marker in [
            "one natural-language paragraph of 6-8 sentences",
            "one-sentence technical conclusion",
            "`unknown`",
            "conclusion-level information",
        ]:
            self.assertIn(marker, executive_contract)

    def test_technical_assessment_adds_reasoning_without_restatement(self):
        template = extract_report_template(self.skill)
        technical = extract_template_section(
            template,
            "## Technical & Incident Assessment",
            "## Progress Summary",
        )
        self.assertIn("Start with problem clarification", technical)
        technical_contract = extract_template_section(
            self.skill,
            "#### Technical & Incident Assessment contract",
            "#### Adaptive ADM depth",
        )
        for marker in [
            "environment or affected-component detail",
            "causal reasoning or an RCA-state explanation",
            "solution, workaround, implementation, or verification detail",
            "only paraphrases an Executive Summary sentence",
            "Existing prevention controls",
        ]:
            self.assertIn(marker, technical_contract)

    def test_progress_summary_count_follows_available_evidence(self):
        template = extract_report_template(self.skill)
        progress = extract_template_section(
            template,
            "## Progress Summary",
            "## Ownership & Next Step",
        )
        for marker in [
            "Up to five substantive milestones supported by evidence",
            "render one when only one exists",
            "Do not pad or repeat evidence",
        ]:
            self.assertIn(marker, progress)
        self.assertNotIn("Three to five", progress)

    def test_adm_expands_technical_depth_without_duplicate_sections(self):
        template = extract_report_template(self.skill)
        adaptive_adm = extract_template_section(
            self.skill,
            "#### Adaptive ADM depth",
            "#### Generation order",
        )
        for marker in [
            "ADM mode activates only when the user explicitly requests `ADM` or `Avaya Diagnostic Methodology`, matched case-insensitively.",
            "Details/Findings",
            "Problem Clarification",
            "Cause",
            "Solution",
            "increases the depth of `Technical & Incident Assessment` only",
        ]:
            self.assertIn(marker, adaptive_adm)
        self.assertNotRegex(
            template,
            r"(?m)^## (?:ADM\b|Avaya Diagnostic Methodology\b)",
        )
        for heading in [
            "## Details/Findings",
            "## Problem Clarification",
            "## Cause",
            "## Solution",
        ]:
            self.assertNotIn(heading, template)

    def test_adm_sparse_evidence_uses_gaps_without_invention(self):
        adaptive_adm = extract_template_section(
            self.skill,
            "#### Adaptive ADM depth",
            "#### Generation order",
        )
        reflection = extract_template_section(
            self.skill,
            "### Step 6 - Reflection and Coverage Review",
            "### Step 7 - Produce the Review",
        )
        self.assertIn("When evidence permits, cover", adaptive_adm)
        for marker in [
            "For each of the four ADM dimensions",
            "evidence-supported content",
            "explicit unresolved evidence or investigation gap",
            "rigid filler or invention",
        ]:
            self.assertIn(marker, adaptive_adm)
            self.assertIn(marker, reflection)
        self.assertNotIn(
            "confirm all four analytical dimensions are covered",
            reflection.lower(),
        )

    def test_preventive_next_checkpoint_is_commitment_not_control(self):
        template = extract_report_template(self.skill)
        summary = extract_template_section(
            template,
            "## Executive Summary",
            "## Technical & Incident Assessment",
        )
        ownership = extract_template_section(
            template,
            "## Ownership & Next Step",
            "## Timeline",
        )
        executive_contract = extract_template_section(
            self.skill,
            "#### Executive Summary contract",
            "#### Technical & Incident Assessment contract",
        )
        technical_contract = extract_template_section(
            self.skill,
            "#### Technical & Incident Assessment contract",
            "#### Adaptive ADM depth",
        )
        conditional = extract_template_section(
            self.skill,
            "For the conditional technical section:",
            "\n---\n\n## Non-Negotiable Rules",
        )

        self.assertIn("Stated next action", ownership)
        self.assertIn("evidence-stated preventive next checkpoint", summary)
        self.assertNotIn("Future prevention", summary)
        self.assertNotIn("Existing prevention controls", summary)
        for marker in [
            "No dedicated `Future prevention` field, recommendation, or prevention narrative",
            "evidence-stated next action or checkpoint",
            "existing commitment or current planned work",
            "never as an agent recommendation or implemented control",
        ]:
            self.assertIn(marker, executive_contract)
        for marker in [
            "only when evidence shows they are implemented",
            "Planned or committed preventive work that is not implemented must not be labeled an Existing prevention control",
        ]:
            self.assertIn(marker, technical_contract)
        self.assertIn("only under the relevant problem", conditional)
        self.assertIn("only when evidence confirms they are implemented", conditional)

    def test_appendix_is_last_and_body_has_no_evidence_markers(self):
        template = extract_report_template(self.skill)
        self.assertIn("## Appendix A — Evidence Register", template)
        appendix = template.index("## Appendix A — Evidence Register")
        order = [
            template.index("## Executive Summary"),
            template.index("## Technical & Incident Assessment"),
            template.index("## Progress Summary"),
            template.index("## Ownership & Next Step"),
            template.index("## Timeline"),
            appendix,
        ]
        self.assertEqual(order, sorted(order))
        body = template[:appendix]
        self.assertNotRegex(
            body,
            r"\[(?:Evidence\s+\d+|E\d+)\]|Evidence IDs?|Evidence N",
        )
        self.assertIn(
            "| Ref | Date | Source | Verbatim evidence / data | Supports |",
            template,
        )
        self.assertTrue(
            template.rstrip().endswith(
                "<Evidence rows E1..EN in ascending date/time order; undated rows last>"
            )
        )

    def test_manager_judgment_sections_are_absent(self):
        template = extract_report_template(self.skill)
        self.assertNotIn("## Risk Flags", template)
        self.assertNotIn("## Targeted Recommendations", template)
        self.assertIn("must never generate a new recommendation", self.skill)

    def test_current_contract_docs_match_skill(self):
        required = [
            "Executive Summary",
            "Appendix A",
            "Verbatim evidence / data",
            "Supports",
            "Case record freshness",
            "Last substantive progress age",
            "Production Outcome Confirmed",
        ]
        prohibited = [
            "Risk Flags",
            "Targeted Recommendations",
            "linked numbered `Action 1`",
            "Additional Datapoints & Customer Experience Metrics",
        ]
        for name, content in self.contract_docs.items():
            with self.subTest(document=name):
                for marker in required:
                    self.assertIn(marker, content)
                for marker in prohibited:
                    self.assertNotIn(marker, content)

    def test_contract_docs_describe_layered_disclosure(self):
        required = [
            "6-8 sentence",
            "conclusion-level",
            "technical reasoning",
            "Future prevention is excluded from Executive Summary",
            "Existing prevention controls",
            "evidence confirms they are implemented",
            "Planned or committed preventive work",
            "evidence-stated next checkpoint",
            "never labeled an Existing prevention control or an agent recommendation",
        ]
        old_summary = (
            "Executive Summary covering the incident, timing and location, affected "
            "scope, business effect, response, root cause, prevention priorities"
        )
        for name, content in self.contract_docs.items():
            with self.subTest(document=name):
                contract = extract_contract_window(content)
                for marker in required:
                    self.assertIn(marker, contract)
                self.assertRegex(contract, r"timing(?:/| and )location")
                self.assertNotIn(old_summary, contract)

    def test_adm_spec_and_presentation_follow_layered_contract(self):
        adm_spec = read(ADM_SPEC)
        presentation = read(PRESENTATION_HTML)
        validate_html_structure(presentation)
        presentation_lower = presentation.lower()

        for marker in [
            "Executive Summary remains one 6-8 sentence paragraph",
            "Future prevention is excluded from Executive Summary",
            "Existing prevention controls",
            "does not append another set of ADM sections",
            "Existing prevention controls require evidence confirming implementation",
            "Planned or committed preventive work remains an evidence-stated checkpoint or planned work, not a recommendation or an implemented control",
        ]:
            self.assertIn(marker, adm_spec)

        for marker in [
            "Evidence-Grounded Technical Review",
            "Evidence-Grounded Technical Assessment",
            "Complete Context Before Analysis",
            "frozen record IDs",
            "incomplete collection blocks review",
            "manager judgment",
            "Single Managed Edge Broker",
            "serializes browser ownership for multiple Gmail MCP clients",
            "edge_broker_profile",
            "legacy_playwright",
            "explicit rollback",
            "Conditional Managed Edge Sign-In",
            "gmail_brokerctl.py login",
            "authentication required",
            "persistent session",
            "evidence-triggered guidance",
            "API Method Reference Check",
            "compares case usage with official Javadoc",
            "requested, attached, or analyzed",
            "Faster Preparation",
            "Evidence Traceability",
            "Earlier Escalation Signals",
            "only after case evidence establishes the failing component",
        ]:
            self.assertIn(marker, presentation)

        for marker in [
            "customer account names",
            "does not guarantee completeness",
        ]:
            self.assertNotIn(marker, presentation)

        structure_start = presentation.index(
            "<h2>Standardized Executive Review Report Structure</h2>"
        )
        structure_end = presentation.index("<!-- SLIDE 11 -->", structure_start)
        structure = presentation[structure_start:structure_end]
        section_headings = [
            "1. 6-8 Sentence Executive Summary",
            "2. Technical &amp; Incident Assessment",
            "3. Progress Summary",
            "4. Ownership &amp; Next Step",
            "5. Timeline",
            "6. Appendix A — Evidence Register",
        ]
        positions = []
        for heading in section_headings:
            marker = f"<h3>{heading}</h3>"
            self.assertEqual(1, structure.count(marker))
            positions.append(structure.index(marker))
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("Progress Summary &amp; Timeline", structure)
        self.assertNotIn("<h3>5. Evidence Appendix</h3>", structure)

        for marker in [
            "risk flag",
            "recommended manager actions",
            "prevention priorities",
            "manager action directive",
            "sanity & risk auditor",
            "zero technical blind spots",
            "playwright gmail mcp",
            "playwright headless browser automatically maintains local chrome session profile",
            "one-time google sso",
            "chrome window opens to authenticate",
            "automatically verifies whether",
            "enforces official javadoc path",
            "80% time saved",
            "zero blind spots",
            "30% faster mttr",
            "flagged as misdirected escalation",
        ]:
            self.assertNotIn(marker, presentation_lower)

        for path in [RELEASE_MD, RELEASE_HTML]:
            with self.subTest(document=path.name):
                content = read(path)
                self.assertIn("layered disclosure", content.lower())
                self.assertIn("6-8 sentence Executive Summary", content)

    def test_tdd_key_capability_uses_evidence_triggered_direction_checks(self):
        tdd_md = self.contract_docs["tdd_md"]
        tdd_html = self.contract_docs["tdd_html"]
        validate_html_structure(tdd_html)
        self.assertIn("### Key Capabilities", tdd_md)
        self.assertIn("<strong>Key Architectural Goals:</strong>", tdd_html)
        sections = {
            "tdd_md": extract_template_section(
                tdd_md,
                "### Key Capabilities",
                "\n---\n",
            ),
            "tdd_html": extract_template_section(
                tdd_html,
                "<strong>Key Architectural Goals:</strong>",
                "</div>",
            ),
        }
        required = [
            "Evidence-Triggered Technical Direction Checks",
            "compares retrieved evidence to conditional product references",
            "documents validation gaps and handoff context",
            "reference comparison alone does not prove cause or vendor ownership",
        ]
        prohibited = [
            "never proves cause or assigns a vendor itself",
            "Automated Sanity Auditing",
            "Detects engineer misdirection",
            "verifies system attribute dependencies",
            "enforces official Javadoc API methods",
            "flags misdirected vendor escalations",
        ]
        for name, section in sections.items():
            with self.subTest(document=name):
                for marker in required:
                    self.assertIn(marker, section)
                for marker in prohibited:
                    self.assertNotIn(marker, section)

    def test_tdd_conditional_direction_checks_are_evidence_gated_and_in_parity(self):
        tdd_md = self.contract_docs["tdd_md"]
        tdd_html = self.contract_docs["tdd_html"]
        validate_html_structure(tdd_html)
        md_heading = "#### Conditional Technical Direction Checks"
        html_heading = "<h4>Conditional Technical Direction Checks</h4>"
        self.assertIn(md_heading, tdd_md)
        self.assertIn(html_heading, tdd_html)
        sections = {
            "tdd_md": extract_template_section(
                tdd_md,
                md_heading,
                "#### Output Brief Schema",
            ),
            "tdd_html": extract_template_section(
                tdd_html,
                html_heading,
                "<h4>Output Brief Schema</h4>",
            ),
        }
        required = [
            "retrieved case evidence matches a layer mismatch",
            "compare platform and application hypotheses",
            "identify the validation needed to distinguish them",
            "Do not present CM configuration as causal without case evidence",
            "conditional verification references only when park/unpark evidence triggers them",
            "does not inspect the live system",
            "compare case evidence with official Javadoc",
            "does not enforce a method or prove causation",
            "requested, collected, attached, and analyzed",
            "identify evidence gaps",
            "getlogs",
            "conditional examples, not universal requirements",
        ]
        prohibited = [
            "Risk Audit",
            "underlying cause is",
            "Assign to",
            "ensure getlogs",
            "Automated Sanity Auditing",
        ]
        for name, section in sections.items():
            with self.subTest(document=name):
                for marker in required:
                    self.assertIn(marker, section)
                for marker in prohibited:
                    self.assertNotIn(marker, section)
        self.assertEqual(
            extract_markdown_list_items(sections["tdd_md"]),
            extract_html_list_items(sections["tdd_html"]),
        )

    def test_tdd_vendor_handoff_matrix_is_reference_only_and_in_parity(self):
        tdd_md = self.contract_docs["tdd_md"]
        tdd_html = self.contract_docs["tdd_html"]
        validate_html_structure(tdd_html)
        md_heading = "#### Vendor Handoff Reference Matrix"
        html_heading = "<h4>Vendor Handoff Reference Matrix</h4>"
        self.assertIn(md_heading, tdd_md)
        self.assertIn(html_heading, tdd_html)
        sections = {
            "tdd_md": extract_template_section(
                tdd_md,
                md_heading,
                "\n\n---\n",
            ),
            "tdd_html": extract_template_section(
                tdd_html,
                html_heading,
                "<h3>3.4 Optional Google Apps Script Governance Extension",
            ),
        }
        required = [
            "only after case evidence establishes the failing component",
            "Manager retains ownership and risk judgment",
            "Evidence-confirmed CM / AES core defect",
            "reference destination: [BBE PEA]",
        ]
        for name, section in sections.items():
            with self.subTest(document=name):
                for marker in required:
                    self.assertIn(marker, section)
                self.assertNotIn("Assign to", section)
        self.assertEqual(
            extract_markdown_list_items(sections["tdd_md"]),
            extract_html_list_items(sections["tdd_html"]),
        )

    def test_presentation_slide_two_frames_technical_direction_as_uncertainty(self):
        presentation = read(PRESENTATION_HTML)
        validate_html_structure(presentation)
        slide_two = extract_template_section(
            presentation,
            "<!-- SLIDE 2 -->",
            "<!-- SLIDE 3 -->",
        )
        for marker in [
            "Technical Direction Uncertainty",
            "evidence may support competing hypotheses",
            "Product references guide validation but do not prove cause",
            "Vendor handoff remains unresolved until case evidence establishes the failing component",
            "Missing logs or incomplete validation can delay a supported conclusion",
        ]:
            self.assertIn(marker, slide_two)
        for marker in [
            "blaming JTAPI SDK null returns instead of CM SA9114/SA9124 attributes",
            "Misdirected Product Escalations",
            "Wasted engineering weeks and prolonged customer outages due to invalid troubleshooting paths",
            "Risk Flag",
            "Sanity & Risk Auditor",
            "manager action directives",
            "Recommended Manager Actions",
            "Flagged as MISDIRECTED ESCALATION",
        ]:
            self.assertNotIn(marker, slide_two)

    def test_presentation_vendor_handoff_slide_matches_reference_matrix(self):
        presentation = read(PRESENTATION_HTML)
        validate_html_structure(presentation)
        slide_nine = extract_template_section(
            presentation,
            "<!-- SLIDE 9 -->",
            "<!-- SLIDE 10 -->",
        )
        tdd_matrix = extract_template_section(
            self.contract_docs["tdd_html"],
            "<h4>Vendor Handoff Reference Matrix</h4>",
            "<h3>3.4 Optional Google Apps Script Governance Extension",
        )
        rows = extract_html_list_items(slide_nine)
        self.assertEqual(5, len(rows))
        self.assertEqual(extract_html_list_items(tdd_matrix), rows)
        for row in rows:
            self.assertTrue(row.startswith("Evidence-confirmed "))
            self.assertIn("reference destination:", row)
        for marker in [
            "reference destination: [BBE PEA]",
            "reference destination: [CPE PEA]",
            "reference destination: [Verint Support Ticket]",
            "reference destination: [Nuance Support Ticket]",
            "Evidence-confirmed customer infrastructure condition",
            "reference destination: Customer / MSP",
            "only after case evidence establishes the failing component",
            "Manager retains ownership and risk judgment",
        ]:
            self.assertIn(marker, slide_nine)
        for marker in [
            "Core Software Bugs ➔",
            "Product Code ➔",
            "Customer / MSP Action",
            "Assign to",
        ]:
            self.assertNotIn(marker, slide_nine)

    def test_strict_html_validator_rejects_invalid_nesting(self):
        with self.assertRaisesRegex(AssertionError, "does not match"):
            validate_html_structure("<div><span></div></span>")
        with self.assertRaisesRegex(AssertionError, "Unclosed HTML tags"):
            validate_html_structure("<div><span></span>")

    def test_current_html_documents_have_strictly_balanced_tags(self):
        html_documents = [README_HTML, *sorted((ROOT / "docs").glob("*.html"))]
        for path in html_documents:
            with self.subTest(document=path.name):
                validate_html_structure(read(path))

    def test_tdd_contract_unconditionally_forbids_generated_recommendations(self):
        sections = {
            "tdd_md": extract_template_section(
                self.contract_docs["tdd_md"],
                "#### Evidence Processing Contract",
                "#### Vendor Handoff Reference Matrix",
            ),
            "tdd_html": extract_template_section(
                self.contract_docs["tdd_html"],
                "<h4>Evidence Processing Contract</h4>",
                "<h4>Vendor Handoff Reference Matrix</h4>",
            ),
        }
        for name, section in sections.items():
            with self.subTest(document=name):
                self.assertIn("The agent does not generate recommendations.", section)
                self.assertIn(
                    "Evidence-backed commitments may be restated only as planned work "
                    "or evidence-stated next checkpoints.",
                    section,
                )
                self.assertNotIn("unsupported recommendations", section)

    def test_tdd_optional_apps_script_contract_has_md_html_parity(self):
        tdd_md = self.contract_docs["tdd_md"]
        tdd_html = self.contract_docs["tdd_html"]
        for name, content in {"tdd_md": tdd_md, "tdd_html": tdd_html}.items():
            with self.subTest(document=name, contract="optional_boundary"):
                for marker in [
                    "separately configured caller",
                    "manually deployed optional extension",
                    "not sent or consumed by the active runtime",
                ]:
                    self.assertIn(marker, content)

        md_payload = json.loads(
            extract_fenced_block_after(tdd_md, "JSON Payload Contract", "json")
        )
        html_payload = json.loads(
            extract_html_pre_after(tdd_html, "JSON Payload Contract")
        )
        self.assertEqual(md_payload, html_payload)

        md_signatures = normalized_function_signatures(
            extract_fenced_block_after(tdd_md, "Optional capabilities", "javascript")
        )
        html_signatures = normalized_function_signatures(
            extract_html_pre_after(tdd_html, "Optional capabilities")
        )
        expected_signatures = [
            "doPost(e)",
            "updateCaseTrackingSheet(caseData)",
            "createGoogleDocReport(caseData)",
            "sendDailyManagerDigest()",
        ]
        self.assertEqual(expected_signatures, md_signatures)
        self.assertEqual(md_signatures, html_signatures)

    def test_tdd_architecture_workspace_row_matches_box_width(self):
        for name in ["tdd_md", "tdd_html"]:
            with self.subTest(document=name):
                lines = self.contract_docs[name].splitlines()
                row_index = next(
                    index
                    for index, line in enumerate(lines)
                    if "| 4. GOOGLE WORKSPACE SERVICES" in line
                )
                self.assertGreater(row_index, 0)
                self.assertEqual(len(lines[row_index - 1]), len(lines[row_index]))

    def test_readme_files_are_english_only(self):
        for path in [README_MD, README_HTML]:
            with self.subTest(document=path.name):
                self.assertNotRegex(read(path), r"[^\x00-\x7F]")

    def test_release_metadata_targets_v1_7_0(self):
        release_md = read(RELEASE_MD)
        release_html = read(RELEASE_HTML)
        self.assertIn("[v1.7.0]", release_md)
        self.assertIn("v1.7.0", release_html)
        self.assertIn("[v1.6.0]", release_md)
        self.assertIn("v1.6.0", release_html)
        self.assertIn("[v1.5.0]", release_md)
        self.assertIn("v1.5.0", release_html)
        self.assertIn("[v1.4.0]", release_md)
        self.assertIn("v1.4.0", release_html)
        self.assertIn("[Unreleased]", release_md)
        self.assertIn(">Unreleased<", release_html)
        self.assertIn("Single Managed Edge Gmail Broker", release_md)
        self.assertIn("Single Managed Edge Gmail Broker", release_html)
        self.assertIn("Layered Executive and Technical Reporting", release_md)
        self.assertIn("Layered Executive and Technical Reporting", release_html)

        plugin = json.loads(read(PLUGIN_JSON))
        self.assertEqual("1.7.0", plugin["version"])

        for path in [README_MD, README_HTML]:
            with self.subTest(document=path.name):
                content = read(path)
                self.assertIn("v1.7.0 - latest release", content)
                self.assertNotIn("release candidate", content)
                self.assertNotIn("published latest remains v1.3.0", content)

        agents = read(AGENTS_MD)
        self.assertIn("- **v1.7.0** — Layered Executive and Technical Reporting", agents)
        self.assertIn("- **v1.6.0** — Single Managed Edge Gmail Broker", agents)
        self.assertIn("- **v1.5.0** — Executive Report Readability Redesign", agents)
        self.assertNotIn("Target release (not yet published)", agents)

    def test_distributable_docs_have_no_machine_specific_file_urls(self):
        docs = [README_MD, README_HTML]
        docs.extend((ROOT / "docs").glob("*.md"))
        docs.extend((ROOT / "docs").glob("*.html"))
        for path in docs:
            with self.subTest(document=path.name):
                self.assertNotRegex(read(path), r"file:///([a-zA-Z]:|/)")

    def test_tdd_html_includes_contract_regression_matrix(self):
        tdd_html = read(TDD_HTML)
        for marker in [
            "Verification &amp; Validation Framework",
            "Contract Regression Matrix",
            "closed/resolved",
            "zero evidence",
        ]:
            self.assertIn(marker, tdd_html)

    def test_tdd_uses_actual_gmail_tool_name(self):
        for path in [TDD_MD, TDD_HTML]:
            content = read(path)
            with self.subTest(document=path.name):
                self.assertIn("gmail_read(", content)
                self.assertNotIn("gmail_read_thread(", content)

    def test_apps_script_uses_evidence_appendix_without_generated_judgment_sections(self):
        code = read(APPS_SCRIPT)
        for prohibited in [
            "risk_flags",
            "recommended_actions",
            "Risk Flags",
            "Recommended Manager Action",
            "Risk Flags Count",
        ]:
            self.assertNotIn(prohibited, code)
        for required in [
            "data.evidence",
            "Appendix A — Evidence Register",
            '"Ref", "Date", "Source", "Verbatim evidence / data", "Supports"',
            "sheet.deleteColumn(7)",
        ]:
            self.assertIn(required, code)

    def test_apps_script_is_optional_and_not_in_active_release(self):
        self.assertTrue(APPS_SCRIPT.exists())
        manifest = read(RELEASE_MANIFEST)
        self.assertNotIn("tools/appsscript/Code.gs", manifest)
        self.assertNotIn("examples/optional-appsscript/Code.gs", manifest)
        optional_source = read(APPS_SCRIPT)
        self.assertIn("not deployed by setup_env.ps1", optional_source)
        self.assertIn("not part of the active", optional_source)

    def test_regression_matrix_covers_required_scenarios(self):
        scenarios = json.loads(read(SCENARIOS))
        ids = {scenario["id"] for scenario in scenarios}
        required = {
            "closed_resolved_old_record",
            "single_issue_with_evidence",
            "multi_problem_case",
            "gmail_no_results",
            "status_pings_only",
            "chronological_output_order",
            "executive_summary_layering",
            "executive_technical_deduplication",
            "adm_technical_depth_without_duplicate_sections",
            "adm_sparse_evidence",
            "preventive_next_checkpoint",
            "lab_success_not_production_confirmed",
            "required_tool_missing",
            "conflicting_sources",
            "zero_case_evidence",
            "appendix_reverse_mapping",
            "all_case_notes_before_gmail",
            "multipage_gmail_threads",
            "every_message_in_thread",
            "incomplete_context_blocks_review",
            "complete_zero_gmail_results",
            "token_and_cursor_loops_block_review",
            "disappearing_thread_blocks_review",
            "snapshot_after_messages_excluded",
            "attachment_metadata_out_of_scope_content",
        }
        self.assertGreaterEqual(len(scenarios), 7)
        self.assertTrue(required.issubset(ids))
        for scenario in scenarios:
            self.assertTrue(scenario["input"].strip())
            self.assertTrue(scenario["expected"].strip())
            markers = scenario.get("contract_markers", [])
            self.assertTrue(markers)
            for marker in markers:
                with self.subTest(scenario=scenario["id"], marker=marker):
                    self.assertIn(marker, self.skill)


if __name__ == "__main__":
    unittest.main()
