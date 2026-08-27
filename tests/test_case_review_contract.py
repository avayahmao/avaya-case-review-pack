import html
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/avaya-case-review/skills/case-review/SKILL.md"
OUTPUT_MODES = ROOT / "plugins/avaya-case-review/skills/case-review/references/output-modes.md"
PRESENTER = ROOT / "plugins/avaya-case-review/skills/case-review/scripts/review_presenter.py"
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


def extract_release_v1_8_section(content: str, html_document: bool) -> str:
    if html_document:
        return extract_between(
            content,
            "<!-- VERSION 1.8.0 -->",
            "<!-- VERSION 1.7.0 -->",
        )
    return extract_between(content, "## [v1.8.0]", "## [v1.7.0]")


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
            "record_ids_planned == record_id_queries_completed == 1",
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
            "The bootstrap input for the primary Case ID query may be empty",
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

    def test_gmail_query_scope_uses_primary_case_id_only(self):
        retrieval = extract_between(
            self.skill,
            "### Complete Context Before Analysis",
            "### Step 4 - Analyze Only What the Evidence Supports",
        )
        gmail_capability = read(GMAIL_CAPABILITY_SKILL)

        for marker in [
            "primary raw Case ID only",
            "Related records remain case context only",
            "record_ids_planned == record_id_queries_completed == 1",
        ]:
            self.assertIn(marker, retrieval)
        self.assertIn("Do not query Case-note-derived or Gmail-discovered related IDs", gmail_capability)

        for forbidden in [
            "For every frozen record ID",
            "enumerate every Gmail thread for every frozen ID",
            "For each frozen primary or Case-note-derived record ID",
            "freeze the primary plus every supported related ID",
        ]:
            self.assertNotIn(forbidden, retrieval + gmail_capability)

    def test_snapshot_reflection_repeats_bootstrap_exception_and_reuse_rule(self):
        retrieval = extract_between(
            self.skill,
            "### Complete Context Before Analysis",
            "### Step 4 - Analyze Only What the Evidence Supports",
        )
        reflection = extract_between(
            self.skill,
            "### Step 6 - Reflection and Coverage Review",
            "### Step 7 - Build the Structured Review Snapshot",
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
            retrieval.index("bootstrap input for the primary Case ID query may be empty"),
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
            "every message in every primary-ID-matched Gmail thread",
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
            "repeated or regressing token",
            "missing `complete` field",
            "quota/timeout",
            "15-minute verification deadline",
            "multi-message thread",
            "cursor exhaustion",
            "hash/count checks",
            "Only then",
        ]
        offsets = [runbook.index(marker) for marker in ordered_markers]
        self.assertEqual(offsets, sorted(offsets))
        for marker in [
            "optional governance example",
            "primary raw Case ID",
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
            r"$McpCtl = Join-Path $env:USERPROFILE '.gemini\tools\gmail\gmail_brokerctl.py'",
            "python $McpCtl stop",
            "$stopExit = $LASTEXITCODE",
            "independent Gmail broker",
            "Test-BrokerLockFree",
            "Get-CimInstance Win32_Process",
            "edge_broker_profile",
            "state.json",
            "broker.lock",
            "ConvertFrom-Json",
            "Start-Sleep -Milliseconds 250",
            "15 seconds",
            "Rerun the prior package's installer",
        ]:
            self.assertIn(marker, runbook)

        rollback = extract_between(runbook, "## Rollback", "Keep the exhaustive Agent gate inactive")
        self._assert_rollback_safety_contract(rollback)

    def _assert_rollback_safety_contract(self, rollback: str) -> None:
        ordered_markers = [
            "python $McpCtl stop",
            "poll for at most 15 seconds",
            "Get-CimInstance Win32_Process",
            "$lockFree = Test-BrokerLockFree $LockFile",
            "if ($statePresent -or $stateProcess.Count -gt 0 -or $dedicatedProcesses.Count -gt 0 -or -not $lockFree)",
            "Rerun the prior package's installer",
        ]
        for marker in ordered_markers:
            self.assertIn(marker, rollback)
        offsets = [rollback.index(marker) for marker in ordered_markers]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("$stopExit = $LASTEXITCODE", rollback)
        self.assertIn("if ($stopExit -notin @(0, 20))", rollback)
        self.assertIn("Start-Sleep -Milliseconds 250", rollback)
        self.assertIn("while ((Get-Date).ToUniversalTime() -lt $deadline)", rollback)
        self.assertIn(
            "if (-not $statePresent -and $stateProcess.Count -eq 0 -and $dedicatedProcesses.Count -eq 0 -and $lockFree) { break }",
            rollback,
        )
        self.assertIn(
            "throw 'FAIL: broker state, PID, lock, or Managed Edge process remains active'",
            rollback,
        )
        self.assertIn("do not replace files until the check passes", rollback)
        self.assertNotIn("%USERPROFILE%", rollback)
        self.assertNotIn("gmail_brokerctl.py status", rollback)
        stop_command = rollback.index("python $McpCtl stop")
        rollback_after_stop = rollback[stop_command:]
        for forbidden_status_pattern in [
            r"(?im)^\s*(?:(?:python(?:\.exe)?|&)\s+)?['\"]?\$[A-Za-z_]\w*['\"]?\s+status\b",
            r"(?im)^\s*(?:python(?:\.exe)?|&)\s+[^`\r\n]*gmail_brokerctl\.py['\"]?\s+status\b",
        ]:
            self.assertNotRegex(rollback_after_stop, forbidden_status_pattern)

    def test_rollback_safety_contract_rejects_guard_or_order_mutations(self):
        runbook = read(GMAIL_CLOUD_BRIDGE_MD)
        rollback = extract_between(runbook, "## Rollback", "Keep the exhaustive Agent gate inactive")
        mutated_guard = rollback.replace(
            "if ($statePresent -or $stateProcess.Count -gt 0 -or $dedicatedProcesses.Count -gt 0 -or -not $lockFree) {\n       throw 'FAIL: broker state, PID, lock, or Managed Edge process remains active'\n   }",
            "",
            1,
        )
        with self.assertRaises(AssertionError):
            self._assert_rollback_safety_contract(mutated_guard)

        mutated_order = rollback.replace(
            "Get-CimInstance Win32_Process",
            "Rerun the prior package's installer\nGet-CimInstance Win32_Process",
            1,
        )
        with self.assertRaises(AssertionError):
            self._assert_rollback_safety_contract(mutated_order)

        mutated_variable_status = rollback.replace(
            "Get-CimInstance Win32_Process",
            "python $McpCtl status\n       Get-CimInstance Win32_Process",
            1,
        )
        with self.assertRaises(AssertionError):
            self._assert_rollback_safety_contract(mutated_variable_status)

        mutated_invocation_status = rollback.replace(
            "Get-CimInstance Win32_Process",
            "& $McpCtl status\n       Get-CimInstance Win32_Process",
            1,
        )
        with self.assertRaises(AssertionError):
            self._assert_rollback_safety_contract(mutated_invocation_status)

        mutated_quoted_python_status = rollback.replace(
            "Get-CimInstance Win32_Process",
            r'python "C:\Users\operator name\.gemini\tools\gmail\gmail_brokerctl.py" status'
            + "\n       Get-CimInstance Win32_Process",
            1,
        )
        with self.assertRaises(AssertionError):
            self._assert_rollback_safety_contract(mutated_quoted_python_status)

        mutated_quoted_invocation_status = rollback.replace(
            "Get-CimInstance Win32_Process",
            r'& "C:\Users\operator name\.gemini\tools\gmail\gmail_brokerctl.py" status'
            + "\n       Get-CimInstance Win32_Process",
            1,
        )
        with self.assertRaises(AssertionError):
            self._assert_rollback_safety_contract(mutated_quoted_invocation_status)

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
            "$verificationDeadline",
            "AddMinutes(15)",
            "Assert-VerificationDeadline",
            "seenPageTokens",
            "seenCursors",
            "repeated or regressing page token",
            "repeated or regressing cursor",
            "list response includes complete",
            "thread response includes complete",
            "-TimeoutSec 60",
            "timeout/quota/error",
            "do not activate local Agent SKILL",
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

    def test_cloud_bridge_verification_bounds_and_advances_each_pagination_chain(self):
        runbook = read(GMAIL_CLOUD_BRIDGE_MD)
        verification = extract_between(
            runbook,
            "## Sanitized verification examples",
            "## Collection contract",
        )
        self.assertLess(
            verification.index("$verificationDeadline"),
            verification.index("function Invoke-Bridge"),
        )
        self.assertLess(
            verification.index("$seenPageTokens = @{}"),
            verification.index("if ($pageToken)"),
        )
        self.assertLess(
            verification.index("$seenCursors = @{}"),
            verification.index("if ($nextCursor)"),
        )
        page_loop = verification.index("if ($pageToken)")
        next_page_call = verification.index("$page = Invoke-Bridge @{", page_loop)
        self.assertLess(
            verification.index("repeated or regressing page token", page_loop),
            next_page_call,
        )
        cursor_loop = verification.index("if ($nextCursor)")
        self.assertLess(
            verification.index("repeated or regressing cursor", cursor_loop),
            verification.index("$cursor = $nextCursor", cursor_loop),
        )
        for marker in [
            "deadline expiry",
            "quota",
            "timeout",
            "missing `complete`",
            "do not activate the local Agent SKILL",
        ]:
            self.assertIn(marker, runbook)

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

    def test_v1_8_release_notes_cover_cloud_bridge(self):
        release_md = extract_release_v1_8_section(read(RELEASE_MD), html_document=False)
        release_html = extract_release_v1_8_section(read(RELEASE_HTML), html_document=True)
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
                    f"v1.8.0 MD section missing claim: {claim}",
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

    def test_whole_case_storyline_resists_latest_message_bias(self):
        storyline = extract_between(
            self.skill,
            "### Whole-case storyline and problem lineage",
            "### Chronological output order",
        )
        for marker in [
            "original customer objective",
            "Blocking question or decision point",
            "Working hypotheses and actions",
            "Corrected finding",
            "Implemented action and primary outcome",
            "Secondary problems",
            "relationship to the primary problem",
            "Latest-message recency and verbosity",
            "current state",
        ]:
            self.assertIn(marker, storyline)

        structured = extract_template_section(
            self.skill,
            "### Structured Analysis Before Presentation",
            "### Step 5 - Enforce the Evidence Gate",
        )
        reflection = extract_template_section(
            self.skill,
            "### Step 6 - Reflection and Coverage Review",
            "### Step 7 - Build the Structured Review Snapshot",
        )
        for marker in ["problem lineage", "blockers", "working hypotheses", "secondary problems"]:
            self.assertIn(marker, structured)
        for marker in ["original objective", "blocker", "secondary issue"]:
            self.assertIn(marker, reflection)

    def test_rendered_date_time_content_is_ascending(self):
        for marker in [
            "Chronological output order",
            "ascending order (oldest first)",
            "undated entries after all dated entries",
            "Assign rendered `E1..EN` identifiers after this chronological sort",
            "oldest first",
            "milestones and timeline chronological",
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
        output_modes = read(OUTPUT_MODES)
        for marker in [
            "`standard`",
            "`compact`",
            "`follow-up`",
            "`technical`",
            "`flow`",
            "`full`",
            "Do not ask the user to choose a format",
            "Never use numeric confidence percentages",
        ]:
            self.assertIn(marker, output_modes)
        self.assertIn("Outputs must not generate risk scores", self.skill)
        self.assertNotIn("All action items must live exclusively", self.skill)

    def test_default_output_is_investigation_complete_not_an_executive_paragraph(self):
        output_modes = read(OUTPUT_MODES)
        standard = extract_between(output_modes, "### `standard`", "### `compact`")
        for marker in [
            "Case Card",
            "Investigation Progress flow",
            "Causal Assessment",
            "six key Technical Specification fields",
            "Timeline",
            "complete dynamic Evidence Register",
        ]:
            self.assertIn(marker, standard)
        self.assertNotIn("Write one natural-language paragraph of 6-8 sentences", self.skill)
        for marker in ("case_record.py present", "--markdown-only", "verify-final"):
            self.assertIn(marker, self.skill)

    def test_technical_mode_uses_fixed_proof_state_schema(self):
        output_modes = read(OUTPUT_MODES)
        technical = extract_between(output_modes, "### `technical`", "### `flow`")
        for marker in [
            "Field | Proof state | Value | Evidence basis",
            "Confirmed mechanism",
            "Suspected or unproven",
            "Verification",
            "Evidence gaps",
            "NOT COLLECTED",
            "NOT OBSERVED",
            "UNKNOWN",
            "NOT APPLICABLE",
        ]:
            self.assertIn(marker, technical)

    def test_milestone_count_follows_available_evidence(self):
        for marker in [
            "Milestones have no minimum count",
            "up to five evidence-supported substantive transitions",
            "without padding or repetition",
        ]:
            self.assertIn(marker, self.skill)
        self.assertNotIn("Three to five", self.skill)

    def test_adm_expands_structured_depth_without_duplicate_sections(self):
        adaptive_adm = extract_template_section(
            self.skill,
            "### Structured Analysis Before Presentation",
            "### Step 5 - Enforce the Evidence Gate",
        )
        for marker in [
            "ADM activates only when explicitly requested",
            "Details/Findings",
            "Problem Clarification",
            "Cause",
            "Solution",
            "structured problem lineage and Technical Specification",
            "do not generate a second ADM outline",
        ]:
            self.assertIn(marker, adaptive_adm)

    def test_adm_sparse_evidence_uses_gaps_without_invention(self):
        adaptive_adm = extract_template_section(
            self.skill,
            "### Structured Analysis Before Presentation",
            "### Step 5 - Enforce the Evidence Gate",
        )
        reflection = extract_template_section(
            self.skill,
            "### Step 6 - Reflection and Coverage Review",
            "### Step 7 - Build the Structured Review Snapshot",
        )
        for marker in [
            "explicit evidence gaps",
            "unsupported dimensions",
            "filler prose",
        ]:
            self.assertIn(marker, adaptive_adm)
        self.assertIn("preserve unsupported values", reflection)

    def test_preventive_next_checkpoint_is_commitment_not_control(self):
        for marker in [
            "Outputs must not generate risk scores",
            "Evidence-stated actions and checkpoints remain existing commitments",
            "never agent recommendations or implemented controls",
            "planned work is not an existing control",
        ]:
            self.assertIn(marker, self.skill)

    def test_standard_follow_up_render_evidence_and_full_keeps_appendix_last(self):
        output_modes = read(OUTPUT_MODES)
        for mode in ("compact", "technical", "flow"):
            section_start = output_modes.index(f"### `{mode}`")
            next_start = output_modes.find("### `", section_start + 5)
            section = output_modes[section_start : next_start if next_start >= 0 else None]
            self.assertNotIn("Appendix A — Evidence Register", section)
        for mode in ("standard", "follow-up"):
            section_start = output_modes.index(f"### `{mode}`")
            next_start = output_modes.find("### `", section_start + 5)
            section = output_modes[section_start : next_start if next_start >= 0 else None]
            self.assertIn("Evidence Register", section)
        full = extract_between(output_modes, "### `full`", "## Secondary Diagnostic Visual Selection")
        self.assertIn("Appendix A — Evidence Register", full)
        self.assertIn("final section of this mode only", full)

    def test_manager_judgment_sections_are_absent(self):
        output_modes = read(OUTPUT_MODES)
        self.assertNotIn("## Risk Flags", output_modes)
        self.assertNotIn("## Targeted Recommendations", output_modes)
        self.assertIn("must not generate risk scores", self.skill)

    def test_current_contract_docs_match_skill(self):
        required = [
            "Case Card",
            "Technical Specification",
            "Causal Assessment",
            "Timeline",
            "standard",
            "follow-up",
            "full",
            "Evidence Register",
            "Production Outcome Confirmed",
        ]
        prohibited = [
            "Risk Flags",
            "Targeted Recommendations",
            "linked numbered `Action 1`",
            "Additional Datapoints & Customer Experience Metrics",
            "6-8 sentence Executive Summary",
        ]
        for name, content in self.contract_docs.items():
            with self.subTest(document=name):
                for marker in required:
                    self.assertIn(marker, content)
                for marker in prohibited:
                    self.assertNotIn(marker, content)

    def test_contract_docs_describe_deterministic_output_modes(self):
        required = [
            "standard",
            "compact",
            "follow-up",
            "technical",
            "flow",
            "full",
            "structured",
            "secondary diagnostic visual",
        ]
        for name, content in self.contract_docs.items():
            with self.subTest(document=name):
                contract = normalize_contract_item(content).lower()
                for marker in required:
                    self.assertIn(marker.lower(), contract)
                self.assertNotIn("6-8 sentence executive summary", contract)

    def test_contract_docs_describe_whole_case_storyline(self):
        for name, content in self.contract_docs.items():
            with self.subTest(document=name):
                normalized = normalize_contract_item(content).lower()
                for marker in [
                    "whole-case storyline",
                    "primary problem",
                    "secondary problems",
                ]:
                    self.assertIn(marker, normalized)

        presentation = normalize_contract_item(read(PRESENTATION_HTML)).lower()
        for marker in [
            "whole-case storyline",
            "primary problem",
            "state transitions",
        ]:
            self.assertIn(marker, presentation)

        for path in [RELEASE_MD, RELEASE_HTML]:
            with self.subTest(document=path.name):
                content = normalize_contract_item(read(path))
                self.assertIn("Whole-Case Storyline and Problem Lineage", content)
                self.assertIn("recency or verbosity", content)

    def test_presentation_follows_deterministic_output_contract(self):
        output_modes = read(OUTPUT_MODES)
        presentation = read(PRESENTATION_HTML)
        validate_html_structure(presentation)
        presentation_lower = presentation.lower()

        for marker in [
            "`standard`",
            "`compact`",
            "`follow-up`",
            "`technical`",
            "`flow`",
            "`full`",
            "Secondary Diagnostic Visual Selection",
            "Structured Review Snapshot v2",
        ]:
            self.assertIn(marker, output_modes)

        for marker in [
            "Evidence-Grounded Technical Review",
            "Evidence-Grounded Technical Assessment",
            "Complete Context Before Analysis",
            "primary raw Case ID",
            "Incomplete collection blocks the review",
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
            "<h2>Deterministic Case Review Presentation Modes</h2>"
        )
        structure_end = presentation.index("<!-- SLIDE 11 -->", structure_start)
        structure = presentation[structure_start:structure_end]
        section_headings = [
            "1. standard",
            "2. compact",
            "3. follow-up",
            "4. technical",
            "5. flow + Adaptive Visual",
            "6. full",
        ]
        positions = []
        for heading in section_headings:
            marker = f"<h3>{heading}</h3>"
            self.assertEqual(1, structure.count(marker))
            positions.append(structure.index(marker))
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("6-8 Sentence Executive Summary", structure)
        self.assertNotIn("Technical &amp; Incident Assessment", structure)

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
                self.assertIn("Durable Case Follow-up and Approved Learning", content)

    def test_presentation_visibly_explains_exhaustive_context_gate(self):
        presentation = read(PRESENTATION_HTML)
        validate_html_structure(presentation)
        visible_text = normalize_contract_item(presentation)

        for marker in [
            "Complete Context Before Analysis",
            "Every Case note",
            "Every message in every primary-ID-matched Gmail thread",
            "Incomplete collection blocks the review",
            "Attachment payloads are excluded; filenames and MIME metadata may be recorded.",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, visible_text)
        self.assertNotIn("Attachments are excluded", visible_text)

        limited_collection = re.compile(
            r"(?:only\s+)?(?:key|relevant|prioriti[sz]ed)\s+"
            r"(?:Gmail\s+)?(?:messages|threads)"
            r"|(?:Gmail\s+)?(?:messages|threads)\s+(?:are\s+)?"
            r"(?:only\s+)?(?:key|relevant|prioriti[sz]ed)",
            re.IGNORECASE,
        )
        self.assertIsNone(limited_collection.search(visible_text))

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
                "#### Structured ReviewSnapshot v2 and Presentation Modes",
            ),
            "tdd_html": extract_template_section(
                tdd_html,
                html_heading,
                "<h4>Structured ReviewSnapshot v2 and Presentation Modes</h4>",
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

    def test_release_metadata_targets_v1_10_0(self):
        release_md = read(RELEASE_MD)
        release_html = read(RELEASE_HTML)
        self.assertIn("[v1.8.0]", release_md)
        self.assertIn("v1.8.0", release_html)
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

        self.assertIn("[v1.9.0]", release_md)
        self.assertIn("v1.9.0", release_html)
        self.assertIn("Codex and Antigravity Installation", release_md)
        self.assertIn("Codex and Antigravity Installation", release_html)
        self.assertIn("[v1.9.1]", release_md)
        self.assertIn("v1.9.1", release_html)
        self.assertIn("Large Gmail Thread Cursor Pagination", release_md)
        self.assertIn("Large Gmail Thread Cursor Pagination", release_html)
        self.assertIn("[v1.9.2]", release_md)
        self.assertIn("v1.9.2", release_html)
        self.assertIn("Primary Case ID-Only Gmail Collection", release_md)
        self.assertIn("Primary Case ID-Only Gmail Collection", release_html)
        self.assertIn("[v1.9.3]", release_md)
        self.assertIn("v1.9.3", release_html)
        self.assertIn("Whole-Case Storyline and Problem Lineage", release_md)
        self.assertIn("Whole-Case Storyline and Problem Lineage", release_html)
        self.assertIn("[v1.9.4]", release_md)
        self.assertIn("v1.9.4", release_html)
        self.assertIn("Cloud Bridge Pagination Speedup", release_md)
        self.assertIn("Cloud Bridge Pagination Speedup", release_html)
        self.assertIn("[v1.10.0]", release_md)
        self.assertIn("v1.10.0", release_html)
        self.assertIn("Investigation-Complete Reviews and Quality Audits", release_md)
        self.assertIn("Investigation-Complete Reviews and Quality Audits", release_html)
        plugin = json.loads(read(PLUGIN_JSON))
        self.assertEqual("1.10.0", plugin["version"])

        for path in [README_MD, README_HTML]:
            with self.subTest(document=path.name):
                content = read(path)
                self.assertIn("v1.10.0 - latest release", content)
                self.assertNotIn("release candidate", content)
                self.assertNotIn("published latest remains v1.3.0", content)

        agents = read(AGENTS_MD)
        self.assertIn("- **v1.7.0** — Layered Executive and Technical Reporting", agents)
        self.assertIn("- **v1.6.0** — Single Managed Edge Gmail Broker", agents)
        self.assertIn("- **v1.5.0** — Executive Report Readability Redesign", agents)
        self.assertIn("v1.8.0", agents)
        self.assertIn("v1.9.0", agents)
        self.assertIn("v1.9.1", agents)
        self.assertIn("v1.9.2", agents)
        self.assertIn("v1.9.3", agents)
        self.assertIn("v1.9.4", agents)
        self.assertIn("v1.10.0", agents)
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
            "standard_default_output",
            "technical_spec_proof_states",
            "whole_case_storyline_and_problem_lineage",
            "adm_technical_depth_without_duplicate_sections",
            "adm_sparse_evidence",
            "preventive_next_checkpoint",
            "delta_first_follow_up",
            "unchanged_follow_up_standard",
            "final_output_integrity",
            "adaptive_visual_selection",
            "explicit_full_mode",
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
