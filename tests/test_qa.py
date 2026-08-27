import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA_PATH = ROOT / "plugins/avaya-case-review/skills/case-review/scripts/qa.py"
SPEC = importlib.util.spec_from_file_location("qa", QA_PATH)
qa = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(qa)


SAMPLE_MARKDOWN = """| Name | Manager | Case ID | Product | Diagnostic & Solution (0-5） | Service & Communication（0-3） | Plus（0-5） | score | comments |
|---|---|---|---|---:|---:|---:|---:|---|
| shengj | qqu | 1-AX4DV2U | | 4 | 3 | 0 | 7 | Diagnostic & Solution -1: Analysis did not fully address the customer concern. |
| huang191 | yangwang | 1-23763930272 | | 5 | 3 | 3 | 11 | Plus +1: Customer pressure; Plus +1: cross-product cooperation; Plus +1: exceptional ownership. |
"""


class QATests(unittest.TestCase):
    def test_markdown_input_normalizes_full_width_headers_and_calculates_score(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qa.md"
            path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
            entries = qa.load_entries(path)
        self.assertEqual(2, len(entries))
        self.assertEqual(7, entries[0]["score"])
        self.assertEqual("", entries[0]["product"])
        self.assertEqual(11, entries[1]["score"])

    def test_score_entry_returns_a_normalized_entry(self):
        entry = qa.score_entry(
            name="guany",
            manager="hmao",
            case_id="1-AVWAH9Z",
            diagnostic_solution=5,
            service_communication=3,
            plus=1,
            comments="Plus +1: Reproduced the issue in the lab and identified a code defect.",
        )
        self.assertEqual(9, entry["score"])
        self.assertEqual("1-AVWAH9Z", entry["case_id"])

    def test_conflicting_supplied_score_is_rejected(self):
        with self.assertRaisesRegex(qa.QAError, "does not equal"):
            qa.normalize_entry(
                {
                    "Name": "agent",
                    "Manager": "manager",
                    "Case ID": "INC1234567",
                    "Diagnostic & Solution": "5",
                    "Service & Communication": "3",
                    "Plus": "0",
                    "score": "9",
                }
            )

    def test_dimension_bounds_are_enforced(self):
        with self.assertRaisesRegex(qa.QAError, "Diagnostic & Solution"):
            qa.normalize_entry(
                {
                    "Name": "agent",
                    "Manager": "manager",
                    "Case ID": "INC1234567",
                    "Diagnostic & Solution": 6,
                    "Service & Communication": 3,
                    "Plus": 0,
                }
            )

    def test_comment_is_required_for_each_nonstandard_score_condition(self):
        cases = (
            (4, 3, 0, "Diagnostic & Solution deduction"),
            (5, 2, 0, "Service & Communication deduction"),
            (5, 3, 1, "Plus award"),
        )
        for diagnostic, service, plus, expected in cases:
            with self.subTest(diagnostic=diagnostic, service=service, plus=plus):
                with self.assertRaisesRegex(qa.QAError, expected):
                    qa.score_entry(
                        name="agent",
                        manager="manager",
                        case_id="INC1234567",
                        diagnostic_solution=diagnostic,
                        service_communication=service,
                        plus=plus,
                    )

    def test_comment_is_optional_for_standard_full_score_without_plus(self):
        entry = qa.score_entry(
            name="agent",
            manager="manager",
            case_id="INC1234567",
            diagnostic_solution=5,
            service_communication=3,
            plus=0,
        )
        self.assertEqual("", entry["comments"])

    def test_comment_requires_exact_signed_notation(self):
        with self.assertRaisesRegex(qa.QAError, "diagnostic & solution -1"):
            qa.score_entry(
                name="agent",
                manager="manager",
                case_id="INC1234567",
                diagnostic_solution=4,
                service_communication=3,
                plus=0,
                comments="Analysis was incomplete.",
            )

    def test_technical_plus_allocations_must_sum_to_score(self):
        with self.assertRaisesRegex(qa.QAError, "must sum to the Plus score"):
            qa.score_entry(
                name="agent",
                manager="manager",
                case_id="INC1234567",
                diagnostic_solution=5,
                service_communication=3,
                plus=2,
                comments="Plus +1: Cross-team coordination.",
            )

    def test_outstanding_item_can_receive_two_points(self):
        entry = qa.score_entry(
            name="agent",
            manager="manager",
            case_id="INC1234567",
            diagnostic_solution=5,
            service_communication=3,
            plus=2,
            comments="Plus +2: Customer Pressure & Ownership — exceptional end-to-end P1 recovery.",
        )
        self.assertEqual(2, entry["plus"])

    def test_single_item_cannot_allocate_more_than_three_points(self):
        with self.assertRaisesRegex(qa.QAError, r"must use \+1, \+2, or \+3"):
            qa.score_entry(
                name="agent",
                manager="manager",
                case_id="INC1234567",
                diagnostic_solution=5,
                service_communication=3,
                plus=4,
                comments="Plus +4: Customer Pressure & Ownership — exceptional recovery.",
            )

    def test_summary_groups_engineers_and_managers(self):
        entries = qa.parse_text(SAMPLE_MARKDOWN)
        normalized = [qa.normalize_entry(item, index) for index, item in enumerate(entries, 1)]
        summary = qa.summarize(normalized)
        self.assertEqual(2, summary["reviews"])
        self.assertEqual(9.0, summary["average_score"])
        self.assertEqual(["huang191", "shengj"], [item["name"] for item in summary["by_name"]])
        self.assertEqual([1, 1], [item["reviews"] for item in summary["by_manager"]])

    def test_rendered_report_contains_complete_entries_and_summary(self):
        entries = [qa.normalize_entry(item, index) for index, item in enumerate(qa.parse_text(SAMPLE_MARKDOWN), 1)]
        report = qa.render_report(entries)
        self.assertIn("# Case Review QA Report", report)
        self.assertIn("## By Engineer", report)
        self.assertIn("## By Manager", report)
        self.assertIn("| shengj | qqu | 1-AX4DV2U | not stated | 4 | 3 | 0 | 7 | Diagnostic & Solution -1: Analysis did not fully address the customer concern. |", report)

    def test_json_input_accepts_entries_envelope(self):
        data = {"entries": [
            {"name": "agent", "manager": "manager", "case_id": "INC1234567",
             "diagnostic_solution": 5, "service_communication": 2, "plus": 1,
             "comments": "Service & Communication -1: Communication was delayed. Plus +1: Cross-team recovery support."}
        ]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qa.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            entries = qa.load_entries(path)
        self.assertEqual(8, entries[0]["score"])


if __name__ == "__main__":
    unittest.main()
