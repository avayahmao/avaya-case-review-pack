import importlib.util
import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


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
            "impact": "Call attempts failed on node 2; wider customer impact is unknown.",
            "current_progress": (
                "The failure was reproduced on node 2; a same-event trace "
                "has not yet been collected."
            ),
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
        "technical_advice": {
            "immediate_diagnostics": [
                {
                    "action": "Collect and correlate a same-event trace from node 2.",
                    "basis": "The failure was reproduced on node 2 without a trace.",
                }
            ],
            "potential_solutions": [
                {
                    "action": "correct the node configuration",
                    "condition": "the trace confirms a node-specific configuration mismatch",
                    "basis": "The current record does not establish configuration causality.",
                }
            ],
            "long_term_steps": [
                {
                    "action": "Verify sustained call success after the supported fix.",
                    "basis": "The durable production outcome remains unknown.",
                }
            ],
        },
        "visual_context": {},
    }


def structured_payload(**kwargs):
    value = payload(**kwargs)
    value.pop("full_review_markdown")
    value["presentation"] = presentation_payload()
    return value


def write_payload(directory, value, name="payload.json"):
    path = Path(directory) / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def durable_bytes(directory):
    case_dir = Path(directory) / "case-records" / "1-23700000001"
    return {
        path.name: path.read_bytes()
        for path in case_dir.iterdir()
        if path.is_file()
    }


