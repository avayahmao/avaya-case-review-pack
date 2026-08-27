import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "plugins/avaya-case-review/skills/case-review/scripts/alarm_audit.py"
SPEC = importlib.util.spec_from_file_location("alarm_audit", AUDIT_PATH)
alarm_audit = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(alarm_audit)


SAMPLE_MARKDOWN = """| Ticket ID | Name | Manager | Account Tier | Alarm | Check | Cause | Chronic | PLUS | Score | Comments |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|
| INC7480916 | lu122 | qqu | global support | MED-GTWY | 1 | 0 | 0 | 0 | 1 | alarm cleared upon access |
| INC7453910 | zhang301 | qqu | Premium | MED-GTWY | 1 | 1 | 0 | 1 | 3 | GW43 still unreachable; customer notified; Plus +1: Communication/Documentation - recovery documented |
| INC7431180 | jyan | qqu | PREMIUM | Heartbeat Failed | 0 | 0 | 0 | 0 | 0 | first meaningful check occurred two weeks later |
"""


class AlarmAuditTests(unittest.TestCase):
    def test_markdown_input_calculates_additive_scores(self):
        entries = [
            alarm_audit.normalize_entry(item, index)
            for index, item in enumerate(alarm_audit.parse_text(SAMPLE_MARKDOWN), 1)
        ]
        self.assertEqual([1, 3, 0], [item["score"] for item in entries])
        self.assertEqual("MED-GTWY", entries[0]["alarm"])

    def test_score_entry_returns_normalized_alarm_audit(self):
        entry = alarm_audit.score_entry(
            ticket_id="INC7482711",
            name="wang385",
            manager="qqu",
            account_tier="global support",
            alarm="Grafana Alert",
            check=1,
            cause=0,
            chronic=0,
            plus=0,
            comments="alarm cleared upon access in Grafana",
        )
        self.assertEqual(1, entry["score"])
        self.assertEqual("INC7482711", entry["ticket_id"])

    def test_conflicting_score_is_rejected(self):
        with self.assertRaisesRegex(alarm_audit.AlarmAuditError, "does not equal"):
            alarm_audit.normalize_entry({
                "Ticket ID": "INC1234567",
                "Name": "agent",
                "Manager": "manager",
                "Check": 1,
                "Cause": 0,
                "Chronic": 0,
                "PLUS": 0,
                "Score": 2,
                "Comments": "alarm cleared upon access",
            })

    def test_dimension_bounds_are_enforced(self):
        with self.assertRaisesRegex(alarm_audit.AlarmAuditError, "Check"):
            alarm_audit.score_entry(
                ticket_id="INC1234567",
                name="agent",
                manager="manager",
                check=2,
                cause=0,
                chronic=0,
                plus=0,
                comments="checked",
            )

    def test_comments_are_required(self):
        with self.assertRaisesRegex(alarm_audit.AlarmAuditError, "comments"):
            alarm_audit.score_entry(
                ticket_id="INC1234567",
                name="agent",
                manager="manager",
                check=1,
                cause=0,
                chronic=0,
                plus=0,
                comments="",
            )

    def test_each_plus_point_requires_a_plus_one_reason(self):
        with self.assertRaisesRegex(alarm_audit.AlarmAuditError, "once per PLUS point"):
            alarm_audit.score_entry(
                ticket_id="INC1234567",
                name="agent",
                manager="manager",
                check=1,
                cause=1,
                chronic=0,
                plus=2,
                comments="Plus +1: Prevention - durable fix",
            )

    def test_summary_groups_engineers_and_managers(self):
        entries = [
            alarm_audit.normalize_entry(item, index)
            for index, item in enumerate(alarm_audit.parse_text(SAMPLE_MARKDOWN), 1)
        ]
        summary = alarm_audit.summarize(entries)
        self.assertEqual(3, summary["reviews"])
        self.assertEqual(1.33, summary["average_score"])
        self.assertEqual(["jyan", "lu122", "zhang301"], [item["name"] for item in summary["by_name"]])
        self.assertEqual(3, summary["by_manager"][0]["reviews"])

    def test_rendered_report_contains_complete_table(self):
        entries = [
            alarm_audit.normalize_entry(item, index)
            for index, item in enumerate(alarm_audit.parse_text(SAMPLE_MARKDOWN), 1)
        ]
        report = alarm_audit.render_report(entries)
        self.assertIn("# Alarm Ticket Audit Report", report)
        self.assertIn("## By Engineer", report)
        self.assertIn("## By Manager", report)
        self.assertIn("| INC7480916 | lu122 | qqu | global support | MED-GTWY | 1 | 0 | 0 | 0 | 1 | alarm cleared upon access |", report)

    def test_json_envelope_is_supported(self):
        data = {"entries": [{
            "ticket_id": "INC1234567",
            "name": "agent",
            "manager": "manager",
            "account_tier": "Premium",
            "alarm": "Heartbeat Failed",
            "check": 1,
            "cause": 1,
            "chronic": 1,
            "plus": 2,
            "comments": "recurring heartbeat issue; Plus +1: Prevention - monitoring added; Plus +1: Communication/Documentation - customer notified",
        }]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "alarm-audit.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            entries = alarm_audit.load_entries(path)
        self.assertEqual(5, entries[0]["score"])


if __name__ == "__main__":
    unittest.main()
