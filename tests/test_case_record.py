import importlib.util
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugins/avaya-case-review/skills/case-review/scripts/case_record.py"
)
SKILL = ROOT / "plugins/avaya-case-review/skills/case-review/SKILL.md"
LIFECYCLE = (
    ROOT
    / "plugins/avaya-case-review/skills/case-review/references/case-record-lifecycle.md"
)
RELEASE_MANIFEST = ROOT / "release-manifest.txt"
SPEC = importlib.util.spec_from_file_location("case_record", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load case_record.py")
case_record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(case_record)


def payload(
    reviewed_at="2026-08-20T01:00:00Z",
    snapshot="2026-08-20T00:59:00Z",
    status="In Progress",
    assignee="Engineer A",
    rca_state="Under Investigation",
    mitigation="None Active",
    production_outcome="unknown",
    blocker="Fresh logs not collected",
    evidence_fact="Failure reproduced on node 2.",
):
    return {
        "case_id": "1-23700000001",
        "reviewed_at": reviewed_at,
        "snapshot_before": snapshot,
        "collection_status": "complete",
        "coverage": {
            "case_notes_discovered": 4,
            "case_notes_processed": 4,
            "record_ids_planned": 1,
            "record_id_queries_completed": 1,
            "query_complete": True,
            "unique_threads_discovered": 1,
            "threads_read_complete": 1,
            "messages_expected": 2,
            "messages_completed": 2,
            "message_chunks_expected": 2,
            "message_chunks_completed": 2,
            "body_hashes_verified": 2,
            "manifest_hashes_stable": 1,
            "snapshot_before": snapshot,
        },
        "current": {
            "title": "Example fault",
            "source": "Siebel SR",
            "official_status": status,
            "priority": "P2",
            "assignee": assignee,
            "primary_problem": "Calls fail on node 2",
            "confirmed_finding": "Failure is isolated to node 2",
            "unproven_or_contradicted": "Database causality is not proven",
            "rca_state": rca_state,
            "mitigation_state": mitigation,
            "production_outcome": production_outcome,
            "current_blocker": blocker,
            "next_action": "Collect a same-event trace",
            "next_action_owner": assignee,
            "next_due": "2026-08-21",
        },
        "evidence_digest": [
            {
                "state": "OBSERVED",
                "date": "2026-08-19T10:00:00Z",
                "source": "application.log",
                "fact": evidence_fact,
            }
        ],
        "full_review_markdown": "# Case Review - 1-23700000001\n\nEvidence-grounded review.",
    }


def learning_candidate():
    return {
        "case_id": "1-23700000001",
        "domain": "contact-center",
        "title": "Correlate a failing node before assigning platform causality",
        "learning_type": "diagnostic-heuristic",
        "evidence_strength": "Suspected",
        "generalized_finding": "A node-specific symptom requires same-event correlation before platform-wide attribution.",
        "activation_conditions": ["The symptom occurs on only one application node."],
        "diagnostic_steps": ["Correlate the application and platform logs for the same event."],
        "disconfirming_signals": ["The same failure occurs across all nodes at the same time."],
        "limitations": ["This pattern does not establish a product defect by itself."],
        "customer_data_removed": True,
    }


def presentation_payload():
    technical_item = {
        "state": "UNKNOWN",
        "value": "unknown",
        "evidence": "No supporting evidence",
    }
    return {
        "technical_spec": {
            key: dict(technical_item)
            for key in (
                "scope",
                "environment",
                "symptom",
                "trigger_conditions",
                "observed_signals",
                "confirmed_mechanism",
                "suspected_or_unproven",
                "ruled_out",
                "change_or_mitigation",
                "verification",
                "production_outcome",
                "evidence_gaps",
            )
        },
        "problem_lineage": {
            "original_objective": "Restore service",
            "intended_action": "Analyze the failure",
            "blocker": "Evidence pending",
            "working_hypotheses": ["Resource exhaustion"],
            "corrected_finding": "unknown",
            "implemented_action": "Restarted service",
            "outcome": "Immediate recovery",
            "secondary_problems": [],
        },
        "milestones": [],
        "timeline": [],
        "evidence_register": [
            {
                "ref": "E1",
                "date": "2026-08-19T10:00:00Z",
                "source": "application.log",
                "evidence": "Failure reproduced on node 2.",
                "supports": "Primary problem",
            }
        ],
        "visual_context": {},
    }


class CaseRecordTests(unittest.TestCase):
    def test_skill_and_release_include_the_lifecycle_resources(self):
        skill = SKILL.read_text(encoding="utf-8-sig")
        lifecycle = LIFECYCLE.read_text(encoding="utf-8-sig")
        entries = {
            line.strip()
            for line in RELEASE_MANIFEST.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.startswith("#")
        }
        for marker in (
            "Persist and Present Deterministically",
            "post-analysis comparison baseline",
            "show the learning option",
            "Apply sanitized learning only after explicit approval",
        ):
            self.assertIn(marker, skill)
        for marker in (
            "never replaces fresh source collection",
            "leave the existing record byte-for-byte unchanged",
            "Deterministic Chat Response",
            "Administrative Closure and Learning",
            "apply-learning",
        ):
            self.assertIn(marker, lifecycle)
        self.assertIn(
            "plugins/avaya-case-review/skills/case-review/scripts/case_record.py",
            entries,
        )
        self.assertIn(
            "plugins/avaya-case-review/skills/case-review/references/case-record-lifecycle.md",
            entries,
        )

    def test_first_review_creates_human_and_machine_records(self):
        with TemporaryDirectory() as temporary:
            result = case_record.update_case_record(payload(), temporary)
            self.assertTrue(result["updated"])
            machine = Path(result["record_json"])
            human = Path(result["record_markdown"])
            self.assertTrue(machine.is_file())
            self.assertTrue(human.is_file())

            record = json.loads(machine.read_text(encoding="utf-8"))
            self.assertEqual(1, len(record["reviews"]))
            self.assertEqual("open", record["current"]["administrative_state"])
            self.assertEqual("not_available", record["learning"]["option"])
            rendered = human.read_text(encoding="utf-8")
            self.assertIn("Comparison baseline only", rendered)
            self.assertIn("Initial case record created", rendered)

    def test_v2_structured_review_does_not_require_full_report_markdown(self):
        with TemporaryDirectory() as temporary:
            structured = payload()
            structured.pop("full_review_markdown")
            structured["presentation"] = presentation_payload()

            result = case_record.update_case_record(structured, temporary)
            record = json.loads(Path(result["record_json"]).read_text(encoding="utf-8"))

            self.assertEqual(2, record["schema_version"])
            self.assertIn("review_snapshot", record)
            self.assertEqual(
                "Restore service",
                record["review_snapshot"]["problem_lineage"]["original_objective"],
            )
            self.assertNotIn("current_report_markdown", record)

    def test_v1_record_migrates_without_losing_history_or_legacy_report(self):
        with TemporaryDirectory() as temporary:
            first = case_record.update_case_record(payload(), temporary)
            machine = Path(first["record_json"])
            legacy = json.loads(machine.read_text(encoding="utf-8"))
            legacy["schema_version"] = 1
            machine.write_text(json.dumps(legacy, indent=2), encoding="utf-8")

            follow_up = payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
                assignee="Engineer B",
                evidence_fact="A new stack was analyzed.",
            )
            follow_up.pop("full_review_markdown")
            follow_up["presentation"] = presentation_payload()
            result = case_record.update_case_record(follow_up, temporary)
            migrated = json.loads(
                Path(result["record_json"]).read_text(encoding="utf-8")
            )

            self.assertEqual(2, migrated["schema_version"])
            self.assertEqual("2026-08-20T01:00:00Z", migrated["created_at"])
            self.assertEqual(2, len(migrated["reviews"]))
            self.assertIn("legacy_full_report_markdown", migrated)
            self.assertIn("Evidence-grounded review", migrated["legacy_full_report_markdown"])

    def test_present_case_record_uses_stored_snapshot_and_delta(self):
        with TemporaryDirectory() as temporary:
            structured = payload()
            structured.pop("full_review_markdown")
            structured["presentation"] = presentation_payload()
            case_record.update_case_record(structured, temporary)

            result = case_record.present_case_record(
                "1-23700000001", "Review 1-23700000001", temporary
            )

            self.assertEqual("standard", result["mode"])
            self.assertIn("# Case Card - 1-23700000001", result["markdown"])
            self.assertIn("## Investigation Progress", result["markdown"])
            self.assertIn("## Causal Assessment", result["markdown"])
            self.assertIn("## Timeline", result["markdown"])
            self.assertIn("## Evidence Register", result["markdown"])

    def test_present_markdown_only_writes_canonical_artifact_and_sha256(self):
        with TemporaryDirectory() as temporary:
            structured = payload()
            structured.pop("full_review_markdown")
            structured["presentation"] = presentation_payload()
            case_record.update_case_record(structured, temporary)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--data-dir",
                    temporary,
                    "present",
                    "--case-id",
                    "1-23700000001",
                    "--request",
                    "Review 1-23700000001",
                    "--markdown-only",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            case_dir = Path(temporary) / "case-records" / "1-23700000001"
            artifact = case_dir / "chat-output.md"
            digest_file = case_dir / "chat-output.sha256"
            self.assertEqual(completed.stdout, artifact.read_text(encoding="utf-8"))
            expected_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            self.assertEqual(
                f"{expected_digest}  chat-output.md\n",
                digest_file.read_text(encoding="ascii"),
            )
            self.assertTrue(completed.stdout.startswith("# Case Card - 1-23700000001"))
            self.assertNotIn('"markdown"', completed.stdout)

    def test_verify_final_accepts_exact_output_and_blocks_drift(self):
        with TemporaryDirectory() as temporary:
            structured = payload()
            structured.pop("full_review_markdown")
            structured["presentation"] = presentation_payload()
            case_record.update_case_record(structured, temporary)
            present = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--data-dir",
                    temporary,
                    "present",
                    "--case-id",
                    "1-23700000001",
                    "--request",
                    "Review 1-23700000001",
                    "--markdown-only",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            candidate = Path(temporary) / "candidate.md"
            candidate.write_text(
                present.stdout.replace("\n", "\r\n"),
                encoding="utf-8",
                newline="",
            )

            verified = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--data-dir",
                    temporary,
                    "verify-final",
                    "--case-id",
                    "1-23700000001",
                    "--input",
                    str(candidate),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            verification = json.loads(verified.stdout)
            self.assertTrue(verification["verified"])
            self.assertEqual(
                verification["artifact_sha256"], verification["candidate_sha256"]
            )

            candidate.write_text(
                present.stdout.replace("| Proof state |", "|"),
                encoding="utf-8",
            )
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--data-dir",
                    temporary,
                    "verify-final",
                    "--case-id",
                    "1-23700000001",
                    "--input",
                    str(candidate),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("final output integrity mismatch", rejected.stderr)

    def test_invalid_structured_snapshot_is_rejected_before_write(self):
        with TemporaryDirectory() as temporary:
            structured = payload()
            structured.pop("full_review_markdown")
            structured["presentation"] = presentation_payload()
            structured["presentation"]["technical_spec"]["scope"]["state"] = (
                "87% CONFIDENT"
            )

            with self.assertRaisesRegex(case_record.RecordError, "unsupported proof state"):
                case_record.update_case_record(structured, temporary)

            paths = case_record.case_paths(
                case_record.resolve_data_dir(temporary), "1-23700000001"
            )
            self.assertFalse(paths["json"].exists())

    def test_follow_up_updates_current_state_and_preserves_history(self):
        with TemporaryDirectory() as temporary:
            case_record.update_case_record(payload(), temporary)
            second = payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
                assignee="Engineer B",
                rca_state="Identified",
                mitigation="Production Deployed",
                evidence_fact="Configuration mismatch was found on node 2.",
            )
            result = case_record.update_case_record(second, temporary)
            record = json.loads(Path(result["record_json"]).read_text(encoding="utf-8"))
            self.assertEqual(2, len(record["reviews"]))
            self.assertEqual("Engineer B", record["current"]["assignee"])
            self.assertTrue(result["delta"]["state_changes"])
            self.assertTrue(result["delta"]["ownership_changes"])
            self.assertEqual(
                ["Configuration mismatch was found on node 2."],
                result["delta"]["new_evidence"],
            )

    def test_duplicate_complete_snapshot_is_idempotent(self):
        with TemporaryDirectory() as temporary:
            first = case_record.update_case_record(payload(), temporary)
            second = case_record.update_case_record(payload(), temporary)
            self.assertFalse(second["updated"])
            record = json.loads(Path(first["record_json"]).read_text(encoding="utf-8"))
            self.assertEqual(1, len(record["reviews"]))

    def test_same_snapshot_cannot_overwrite_state(self):
        with TemporaryDirectory() as temporary:
            case_record.update_case_record(payload(), temporary)
            changed = payload(assignee="Engineer B")
            with self.assertRaisesRegex(case_record.RecordError, "newer fresh snapshot"):
                case_record.update_case_record(changed, temporary)

    def test_incomplete_collection_cannot_change_existing_record(self):
        with TemporaryDirectory() as temporary:
            result = case_record.update_case_record(payload(), temporary)
            before = Path(result["record_json"]).read_bytes()
            invalid = payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
            )
            invalid["collection_status"] = "incomplete"
            with self.assertRaisesRegex(case_record.RecordError, "only after complete"):
                case_record.update_case_record(invalid, temporary)
            self.assertEqual(before, Path(result["record_json"]).read_bytes())

    def test_administrative_closure_keeps_unknown_production_outcome(self):
        with TemporaryDirectory() as temporary:
            closed = payload(status="Closed - Complete", production_outcome="unknown")
            result = case_record.update_case_record(closed, temporary)
            record = json.loads(Path(result["record_json"]).read_text(encoding="utf-8"))
            self.assertEqual("closed", record["current"]["administrative_state"])
            self.assertEqual("unknown", record["current"]["production_outcome"])
            self.assertEqual("available", record["learning"]["option"])

    def test_learning_requires_closure_sanitization_and_explicit_approval(self):
        with TemporaryDirectory() as temporary:
            case_record.update_case_record(payload(status="Completed"), temporary)
            drafted = case_record.draft_learning_candidate(learning_candidate(), temporary)
            self.assertTrue(Path(drafted["candidate_markdown"]).is_file())
            self.assertTrue(drafted["requires_user_approval"])

            with self.assertRaisesRegex(case_record.RecordError, "explicit user approval"):
                case_record.apply_learning("1-23700000001", False, temporary)

            applied = case_record.apply_learning("1-23700000001", True, temporary)
            overlay = Path(applied["overlay"])
            self.assertTrue(overlay.is_file())
            self.assertIn("Evidence strength", overlay.read_text(encoding="utf-8"))

            duplicate = case_record.apply_learning("1-23700000001", True, temporary)
            self.assertFalse(duplicate["applied"])

    def test_reopening_suspends_previously_applied_learning(self):
        with TemporaryDirectory() as temporary:
            case_record.update_case_record(payload(status="Completed"), temporary)
            case_record.draft_learning_candidate(learning_candidate(), temporary)
            applied = case_record.apply_learning("1-23700000001", True, temporary)

            reopened = payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
                status="In Progress",
                evidence_fact="The symptom recurred after administrative closure.",
            )
            result = case_record.update_case_record(reopened, temporary)
            record = json.loads(Path(result["record_json"]).read_text(encoding="utf-8"))
            self.assertEqual("reopened", record["current"]["administrative_state"])
            self.assertEqual("review_required_reopened", record["learning"]["status"])
            overlay = Path(applied["overlay"]).read_text(encoding="utf-8")
            self.assertIn("**Approval state:** suspended", overlay)

    def test_learning_candidate_cannot_embed_case_id_in_generalized_text(self):
        with TemporaryDirectory() as temporary:
            case_record.update_case_record(payload(status="Resolved"), temporary)
            candidate = learning_candidate()
            candidate["generalized_finding"] += " Seen in 1-23700000001."
            with self.assertRaisesRegex(case_record.RecordError, "remove the case ID"):
                case_record.draft_learning_candidate(candidate, temporary)


if __name__ == "__main__":
    unittest.main()
