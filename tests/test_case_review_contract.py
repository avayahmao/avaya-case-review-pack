import html
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/avaya-case-review/skills/case-review/SKILL.md"
MANAGER_MD = ROOT / "docs/MANAGER_ONBOARDING_GUIDE.md"
MANAGER_HTML = ROOT / "docs/MANAGER_ONBOARDING_GUIDE.html"
TDD_MD = ROOT / "docs/TECHNICAL_DESIGN_DOCUMENT.md"
TDD_HTML = ROOT / "docs/TECHNICAL_DESIGN_DOCUMENT.html"
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
            "does not guarantee completeness or prevent outages",
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

    def test_tdd_contract_unconditionally_forbids_generated_recommendations(self):
        sections = {
            "tdd_md": extract_template_section(
                self.contract_docs["tdd_md"],
                "#### Evidence Processing Contract",
                "#### Vendor Escalation Handoff Matrix",
            ),
            "tdd_html": extract_template_section(
                self.contract_docs["tdd_html"],
                "<h4>Evidence Processing Contract</h4>",
                "<h4>Vendor Escalation Handoff Verification Rules</h4>",
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

    def test_release_metadata_targets_v1_6_0(self):
        release_md = read(RELEASE_MD)
        release_html = read(RELEASE_HTML)
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

        plugin = json.loads(read(PLUGIN_JSON))
        self.assertEqual("1.6.0", plugin["version"])

        for path in [README_MD, README_HTML]:
            with self.subTest(document=path.name):
                content = read(path)
                self.assertIn("v1.6.0 - latest release", content)
                self.assertNotIn("release candidate", content)
                self.assertNotIn("published latest remains v1.3.0", content)

        agents = read(AGENTS_MD)
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