class CaseRecordTests(unittest.TestCase):
    def test_future_reviewed_at_is_rejected(self):
        with self.assertRaisesRegex(
            case_record.RecordError,
            "reviewed_at cannot be in the future",
        ):
            case_record.validate_update_payload(
                structured_payload(reviewed_at="2099-01-01T00:00:00Z")
            )

    def test_finalize_write_failures_restore_every_existing_file(self):
        for target_name in (
            "record.json",
            "record.md",
            "chat-output.md",
            "chat-output.sha256",
        ):
            with self.subTest(target=target_name), TemporaryDirectory() as temporary:
                case_record.finalize_case_record(
                    structured_payload(),
                    "1-23700000001",
                    "Review 1-23700000001",
                    temporary,
                )
                before = durable_bytes(temporary)
                follow_up = structured_payload(
                    reviewed_at="2026-08-21T01:00:00Z",
                    snapshot="2026-08-21T00:59:00Z",
                    assignee="Engineer B",
                )
                original_replace = case_record.os.replace
                injected = False

                def fail_one_target(source, destination):
                    nonlocal injected
                    if not injected and Path(destination).name == target_name:
                        injected = True
                        raise OSError(f"injected {target_name} write failure")
                    return original_replace(source, destination)

                with patch.object(case_record.os, "replace", side_effect=fail_one_target):
                    with self.assertRaisesRegex(OSError, f"injected {re.escape(target_name)}"):
                        case_record.finalize_case_record(
                            follow_up,
                            "1-23700000001",
                            "Review 1-23700000001",
                            temporary,
                        )

                self.assertTrue(injected)
                self.assertEqual(before, durable_bytes(temporary))

    def test_finalize_verification_failure_restores_every_existing_file(self):
        with TemporaryDirectory() as temporary:
            case_record.finalize_case_record(
                structured_payload(),
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )
            before = durable_bytes(temporary)
            follow_up = structured_payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
                assignee="Engineer B",
            )

            with patch.object(
                case_record,
                "verify_chat_output_artifact",
                side_effect=case_record.RecordError("injected verification failure"),
            ):
                with self.assertRaisesRegex(
                    case_record.RecordError, "injected verification failure"
                ):
                    case_record.finalize_case_record(
                        follow_up,
                        "1-23700000001",
                        "Review 1-23700000001",
                        temporary,
                    )

            self.assertEqual(before, durable_bytes(temporary))

    def test_finalize_first_review_emits_one_verified_canonical_markdown(self):
        with TemporaryDirectory() as temporary:
            input_path = write_payload(temporary, structured_payload())

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--data-dir",
                    temporary,
                    "finalize",
                    "--input",
                    str(input_path),
                    "--case-id",
                    "1-23700000001",
                    "--request",
                    "Review 1-23700000001",
                ],
                check=True,
                capture_output=True,
            )

            case_dir = Path(temporary) / "case-records" / "1-23700000001"
            artifact = case_dir / "chat-output.md"
            digest_file = case_dir / "chat-output.sha256"
            self.assertEqual(completed.stdout, artifact.read_bytes())
            self.assertEqual(1, completed.stdout.count(b"# Case Review - 1-23700000001"))
            self.assertIn(b"## Executive Summary", completed.stdout)
            self.assertIn(b"### Action Plan", completed.stdout)
            self.assertIn(b"## Technical Advice", completed.stdout)
            self.assertEqual(
                f"{hashlib.sha256(completed.stdout).hexdigest()}  chat-output.md\n",
                digest_file.read_text(encoding="ascii"),
            )
            record = json.loads((case_dir / "record.json").read_text(encoding="utf-8"))
            self.assertEqual(1, len(record["reviews"]))

    def test_finalize_exact_retry_is_idempotent(self):
        with TemporaryDirectory() as temporary:
            value = structured_payload()
            first = case_record.finalize_case_record(
                value,
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )
            before = durable_bytes(temporary)

            second = case_record.finalize_case_record(
                value,
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )

            self.assertTrue(first["updated"])
            self.assertTrue(first["verification"]["verified"])
            self.assertFalse(second["updated"])
            self.assertEqual("duplicate review snapshot", second["reason"])
            self.assertEqual(first["markdown"], second["markdown"])
            self.assertEqual(before, durable_bytes(temporary))

    def test_finalize_rejects_divergent_same_snapshot_without_mutation(self):
        with TemporaryDirectory() as temporary:
            case_record.finalize_case_record(
                structured_payload(),
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )
            before = durable_bytes(temporary)
            changed = structured_payload(assignee="Engineer B")

            with self.assertRaisesRegex(case_record.RecordError, "newer fresh snapshot"):
                case_record.finalize_case_record(
                    changed,
                    "1-23700000001",
                    "Review 1-23700000001",
                    temporary,
                )

            self.assertEqual(before, durable_bytes(temporary))

    def test_finalize_rejects_incomplete_payload_without_mutation(self):
        with TemporaryDirectory() as temporary:
            case_record.finalize_case_record(
                structured_payload(),
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )
            before = durable_bytes(temporary)
            incomplete = structured_payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
            )
            incomplete["collection_status"] = "incomplete"

            with self.assertRaisesRegex(case_record.RecordError, "only after complete"):
                case_record.finalize_case_record(
                    incomplete,
                    "1-23700000001",
                    "Review 1-23700000001",
                    temporary,
                )

            self.assertEqual(before, durable_bytes(temporary))

    def test_finalize_rejects_legacy_markdown_only_follow_up_without_mutation(self):
        with TemporaryDirectory() as temporary:
            case_record.finalize_case_record(
                structured_payload(),
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )
            before = durable_bytes(temporary)
            follow_up = payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
                status="Closed - Complete",
            )
            follow_up["full_review_markdown"] = (
                "# Case Review - 1-23700000001\n\n**Status:** In Progress"
            )

            with self.assertRaisesRegex(
                case_record.RecordError, "current structured presentation"
            ):
                case_record.finalize_case_record(
                    follow_up,
                    "1-23700000001",
                    "Review 1-23700000001 again",
                    temporary,
                )

            self.assertEqual(before, durable_bytes(temporary))

    def test_presentation_cannot_override_validated_case_or_current(self):
        with TemporaryDirectory() as temporary:
            first = case_record.finalize_case_record(
                structured_payload(),
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )
            before = durable_bytes(temporary)

            for reserved, injected in (
                ("case_id", "1-23700000002"),
                (
                    "current",
                    {
                        **structured_payload()["current"],
                        "official_status": "Resolved",
                        "primary_problem": "A forged report-only problem",
                    },
                ),
            ):
                with self.subTest(reserved=reserved):
                    follow_up = structured_payload(
                        reviewed_at="2026-08-21T01:00:00Z",
                        snapshot="2026-08-21T00:59:00Z",
                    )
                    follow_up["presentation"][reserved] = injected

                    with self.assertRaisesRegex(
                        case_record.RecordError,
                        rf"presentation\.{reserved} may not override",
                    ):
                        case_record.finalize_case_record(
                            follow_up,
                            "1-23700000001",
                            "Review 1-23700000001 again",
                            temporary,
                        )
                    self.assertEqual(before, durable_bytes(temporary))

            stored = json.loads(Path(first["record_json"]).read_text(encoding="utf-8"))
            self.assertEqual(stored["current"], stored["review_snapshot"]["current"])
            self.assertIn("**Status:** In Progress", first["markdown"])
            self.assertNotIn("A forged report-only problem", first["markdown"])

    def test_finalize_matches_update_then_present_byte_for_byte(self):
        with TemporaryDirectory() as temporary:
            value = structured_payload()
            case_record.update_case_record(value, temporary)
            legacy = case_record.present_case_record(
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
                write_chat_output=True,
            )
            expected = Path(legacy["chat_output"]).read_bytes()

            finalized = case_record.finalize_case_record(
                value,
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )

            self.assertEqual(expected, finalized["markdown"].encode("utf-8"))
            self.assertEqual(expected, Path(finalized["chat_output"]).read_bytes())

    def test_finalize_render_failure_leaves_existing_files_unchanged(self):
        with TemporaryDirectory() as temporary:
            case_record.finalize_case_record(
                structured_payload(),
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )
            before = durable_bytes(temporary)
            follow_up = structured_payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
            )

            with patch.object(
                case_record,
                "render_review",
                side_effect=case_record.PresentationError("render failed"),
            ):
                with self.assertRaisesRegex(case_record.PresentationError, "render failed"):
                    case_record.finalize_case_record(
                        follow_up,
                        "1-23700000001",
                        "Review 1-23700000001",
                        temporary,
                    )

            self.assertEqual(before, durable_bytes(temporary))

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
            self.assertTrue(result["markdown"].startswith("# Case Review - 1-23700000001"))
            self.assertIn("## Executive Summary", result["markdown"])
            self.assertIn("Reported Problem / Symptom", result["markdown"])
            self.assertIn("Current State", result["markdown"])
            self.assertIn("### Action Plan", result["markdown"])
            self.assertIn("## Technical Advice", result["markdown"])
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
            self.assertTrue(completed.stdout.startswith("# Case Review - 1-23700000001"))
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

    def test_current_impact_and_progress_are_required(self):
        for field in ("impact", "current_progress"):
            with self.subTest(field=field):
                value = structured_payload()
                value["current"].pop(field)
                with self.assertRaisesRegex(case_record.RecordError, field):
                    case_record.validate_update_payload(value)

    def test_structured_technical_advice_requires_evidence_based_item_fields(self):
        missing_advice = structured_payload()
        missing_advice["presentation"].pop("technical_advice")
        with self.assertRaisesRegex(case_record.RecordError, "technical_advice"):
            case_record.validate_update_payload(missing_advice)

        for list_name, missing_field in (
            ("immediate_diagnostics", "basis"),
            ("potential_solutions", "condition"),
            ("long_term_steps", "action"),
        ):
            with self.subTest(list_name=list_name, missing_field=missing_field):
                value = structured_payload()
                value["presentation"]["technical_advice"][list_name][0].pop(
                    missing_field
                )
                with self.assertRaises(case_record.RecordError):
                    case_record.validate_update_payload(value)

        empty = structured_payload()
        empty["current"]["impact"] = "unknown"
        empty["presentation"]["technical_advice"] = {
            "immediate_diagnostics": [],
            "potential_solutions": [],
            "long_term_steps": [],
        }
        normalized = case_record.validate_update_payload(empty)
        self.assertEqual("unknown", normalized["current"]["impact"])
        self.assertEqual(
            [],
            normalized["presentation"]["technical_advice"]["potential_solutions"],
        )

    def test_structured_snapshot_normalizes_underscored_proof_states(self):
        structured = structured_payload()
        structured["presentation"]["technical_spec"]["evidence_gaps"]["state"] = (
            "NOT_COLLECTED"
        )
        structured["presentation"]["visual_context"] = {
            "hypotheses": [
                {
                    "claim": "One",
                    "state": "NOT_TESTED",
                    "evidence": "E1",
                    "validation": "Test one",
                },
                {
                    "claim": "Two",
                    "state": "SUSPECTED",
                    "evidence": "E1",
                    "validation": "Test two",
                },
            ]
        }

        normalized = case_record.validate_update_payload(structured)

        self.assertEqual(
            "NOT COLLECTED",
            normalized["presentation"]["technical_spec"]["evidence_gaps"]["state"],
        )
        self.assertEqual(
            "NOT TESTED",
            normalized["presentation"]["visual_context"]["hypotheses"][0]["state"],
        )

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

    def test_legacy_update_after_structured_review_cannot_present_stale_snapshot(self):
        with TemporaryDirectory() as temporary:
            case_record.finalize_case_record(
                structured_payload(),
                "1-23700000001",
                "Review 1-23700000001",
                temporary,
            )
            follow_up = payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
                status="Resolved",
            )
            follow_up["full_review_markdown"] = (
                "# Case Review - 1-23700000001\n\n**Status:** Resolved"
            )
            result = case_record.update_case_record(follow_up, temporary)
            stored = json.loads(Path(result["record_json"]).read_text(encoding="utf-8"))

            self.assertEqual("Resolved", stored["current"]["official_status"])
            self.assertEqual(follow_up["full_review_markdown"], stored["current_report_markdown"])
            self.assertEqual(2, len(stored["reviews"]))
            with self.assertRaisesRegex(
                case_record.RecordError, "structured v2 review before presentation"
            ):
                case_record.present_case_record(
                    "1-23700000001", "Review 1-23700000001 again", temporary
                )

    def test_impact_change_is_material_follow_up(self):
        with TemporaryDirectory() as temporary:
            case_record.update_case_record(structured_payload(), temporary)
            follow_up = structured_payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
            )
            follow_up["current"]["impact"] = (
                "Customer confirmed call failures across both production nodes."
            )
            result = case_record.update_case_record(follow_up, temporary)
            rendered = case_record.present_case_record(
                "1-23700000001", "Review 1-23700000001 again", temporary
            )

            self.assertTrue(
                any("impact" in change for change in result["delta"]["state_changes"])
            )
            self.assertEqual("follow-up", rendered["mode"])
            self.assertIn(
                "Customer confirmed call failures across both production nodes.",
                rendered["markdown"],
            )

    def test_first_follow_up_from_older_v2_record_does_not_invent_progress_changes(self):
        with TemporaryDirectory() as temporary:
            first = case_record.update_case_record(structured_payload(), temporary)
            record_path = Path(first["record_json"])
            older_v2 = json.loads(record_path.read_text(encoding="utf-8"))
            for prior_current in (
                older_v2["current"],
                older_v2["reviews"][-1]["current"],
                older_v2["review_snapshot"]["current"],
            ):
                prior_current.pop("impact")
                prior_current.pop("current_progress")
            record_path.write_text(json.dumps(older_v2), encoding="utf-8")

            follow_up = structured_payload(
                reviewed_at="2026-08-21T01:00:00Z",
                snapshot="2026-08-21T00:59:00Z",
            )
            result = case_record.update_case_record(follow_up, temporary)
            rendered = case_record.present_case_record(
                "1-23700000001", "Review 1-23700000001 again", temporary
            )

            self.assertEqual([], result["delta"]["state_changes"])
            self.assertEqual("standard", rendered["mode"])
            self.assertIn(
                "Call attempts failed on node 2; wider customer impact is unknown.",
                rendered["markdown"],
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



def passing_manifest(case_id="1-23700000001", snapshot="2026-08-20T00:59:00Z"):
    return {
        "case_id": case_id,
        "collected_at": "2026-08-20T00:59:30Z",
        "snapshot_before": snapshot,
        "status": "pass",
        "failures": [],
        "digest_degraded": False,
        "ledger": {
            "record_ids_planned": 1,
            "record_id_queries_completed": 1,
            "query_pages_completed": 1,
            "unique_threads_discovered": 1,
            "threads_read_complete": 1,
            "messages_expected": 2,
            "messages_completed": 2,
            "message_chunks_expected": 2,
            "message_chunks_completed": 2,
            "body_hashes_verified": 2,
            "manifest_hashes_stable": 1,
            "gmail_threads_discovered": 1,
            "gmail_threads_enumerated": 1,
            "gmail_threads_read_complete": 1,
            "gmail_messages_expected": 2,
            "gmail_messages_read": 2,
            "body_chunks_expected": 2,
            "body_chunks_read": 2,
            "snapshot_before": snapshot,
            "query_complete": True,
        },
    }


class SchemaCommandTests(unittest.TestCase):
    def test_schema_describes_validated_contract(self):
        schema = case_record.describe_schema()
        self.assertEqual(schema["schema_version"], case_record.SCHEMA_VERSION)
        update = schema["update_input"]
        self.assertEqual(
            sorted(update["current"]["required_non_empty_strings"]),
            sorted(case_record.CURRENT_FIELDS),
        )
        self.assertIn("rca_state", update["current"]["enums"])
        self.assertIn("impact", update["current"]["required_non_empty_strings"])
        self.assertIn("current_progress", update["current"]["required_non_empty_strings"])
        self.assertEqual(
            update["evidence_digest"]["states"], sorted(case_record.EVIDENCE_STATES)
        )
        self.assertEqual(
            update["coverage"]["equalities"],
            [f"{l} == {r}" for l, r in case_record.COVERAGE_EQUALITIES],
        )
        self.assertEqual(
            update["coverage"]["required_non_negative_integers"],
            sorted(case_record.coverage_required_numbers()),
        )
        presentation = update["presentation"]
        advice_lists = presentation["technical_advice"]["item_lists"]
        self.assertEqual(
            ["action", "basis"],
            advice_lists["immediate_diagnostics"]["item_fields"],
        )
        self.assertEqual(
            ["action", "condition", "basis"],
            advice_lists["potential_solutions"]["item_fields"],
        )
        self.assertEqual(
            ["action", "basis"],
            advice_lists["long_term_steps"]["item_fields"],
        )
        self.assertEqual(
            presentation["technical_spec"]["item_fields"],
            ["state", "value", "evidence"],
        )
        self.assertEqual(
            presentation["milestones"]["item_fields"],
            ["date", "change"],
        )
        self.assertEqual(
            presentation["timeline"]["item_fields"],
            ["date", "by", "source", "change"],
        )
        self.assertEqual(
            presentation["evidence_register"]["item_fields"],
            ["ref", "date", "source", "evidence", "supports"],
        )
        variants = presentation["visual_context"]["variants"]
        self.assertEqual(
            variants["recurrences"]["item_fields"],
            ["date", "symptom", "change", "outcome"],
        )
        self.assertEqual(
            variants["transitions"]["item_fields"],
            ["label", "state"],
        )
        evidence_rows = schema["build_payload"]["overlay_fields"]["evidence_rows"]
        self.assertTrue(evidence_rows["normal_path"])
        self.assertIn("supports", evidence_rows["required_item_fields"])
        self.assertIn("milestone_change", evidence_rows["optional_item_fields"])
        self.assertIn("trailing commas", schema["build_payload"]["overlay_syntax"])
        self.assertIn(
            "current structured presentation",
            schema["build_payload"]["finalize_requirement"],
        )
        self.assertIn(
            "full_review_markdown is supported by update only",
            schema["build_payload"]["finalize_requirement"],
        )

    def test_schema_cli_prints_json(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "schema"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertIn("build_payload", parsed)
        self.assertIn("update_input", parsed)
        self.assertIn("finalize-overlay", parsed["build_payload"]["normal_one_shot_command"])


class BuildPayloadTests(unittest.TestCase):
    def overlay(self):
        base = payload()
        return {
            "case_notes_discovered": 4,
            "case_notes_processed": 4,
            "reviewed_at": base["reviewed_at"],
            "current": base["current"],
            "evidence_digest": base["evidence_digest"],
            "full_review_markdown": base["full_review_markdown"],
        }

    def test_build_payload_round_trip_passes_update(self):
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            out_path = Path(tmp) / "payload.json"
            manifest_path.write_text(
                json.dumps(passing_manifest()), encoding="utf-8"
            )
            overlay_path.write_text(json.dumps(self.overlay()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    f"--data-dir={tmp}",
                    "build-payload",
                    "--manifest",
                    str(manifest_path),
                    "--overlay",
                    str(overlay_path),
                    "--out",
                    str(out_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            built = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(built["collection_status"], "complete")
            self.assertEqual(
                built["coverage"]["gmail_messages_read"], 2
            )
            record = case_record.update_case_record(built, Path(tmp))
            self.assertTrue(record["updated"])
            self.assertEqual(record["review_count"], 1)

    def test_build_payload_runs_render_preflight_before_writing(self):
        overlay = self.overlay()
        overlay.pop("full_review_markdown")
        overlay["presentation"] = presentation_payload()
        overlay["presentation"]["milestones"] = [
            {"date": "2026-08-20", "detail": "Field name is invalid."}
        ]
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            out_path = Path(tmp) / "payload.json"
            manifest_path.write_text(
                json.dumps(passing_manifest()), encoding="utf-8"
            )
            overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
            with self.assertRaisesRegex(
                case_record.RecordError,
                r"presentation is not renderable.*change",
            ):
                case_record.build_update_payload(
                    manifest_path, overlay_path, out_path
                )
            self.assertFalse(out_path.exists())

    def test_build_payload_expands_single_source_evidence_rows(self):
        overlay = self.overlay()
        overlay.pop("evidence_digest")
        overlay.pop("full_review_markdown")
        presentation = presentation_payload()
        presentation.pop("evidence_register")
        presentation.pop("timeline")
        presentation.pop("milestones")
        overlay["presentation"] = presentation
        overlay["evidence_rows"] = [
            {
                "state": "OBSERVED",
                "date": "2026-08-19T10:00:00Z",
                "source": "application.log",
                "fact": "Failure reproduced on node 2.",
                "supports": "Primary problem",
                "by": "Support",
                "change": "The failure was reproduced.",
                "milestone_change": "Reproduction established the failing node.",
            },
            {
                "state": "NOT TESTED",
                "date": "not stated",
                "source": "Coverage review",
                "fact": "A same-event network trace was not collected.",
                "supports": "Evidence gaps",
            },
        ]
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            out_path = Path(tmp) / "payload.json"
            manifest_path.write_text(
                json.dumps(passing_manifest()), encoding="utf-8"
            )
            overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
            case_record.build_update_payload(manifest_path, overlay_path, out_path)
            built = json.loads(out_path.read_text(encoding="utf-8"))

            self.assertEqual(2, len(built["evidence_digest"]))
            self.assertEqual(
                ["E1", "E2"],
                [item["ref"] for item in built["presentation"]["evidence_register"]],
            )
            self.assertEqual(1, len(built["presentation"]["timeline"]))
            self.assertEqual("E1", built["presentation"]["timeline"][0]["evidence"])
            self.assertEqual(1, len(built["presentation"]["milestones"]))
            self.assertEqual("E1", built["presentation"]["milestones"][0]["evidence"])

    def test_build_payload_rejects_mixed_evidence_surfaces(self):
        overlay = self.overlay()
        overlay["evidence_rows"] = [
            {
                "state": "OBSERVED",
                "date": "2026-08-19T10:00:00Z",
                "source": "application.log",
                "fact": "Failure reproduced on node 2.",
                "supports": "Primary problem",
            }
        ]
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            manifest_path.write_text(
                json.dumps(passing_manifest()), encoding="utf-8"
            )
            overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
            with self.assertRaisesRegex(
                case_record.RecordError,
                "cannot be combined with evidence_digest",
            ):
                case_record.build_update_payload(
                    manifest_path, overlay_path, Path(tmp) / "out.json"
                )

    def test_evidence_rows_require_chronological_order(self):
        rows = [
            {
                "state": "OBSERVED",
                "date": "2026-08-20",
                "source": "Later source",
                "fact": "Later fact.",
                "supports": "Current state",
            },
            {
                "state": "OBSERVED",
                "date": "2026-08-19",
                "source": "Earlier source",
                "fact": "Earlier fact.",
                "supports": "Primary problem",
            },
        ]
        with self.assertRaisesRegex(
            case_record.RecordError, "ordered oldest-first"
        ):
            case_record.expand_evidence_rows(rows)

    def test_evidence_rows_reject_compact_iso_date_that_presenter_cannot_sort(self):
        rows = [
            {
                "state": "OBSERVED",
                "date": "20260819",
                "source": "Case record",
                "fact": "A dated event occurred.",
                "supports": "Timeline",
            }
        ]
        with self.assertRaisesRegex(case_record.RecordError, "extended ISO-8601"):
            case_record.expand_evidence_rows(rows)

    def test_evidence_rows_bound_milestones_without_retry(self):
        rows = [
            {
                "state": "OBSERVED",
                "date": f"2026-08-{day:02d}",
                "source": f"Source {day}",
                "fact": f"Fact {day}.",
                "supports": "Timeline",
                "milestone_change": f"Milestone {day}.",
            }
            for day in range(1, 7)
        ]
        _digest, _register, _timeline, milestones = (
            case_record.expand_evidence_rows(rows)
        )
        self.assertEqual(
            ["2026-08-01", "2026-08-02", "2026-08-04", "2026-08-05", "2026-08-06"],
            [item["date"] for item in milestones],
        )

    def test_finalize_overlay_cli_builds_and_finalizes_in_one_process(self):
        overlay = self.overlay()
        overlay.pop("evidence_digest")
        overlay.pop("full_review_markdown")
        presentation = presentation_payload()
        presentation.pop("evidence_register")
        presentation.pop("timeline")
        presentation.pop("milestones")
        overlay["presentation"] = presentation
        overlay["evidence_rows"] = [
            {
                "state": "OBSERVED",
                "date": "2026-08-19T10:00:00Z",
                "source": "application.log",
                "fact": "Failure reproduced on node 2.",
                "supports": "Primary problem",
                "by": "Support",
                "change": "The failure was reproduced.",
                "milestone_change": "Reproduction established the failing node.",
            }
        ]
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            manifest_path.write_text(
                json.dumps(passing_manifest()), encoding="utf-8"
            )
            overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--data-dir",
                    tmp,
                    "finalize-overlay",
                    "--manifest",
                    str(manifest_path),
                    "--overlay",
                    str(overlay_path),
                    "--case-id",
                    "1-23700000001",
                    "--request",
                    "Review 1-23700000001",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("# Case Review - 1-23700000001", result.stdout)
            case_dir = Path(tmp) / "case-records" / "1-23700000001"
            self.assertTrue((case_dir / "record.json").is_file())
            self.assertEqual(
                result.stdout,
                (case_dir / "chat-output.md").read_text(encoding="utf-8"),
            )

    def test_build_payload_rejects_non_passing_manifest(self):
        manifest = passing_manifest()
        manifest["status"] = "fail"
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            overlay_path.write_text(json.dumps(self.overlay()), encoding="utf-8")
            with self.assertRaises(case_record.RecordError):
                case_record.build_update_payload(
                    manifest_path, overlay_path, Path(tmp) / "out.json"
                )

    def test_build_payload_rejects_missing_note_counters(self):
        overlay = self.overlay()
        del overlay["case_notes_discovered"]
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            manifest_path.write_text(
                json.dumps(passing_manifest()), encoding="utf-8"
            )
            overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
            with self.assertRaises(case_record.RecordError):
                case_record.build_update_payload(
                    manifest_path, overlay_path, Path(tmp) / "out.json"
                )

    def test_build_payload_rejects_unequal_note_counters(self):
        overlay = self.overlay()
        overlay["case_notes_processed"] = 3
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            manifest_path.write_text(
                json.dumps(passing_manifest()), encoding="utf-8"
            )
            overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
            with self.assertRaises(case_record.RecordError):
                case_record.build_update_payload(
                    manifest_path, overlay_path, Path(tmp) / "out.json"
                )

    def test_build_payload_accepts_utf8_bom_in_agent_overlay(self):
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            out_path = Path(tmp) / "payload.json"
            manifest_path.write_text(json.dumps(passing_manifest()), encoding="utf-8")
            overlay_path.write_bytes(
                b"\xef\xbb\xbf" + json.dumps(self.overlay()).encode("utf-8")
            )
            case_record.build_update_payload(manifest_path, overlay_path, out_path)
            self.assertTrue(out_path.is_file())

    def test_build_payload_accepts_trailing_commas_in_agent_overlay(self):
        with TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            overlay_path = Path(tmp) / "overlay.json"
            out_path = Path(tmp) / "payload.json"
            manifest_path.write_text(
                json.dumps(passing_manifest()), encoding="utf-8"
            )
            overlay_text = json.dumps(self.overlay(), indent=2)
            overlay_path.write_text(
                overlay_text.rsplit("\n}", 1)[0] + ",\n}\n",
                encoding="utf-8",
            )
            case_record.build_update_payload(manifest_path, overlay_path, out_path)
            self.assertTrue(out_path.is_file())


if __name__ == "__main__":
    unittest.main()
