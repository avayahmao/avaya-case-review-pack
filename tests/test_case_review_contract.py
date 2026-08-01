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
SCENARIOS = ROOT / "tests/case_review_scenarios.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


class CaseReviewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = read(SKILL)
        cls.contract_docs = {
            "manager_md": read(MANAGER_MD),
            "manager_html": read(MANAGER_HTML),
            "tdd_md": read(TDD_MD),
            "tdd_html": read(TDD_HTML),
        }

    def test_dynamic_evidence_gate_is_explicit(self):
        required = [
            "Evidence 1..N",
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

    def test_single_action_source_and_conditional_schema(self):
        self.assertIn("All action items must live exclusively", self.skill)
        self.assertIn("Choose exactly one structure", self.skill)
        self.assertNotIn("### [Structure A:", self.skill)
        self.assertNotIn("### [Structure B:", self.skill)

    def test_current_contract_docs_match_skill(self):
        required = [
            "Evidence 1..N",
            "Case record freshness",
            "Last substantive progress age",
            "Production Outcome Confirmed",
            "Targeted Recommendations",
        ]
        prohibited = [
            "linked numbered `Action 1`",
            "Additional Datapoints & Customer Experience Metrics",
        ]
        for name, content in self.contract_docs.items():
            with self.subTest(document=name):
                for marker in required:
                    self.assertIn(marker, content)
                for marker in prohibited:
                    self.assertNotIn(marker, content)

    def test_release_metadata_targets_v1_4_0(self):
        release_md = read(RELEASE_MD)
        release_html = read(RELEASE_HTML)
        self.assertIn("[v1.4.0]", release_md)
        self.assertIn("v1.4.0", release_html)
        self.assertNotIn("[Unreleased]", release_md)
        self.assertNotIn(">Unreleased<", release_html)

        plugin = json.loads(read(PLUGIN_JSON))
        self.assertEqual("1.4.0", plugin["version"])

        for path in [README_MD, README_HTML]:
            with self.subTest(document=path.name):
                content = read(path)
                self.assertIn("v1.4.0 - latest release", content)
                self.assertNotIn("release candidate", content)
                self.assertNotIn("published latest remains v1.3.0", content)

        agents = read(AGENTS_MD)
        self.assertIn("- **v1.4.0** — Evidence-Grounded Workflow Hardening", agents)
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
