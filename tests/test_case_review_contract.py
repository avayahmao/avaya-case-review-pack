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
