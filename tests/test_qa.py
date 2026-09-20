import csv
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA_PATH = ROOT / "plugins/avaya-case-review/skills/case-review/scripts/qa.py"
QA_SKILL_PATH = ROOT / "plugins/avaya-case-review/skills/qa/SKILL.md"
SPEC = importlib.util.spec_from_file_location("qa", QA_PATH)
qa = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(qa)


SAMPLE_MARKDOWN = """| Name | Manager | Case ID | Product | Auditor | Reviewability | Reviewability Reason | Diagnostic & Solution (0-5） | Service & Communication（0-3） | Plus（0-5） | score | Problem | efforts | comments |
|---|---|---|---|---|---|---|---:|---:|---:|---:|---|---|---|
| shengj | qqu | 1-AX4DV2U | | hmao | Reviewable | | 4 | 3 | 0 | 7 | CPU usage is high | Analyzed the monitor logs and proposed corrective action. | Diagnostic & Solution -1: analysis did not fully address the customer concern. |
| huang191 | yangwang | 1-23763930272 | | hmao | Reviewable | | 5 | 3 | 3 | 11 | Calls fail across integrated products | Reproduced the issue and coordinated the recovery. | Plus +1: Code Defect Discovery — reproduced the defect; Plus +1: Cross-Product Integration — traced the cross-system path; Plus +1: Customer Pressure & Ownership — led recovery under pressure. |
"""


def make_tsv(rows):
    output = StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue()


