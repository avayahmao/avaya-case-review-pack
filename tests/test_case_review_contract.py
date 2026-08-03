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
PLUGIN_JSON = ROOT / "plugins/avaya-case-review/plugin.json"
AGENTS_MD = ROOT / "AGENTS.md"
APPS_SCRIPT = ROOT / "tools/appsscript/Code.gs"
SCENARIOS = ROOT / "tests/case_review_scenarios.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def extract_report_template(skill: str) -> str:
    match = re.search(r"```markdown\n(.*?)\n```", skill, re.DOTALL)
    if not match:
        raise AssertionError("Rendered report template not found")
    return match.group(1)


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
            "output exactly `不知道`",
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
        self.assertIn("Choose exactly one structure", self.skill)
        self.assertIn("must never generate a new recommendation", self.skill)
        self.assertNotIn("All action items must live exclusively", self.skill)
        self.assertNotIn("### [Structure A:", self.skill)
        self.assertNotIn("### [Structure B:", self.skill)

    def test_appendix_is_last_and_body_has_no_evidence_markers(self):
        template = extract_report_template(self.skill)
        self.assertIn("## Appendix A — Evidence Register", template)
        appendix = template.index("## Appendix A — Evidence Register")
        order = [
            template.index("## Verdict"),
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
        self.assertTrue(template.rstrip().endswith("<Evidence rows E1..EN>"))

    def test_manager_judgment_sections_are_absent(self):
        template = extract_report_template(self.skill)
        self.assertNotIn("## Risk Flags", template)
        self.assertNotIn("## Targeted Recommendations", template)
        self.assertIn("must never generate a new recommendation", self.skill)

    def test_current_contract_docs_match_skill(self):
        required = [
            "Appendix A — Evidence Register",
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

    def test_regression_matrix_covers_required_scenarios(self):
        scenarios = json.loads(read(SCENARIOS))
        ids = {scenario["id"] for scenario in scenarios}
        required = {
            "closed_resolved_old_record",
            "single_issue_with_evidence",
            "multi_problem_case",
            "gmail_no_results",
            "status_pings_only",
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