class QATests(unittest.TestCase):
    def scored_entry(self, **overrides):
        values = {
            "name": "agent",
            "manager": "manager",
            "case_id": "INC1234567",
            "diagnostic_solution": 5,
            "service_communication": 3,
            "plus": 0,
            "auditor": "auditor",
            "problem": "Customer cannot complete the requested operation.",
            "efforts": "Engineer analyzed the evidence and supplied the solution.",
        }
        values.update(overrides)
        return qa.score_entry(**values)

    def test_markdown_input_normalizes_full_width_headers_and_preserves_text_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qa.md"
            path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
            entries = qa.load_entries(path)
        self.assertEqual(2, len(entries))
        self.assertEqual(7, entries[0]["score"])
        self.assertEqual("", entries[0]["product"])
        self.assertEqual("hmao", entries[0]["auditor"])
        self.assertEqual("CPU usage is high", entries[0]["problem"])
        self.assertIn("monitor logs", entries[0]["efforts"])
        self.assertEqual(11, entries[1]["score"])

    def test_score_entry_returns_all_normalized_fields_and_defaults_reviewable(self):
        entry = self.scored_entry(
            name="guany",
            manager="hmao",
            case_id="1-AVWAH9Z",
            product="AES",
            diagnostic_solution=5,
            service_communication=3,
            plus=1,
            comments="Plus +1: Code Defect Discovery — reproduced the issue in the lab.",
        )
        self.assertEqual(9, entry["score"])
        self.assertEqual("1-AVWAH9Z", entry["case_id"])
        self.assertEqual("Reviewable", entry["reviewability"])
        self.assertEqual("auditor", entry["auditor"])
        self.assertIn("Customer cannot", entry["problem"])
        self.assertIn("supplied the solution", entry["efforts"])

    def test_source_logins_must_be_lowercase_without_silent_conversion(self):
        for field, value in (
            ("name", "Agent"),
            ("manager", "MANAGER"),
            ("manager", "qingbo qu"),
            ("auditor", "Auditor"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(qa.QAError, rf"{field} must be a lowercase source login"):
                    self.scored_entry(**{field: value})
        self.assertEqual("unknown", self.scored_entry(auditor="unknown")["auditor"])
        self.assertEqual("", self.scored_entry(auditor="")["auditor"])

    def test_reviewable_rows_require_problem_and_efforts(self):
        with self.assertRaisesRegex(qa.QAError, r"problem must be non-empty"):
            self.scored_entry(problem="")
        with self.assertRaisesRegex(qa.QAError, r"efforts must be non-empty"):
            self.scored_entry(efforts="")

    def test_reviewability_reason_must_be_blank_for_reviewable_rows(self):
        with self.assertRaisesRegex(qa.QAError, "must be blank"):
            self.scored_entry(reviewability_reason="Not needed for a scored row")

    def test_conflicting_supplied_score_is_rejected(self):
        raw = {
            "Name": "agent",
            "Manager": "manager",
            "Case ID": "INC1234567",
            "Diagnostic & Solution": "5",
            "Service & Communication": "3",
            "Plus": "0",
            "score": "9",
            "Problem": "Customer issue",
            "efforts": "Analyzed and resolved.",
        }
        with self.assertRaisesRegex(qa.QAError, "does not equal"):
            qa.normalize_entry(raw)

    def test_dimension_bounds_are_enforced(self):
        with self.assertRaisesRegex(qa.QAError, "Diagnostic & Solution"):
            self.scored_entry(diagnostic_solution=6)

    def test_comment_is_required_for_each_nonstandard_score_condition(self):
        cases = (
            (4, 3, 0, "Diagnostic & Solution deduction"),
            (5, 2, 0, "Service & Communication deduction"),
            (5, 3, 1, "Plus award"),
        )
        for diagnostic, service, plus, expected in cases:
            with self.subTest(diagnostic=diagnostic, service=service, plus=plus):
                with self.assertRaisesRegex(qa.QAError, expected):
                    self.scored_entry(
                        diagnostic_solution=diagnostic,
                        service_communication=service,
                        plus=plus,
                    )

    def test_comment_is_optional_for_standard_full_score_without_plus(self):
        entry = self.scored_entry()
        self.assertEqual("", entry["comments"])

    def test_comment_requires_exact_signed_notation(self):
        with self.assertRaisesRegex(qa.QAError, "Diagnostic & Solution -1"):
            self.scored_entry(
                diagnostic_solution=4,
                comments="Analysis was incomplete.",
            )

    def test_natural_first_comment_accepts_parenthetical_signed_notation(self):
        entry = self.scored_entry(
            diagnostic_solution=4,
            comments=(
                "Service recovered, but the cause remains unknown. "
                "(Diagnostic & Solution -1: cause remains unknown)"
            ),
        )
        self.assertEqual(4, entry["diagnostic_solution"])
        self.assertEqual(7, entry["score"])

    def test_wrong_deduction_magnitude_is_rejected(self):
        with self.assertRaisesRegex(qa.QAError, "deduction must be -1"):
            self.scored_entry(
                diagnostic_solution=4,
                comments="Diagnostic & Solution -2: analysis was incomplete.",
            )

    def test_signed_notation_rejects_spaced_signs_and_empty_reasons(self):
        cases = (
            (
                {"diagnostic_solution": 4, "comments": "Diagnostic & Solution - 1: cause remains unknown"},
                "exact 'Diagnostic & Solution -N:' notation",
            ),
            (
                {"diagnostic_solution": 4, "comments": "Diagnostic & Solution -1:"},
                "must include a non-empty reason",
            ),
            (
                {"plus": 1, "comments": "Plus + 1: Scope Extension — resolved an extra issue"},
                r"exact 'Plus \+N:' notation",
            ),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(qa.QAError, expected):
                    self.scored_entry(**overrides)

    def test_deduction_tokens_are_rejected_for_full_dimensions(self):
        comments = (
            "Diagnostic & Solution -1: unsupported deduction.",
            "Service & Communication -1: unsupported deduction.",
        )
        for comment in comments:
            with self.subTest(comment=comment):
                with self.assertRaisesRegex(qa.QAError, "must not include"):
                    self.scored_entry(comments=comment)

    def test_technical_plus_allocations_must_sum_to_score(self):
        with self.assertRaisesRegex(qa.QAError, "must sum to the Plus score"):
            self.scored_entry(
                plus=2,
                comments="Plus +1: Cross-Product Integration — coordinated across systems.",
            )

    def test_technical_plus_requires_a_canonical_item_name(self):
        with self.assertRaisesRegex(qa.QAError, "canonical item"):
            self.scored_entry(
                plus=1,
                comments="Plus +1: Product Knowledge — knew how the feature worked.",
            )

    def test_technical_plus_requires_an_evidenced_non_vague_reason(self):
        for comment in (
            "Plus +1: Scope Extension",
            "Plus +1: Scope Extension — solved quickly",
        ):
            with self.subTest(comment=comment):
                with self.assertRaisesRegex(qa.QAError, "reason|evidence or impact"):
                    self.scored_entry(plus=1, comments=comment)

    def test_plus_allocation_is_rejected_when_plus_is_zero(self):
        with self.assertRaisesRegex(qa.QAError, "when Plus is 0"):
            self.scored_entry(
                comments="Plus +1: Code Defect Discovery — unsupported numeric award.",
            )

    def test_outstanding_item_can_receive_two_points(self):
        entry = self.scored_entry(
            plus=2,
            comments=(
                "Plus +2: Customer Pressure & Ownership — "
                "led exceptional end-to-end P1 recovery."
            ),
        )
        self.assertEqual(2, entry["plus"])

    def test_single_item_cannot_allocate_more_than_three_points(self):
        with self.assertRaisesRegex(qa.QAError, r"must use \+1, \+2, or \+3"):
            self.scored_entry(
                plus=4,
                comments="Plus +4: Customer Pressure & Ownership — exceptional recovery.",
            )

    def test_not_reviewable_variants_normalize_to_explicit_unscored_rows(self):
        for value in ("Not Reviewable", "not-reviewable", "N/A", "NA", "unscored"):
            with self.subTest(value=value):
                entry = qa.normalize_entry(
                    {
                        "Name": "agent",
                        "Manager": "manager",
                        "Case ID": "INC1234567",
                        "Auditor": "",
                        "Reviewability": value,
                        "Reviewability Reason": "Administrative standby request.",
                    }
                )
                self.assertEqual("Not Reviewable", entry["reviewability"])
                self.assertIsNone(entry["diagnostic_solution"])
                self.assertIsNone(entry["service_communication"])
                self.assertIsNone(entry["plus"])
                self.assertIsNone(entry["score"])

    def test_not_reviewable_rows_require_reason_and_blank_scores(self):
        base = {
            "Name": "agent",
            "Manager": "manager",
            "Case ID": "INC1234567",
            "Reviewability": "Not Reviewable",
        }
        with self.assertRaisesRegex(qa.QAError, "reviewability_reason must be non-empty"):
            qa.normalize_entry(base)
        with self.assertRaisesRegex(qa.QAError, "do not use 0 for an unscored row"):
            qa.normalize_entry({**base, "Reviewability Reason": "No technical work", "score": 0})
        with self.assertRaisesRegex(qa.QAError, "must all be blank"):
            qa.normalize_entry(
                {
                    **base,
                    "Reviewability Reason": "No technical work",
                    "Diagnostic & Solution": 0,
                }
            )

    def test_reviewable_rows_reject_mixed_or_score_only_dimensions(self):
        common = {
            "Name": "agent",
            "Manager": "manager",
            "Case ID": "INC1234567",
            "Problem": "Customer issue",
            "efforts": "Engineer effort",
        }
        with self.assertRaisesRegex(qa.QAError, "mixes blank and populated"):
            qa.normalize_entry({**common, "Diagnostic & Solution": 5, "Plus": 0})
        with self.assertRaisesRegex(qa.QAError, "score cannot substitute"):
            qa.normalize_entry({**common, "score": 0})

    def test_zero_score_is_valid_when_all_dimensions_are_explicitly_scored(self):
        entry = self.scored_entry(
            diagnostic_solution=0,
            service_communication=0,
            plus=0,
            comments=(
                "Diagnostic & Solution -5: no technical contribution; "
                "Service & Communication -3: no meaningful communication."
            ),
        )
        self.assertEqual(0, entry["score"])

    def test_headered_tsv_supports_quoted_multiline_fields(self):
        rows = [
            qa.CURRENT_COLUMNS,
            (
                "agent", "manager", "INC1234567", "AES", "auditor", "Reviewable", "",
                5, 3, 0, 8, "Customer issue", "Checked logs.\nValidated the fix.", "",
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qa.txt"
            path.write_text(make_tsv(rows), encoding="utf-8")
            entries = qa.load_entries(path)
        self.assertEqual("Checked logs.\nValidated the fix.", entries[0]["efforts"])
        self.assertEqual("Reviewable", entries[0]["reviewability"])

    def test_headerless_legacy_and_current_tsv_schemas_are_supported(self):
        legacy = [[
            "agent", "manager", "INC1000001", "AES", "auditor", 5, 3, 0, 8,
            "Customer issue", "Engineer resolved it", "",
        ]]
        current = [[
            "agent", "manager", "INC1000002", "AES", "", "N/A", "Duplicate ticket",
            "", "", "", "", "", "", "",
        ]]
        legacy_entry = qa.normalize_entry(qa.parse_text(make_tsv(legacy), ".txt")[0])
        current_entry = qa.normalize_entry(qa.parse_text(make_tsv(current), ".tsv")[0])
        self.assertEqual("Reviewable", legacy_entry["reviewability"])
        self.assertEqual(8, legacy_entry["score"])
        self.assertEqual("Not Reviewable", current_entry["reviewability"])
        self.assertIsNone(current_entry["score"])

    def test_malformed_tsv_row_length_has_actionable_error(self):
        text = make_tsv([qa.CURRENT_COLUMNS, ["agent", "manager", "INC1234567"]])
        with self.assertRaisesRegex(qa.QAError, "canonical header.*quote fields"):
            qa.parse_text(text, ".txt")

    def test_headerless_tsv_requires_a_known_positional_schema(self):
        with self.assertRaisesRegex(qa.QAError, "12-column legacy schema or 14-column current schema"):
            qa.parse_text("agent\tmanager\tINC1234567", ".txt")

    def test_json_input_accepts_rows_envelope(self):
        data = {
            "rows": [
                {
                    "name": "agent",
                    "manager": "manager",
                    "case_id": "INC1234567",
                    "diagnostic_solution": 5,
                    "service_communication": 2,
                    "plus": 1,
                    "problem": "Customer issue",
                    "efforts": "Engineer analyzed and coordinated recovery.",
                    "comments": (
                        "Service & Communication -1: communication was delayed; "
                        "Plus +1: Cross-Product Integration — coordinated recovery."
                    ),
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "qa.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            entries = qa.load_entries(path)
        self.assertEqual(8, entries[0]["score"])

    def test_summary_counts_rows_and_excludes_unscored_rows_from_averages(self):
        entries = [
            qa.normalize_entry(item, index)
            for index, item in enumerate(qa.parse_text(SAMPLE_MARKDOWN), 1)
        ]
        entries.append(
            qa.normalize_entry(
                {
                    "Name": "shengj",
                    "Manager": "qqu",
                    "Case ID": "INC1000003",
                    "Reviewability": "Not Reviewable",
                    "Reviewability Reason": "Duplicate ticket",
                },
                3,
            )
        )
        summary = qa.summarize(entries)
        self.assertEqual(3, summary["total_rows"])
        self.assertEqual(2, summary["scored_reviews"])
        self.assertEqual(1, summary["not_reviewable_rows"])
        self.assertEqual(9.0, summary["average_score"])
        self.assertEqual(7, summary["minimum_score"])
        self.assertEqual(11, summary["maximum_score"])
        self.assertEqual(["huang191", "shengj"], [item["name"] for item in summary["by_name"]])

    def test_all_unscored_summary_and_report_are_safe(self):
        entry = qa.normalize_entry(
            {
                "Name": "agent",
                "Manager": "manager",
                "Case ID": "INC1234567",
                "Reviewability": "unscored",
                "Reviewability Reason": "No attributable technical work",
            }
        )
        summary = qa.summarize([entry])
        self.assertEqual(0, summary["scored_reviews"])
        self.assertIsNone(summary["average_score"])
        self.assertIsNone(summary["minimum_score"])
        self.assertIsNone(summary["maximum_score"])
        report = qa.render_report([entry])
        self.assertIn("| Average score | not available |", report)
        self.assertIn("| Minimum score | not available |", report)
        self.assertIn("| agent | manager | 1 | 0 | 1 | not available |", report)

    def test_rendered_report_contains_exact_full_schema_and_unscored_blanks(self):
        entries = [
            qa.normalize_entry(item, index)
            for index, item in enumerate(qa.parse_text(SAMPLE_MARKDOWN), 1)
        ]
        entries.append(
            qa.normalize_entry(
                {
                    "Name": "agent",
                    "Manager": "manager",
                    "Case ID": "INC1000004",
                    "Reviewability": "Not Reviewable",
                    "Reviewability Reason": "Standby request",
                },
                3,
            )
        )
        report = qa.render_report(entries)
        expected_header = (
            "| Name | Manager | Case ID | Product | Auditor | Reviewability | "
            "Reviewability Reason | Diagnostic & Solution | Service & Communication | "
            "Plus | Score | Problem | efforts | comments |"
        )
        self.assertIn(expected_header, report)
        self.assertIn("**Total rows:** 3", report)
        self.assertIn("**Scored reviews:** 2", report)
        self.assertIn("**Not-reviewable rows:** 1", report)
        self.assertIn(
            "| agent | manager | INC1000004 | not stated |  | Not Reviewable | Standby request |  |  |  |  |  |  |  |",
            report,
        )

    def test_cli_score_accepts_new_text_fields(self):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = qa.main(
                [
                    "score",
                    "--name", "agent",
                    "--manager", "manager",
                    "--case-id", "INC1234567",
                    "--auditor", "auditor",
                    "--diagnostic-solution", "5",
                    "--service-communication", "3",
                    "--plus", "0",
                    "--problem", "Customer issue",
                    "--efforts", "Engineer resolved it",
                ]
            )
        self.assertEqual(0, exit_code)
        rendered = json.loads(output.getvalue())
        self.assertEqual("auditor", rendered["auditor"])
        self.assertEqual("Customer issue", rendered["problem"])
        self.assertEqual("Engineer resolved it", rendered["efforts"])

    def test_qa_skill_requires_example_led_simple_english_generation(self):
        content = QA_SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("## Example-led calibration", content)
        self.assertIn("New SIP trunk returned 403", content)
        self.assertIn("Do not raise a score merely to match another auditor's mean", content)
        self.assertIn("Do not emit field labels such as `Reviewed:`", content)
        self.assertIn("state the natural judgment first", content)
        self.assertNotIn("Write `Problem` as `<case type> —", content)
        self.assertNotIn("Use consistent signed notation at the start", content)


if __name__ == "__main__":
    unittest.main()
