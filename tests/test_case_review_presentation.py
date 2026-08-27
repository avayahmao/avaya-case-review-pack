import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins/avaya-case-review/skills/case-review/SKILL.md"
OUTPUT_MODES = (
    ROOT
    / "plugins/avaya-case-review/skills/case-review/references/output-modes.md"
)
RELEASE_MANIFEST = ROOT / "release-manifest.txt"
SCRIPT = (
    ROOT
    / "plugins/avaya-case-review/skills/case-review/scripts/review_presenter.py"
)
SPEC = importlib.util.spec_from_file_location("review_presenter", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load review_presenter.py")
review_presenter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_presenter)


def snapshot():
    return {
        "case_id": "1-23700000001",
        "current": {
            "official_status": "Working",
            "rca_state": "Suspected",
            "mitigation_state": "Production Deployed",
            "primary_problem": "Tomcat stopped serving the management application.",
            "confirmed_finding": "The service recovered after restart.",
            "unproven_or_contradicted": "A memory leak is not proven.",
            "production_outcome": "Immediate recovery confirmed; sustained outcome unknown.",
            "current_blocker": "Heap evidence has not been analyzed.",
            "next_action": "Analyze the heap evidence.",
            "next_action_owner": "Engineer A",
            "next_due": "2026-08-21",
        },
        "technical_spec": {
            "scope": {
                "state": "OBSERVED",
                "value": "Production EPM node 2A",
                "evidence": "Incident timeline",
            },
            "environment": {
                "state": "OBSERVED",
                "value": "EPM 8.1.2.1.0020",
                "evidence": "Environment update",
            },
            "symptom": {
                "state": "OBSERVED",
                "value": "Tomcat stopped serving the management application",
                "evidence": "Case description",
            },
            "trigger_conditions": {
                "state": "UNKNOWN",
                "value": "unknown",
                "evidence": "No reproduction",
            },
            "observed_signals": {
                "state": "OBSERVED",
                "value": "Reported OutOfMemoryError",
                "evidence": "Case description",
            },
            "confirmed_mechanism": {
                "state": "NOT OBSERVED",
                "value": "No confirmed mechanism",
                "evidence": "No analyzed stack",
            },
            "suspected_or_unproven": {
                "state": "SUSPECTED",
                "value": "Configured heap limit may have been reached",
                "evidence": "Working hypothesis",
            },
            "ruled_out": {
                "state": "NOT APPLICABLE",
                "value": "No alternative has been ruled out",
                "evidence": "Investigation remains open",
            },
            "change_or_mitigation": {
                "state": "PRODUCTION DEPLOYED",
                "value": "Tomcat service restarted",
                "evidence": "Operations timeline",
            },
            "verification": {
                "state": "OUTCOME CONFIRMED",
                "value": "Management page recovered",
                "evidence": "Post-restart check",
            },
            "production_outcome": {
                "state": "UNKNOWN",
                "value": "Sustained outcome unknown",
                "evidence": "No monitoring result",
            },
            "evidence_gaps": {
                "state": "NOT COLLECTED",
                "value": "GC log and heap dump",
                "evidence": "Not present in collected sources",
            },
        },
        "problem_lineage": {
            "original_objective": "Restore the EPM management application.",
            "intended_action": "Analyze the OutOfMemoryError evidence.",
            "blocker": "Heap evidence has not been analyzed.",
            "working_hypotheses": ["Configured heap limit may have been reached."],
            "corrected_finding": "unknown",
            "implemented_action": "Restarted Tomcat.",
            "outcome": "Immediate recovery confirmed.",
            "secondary_problems": ["Sustained outcome remains unknown."],
        },
        "milestones": [
            {"date": "2026-08-18", "change": "Management application failed."},
            {"date": "2026-08-18", "change": "Tomcat was restarted."},
        ],
        "timeline": [
            {
                "date": "2026-08-18T10:58:00Z",
                "by": "Customer",
                "source": "Case record",
                "change": "Management application failed.",
            }
        ],
        "evidence_register": [
            {
                "ref": "E1",
                "date": "2026-08-18T10:58:00Z",
                "source": "Case record",
                "evidence": "Tomcat stopped serving the management application.",
                "supports": "Primary problem",
            }
        ],
        "visual_context": {},
    }


def final_drift_regression_snapshot():
    data = copy.deepcopy(snapshot())
    data["case_id"] = "1-23780000000"
    data["current"].update(
        {
            "primary_problem": "Intermittent production transactions failed during the reported window.",
            "confirmed_finding": "Service recovery was reported after the configuration change.",
            "unproven_or_contradicted": (
                "The case record reports business impact, while a later email says no "
                "end-user impact; the source conflict remains unresolved."
            ),
            "production_outcome": (
                "Immediate recovery was reported, but sustained post-change production "
                "validation is not available."
            ),
            "current_blocker": "A recurrence-free monitoring result has not been supplied.",
            "next_action": "Confirm seven-day recurrence-free operation and reconcile the impact statements.",
            "next_action_owner": "Support Engineer",
            "next_due": "2026-08-26 17:00 SGT",
        }
    )
    data["technical_spec"]["verification"] = {
        "state": "NOT COLLECTED",
        "value": "No sustained post-change validation result is available.",
        "evidence": "The collected record ends after the immediate recovery report.",
    }
    data["technical_spec"]["evidence_gaps"] = {
        "state": "NOT COLLECTED",
        "value": "Recurrence-free monitoring and a reconciled impact statement.",
        "evidence": "Neither item appears in the collected sources.",
    }
    data["milestones"] = [
        {"date": "2026-08-18", "change": "Production failures were reported."},
        {"date": "2026-08-19", "change": "Competing technical explanations were recorded."},
        {"date": "2026-08-20", "change": "A configuration change was deployed."},
        {"date": "2026-08-21", "change": "Immediate recovery was reported; sustained validation remained open."},
    ]
    data["visual_context"] = {
        "hypotheses": [
            {
                "claim": "The configuration mismatch caused the failures",
                "state": "SUSPECTED",
                "evidence": "Recovery followed the configuration change",
                "validation": "Correlate same-event logs and confirm no recurrence",
            },
            {
                "claim": "The incident had no business impact",
                "state": "CONTRADICTED",
                "evidence": "The case record and later email contain conflicting impact statements",
                "validation": "Reconcile the statements with the customer",
            },
        ]
    }
    return data


class CaseReviewPresentationTests(unittest.TestCase):
    def test_skill_uses_structured_snapshot_and_on_demand_full_output(self):
        skill = SKILL.read_text(encoding="utf-8-sig")
        output_modes = OUTPUT_MODES.read_text(encoding="utf-8-sig")
        entries = {
            line.strip()
            for line in RELEASE_MANIFEST.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.startswith("#")
        }

        for marker in (
            "Build the Structured Review Snapshot",
            "case_record.py update",
            "case_record.py present",
            "output-modes.md",
        ):
            self.assertIn(marker, skill)
        for forbidden in (
            "Write one natural-language paragraph of 6-8 sentences",
            "final section of every rendered review",
        ):
            self.assertNotIn(forbidden, skill)
        for mode in ("standard", "compact", "follow-up", "technical", "flow", "full"):
            self.assertIn(f"`{mode}`", output_modes)
        self.assertIn(
            "plugins/avaya-case-review/skills/case-review/scripts/review_presenter.py",
            entries,
        )
        self.assertIn(
            "plugins/avaya-case-review/skills/case-review/references/output-modes.md",
            entries,
        )

    def test_plain_review_defaults_to_balanced_standard_view(self):
        result = review_presenter.render_review(
            request_text="Review 1-23700000001",
            snapshot=snapshot(),
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("standard", result["mode"])
        self.assertIn("# Case Card - 1-23700000001", result["markdown"])
        self.assertIn("Primary problem", result["markdown"])
        self.assertIn("## Key Technical Specification", result["markdown"])
        for field in (
            "Scope",
            "Symptom",
            "Confirmed mechanism",
            "Suspected or unproven",
            "Verification",
            "Evidence gaps",
        ):
            self.assertIn(f"| {field} |", result["markdown"])
        self.assertIn("## Progress Milestones", result["markdown"])
        self.assertIn("Management application failed.", result["markdown"])
        for marker in (
            "## Investigation Progress",
            "## Causal Assessment",
            "## Timeline",
            "## Evidence Register",
        ):
            self.assertIn(marker, result["markdown"])
        for forbidden in ("Executive Summary",):
            self.assertNotIn(forbidden, result["markdown"])

    def test_explicit_compact_request_returns_case_card_only(self):
        result = review_presenter.render_review(
            request_text="Give me a compact review of 1-23700000001",
            snapshot=snapshot(),
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("compact", result["mode"])
        self.assertIn("# Case Card - 1-23700000001", result["markdown"])
        self.assertNotIn("## Key Technical Specification", result["markdown"])
        self.assertNotIn("## Progress Milestones", result["markdown"])

    def test_standard_view_preserves_final_drift_regression_details(self):
        result = review_presenter.render_review(
            request_text="Review 1-23780000000",
            snapshot=final_drift_regression_snapshot(),
            review_count=1,
            delta=None,
            record_path="C:/records/1-23780000000/record.md",
        )

        markdown = result["markdown"]
        self.assertEqual("standard", result["mode"])
        self.assertIn(
            "| Claim | Proof state | Evidence | Validation needed |", markdown
        )
        self.assertIn(
            "The case record reports business impact, while a later email says no "
            "end-user impact; the source conflict remains unresolved.",
            markdown,
        )
        self.assertIn("No sustained post-change validation result is available.", markdown)
        self.assertIn("Support Engineer", markdown)
        self.assertIn("2026-08-26 17:00 SGT", markdown)
        self.assertEqual(4, sum(1 for line in markdown.splitlines() if line.startswith("- **2026-")))
        self.assertIn("## Evidence Register", markdown)

    def test_existing_record_defaults_to_delta_first_follow_up(self):
        delta = {
            "state_changes": ["rca state: Under Investigation -> Suspected"],
            "ownership_changes": ["assignee: Engineer A -> Engineer B"],
            "new_evidence": ["A new exception stack was analyzed."],
            "unchanged_blockers": ["Production validation remains pending."],
        }
        result = review_presenter.render_review(
            request_text="Review 1-23700000001 again",
            snapshot=snapshot(),
            review_count=2,
            delta=delta,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("follow-up", result["mode"])
        self.assertIn("Changed since last review", result["markdown"])
        self.assertIn("New decisive evidence", result["markdown"])
        self.assertIn("Unchanged blocker", result["markdown"])
        self.assertLess(
            result["markdown"].index("Changed since last review"),
            result["markdown"].index("Primary problem"),
        )
        self.assertNotIn("Follow-up History", result["markdown"])
        changed_line = next(
            line
            for line in result["markdown"].splitlines()
            if "Changed since last review" in line
        )
        self.assertLessEqual(len(changed_line), 240)
        self.assertNotIn("Under Investigation -> Suspected", changed_line)

    def test_material_follow_up_preserves_complete_investigation(self):
        data = final_drift_regression_snapshot()
        delta = {
            "state_changes": ["rca state: Under Investigation -> Suspected"],
            "ownership_changes": ["assignee: Engineer A -> Support Engineer"],
            "new_evidence": ["A new exception stack was analyzed."],
            "unchanged_blockers": ["Sustained validation remains pending."],
        }
        result = review_presenter.render_review(
            request_text="Review 1-23780000000 again",
            snapshot=data,
            review_count=2,
            delta=delta,
            record_path="C:/records/1-23780000000/record.md",
        )

        markdown = result["markdown"]
        self.assertEqual("follow-up", result["mode"])
        self.assertLess(
            markdown.index("Changed since last review"),
            markdown.index("## Investigation Progress"),
        )
        for marker in (
            "## Investigation Progress",
            "flowchart TD",
            "## Causal Assessment",
            "Confirmed mechanism",
            "Suspected causal paths",
            "Remaining causal validation",
            "## Timeline",
            "## Evidence Register",
            "| Ref | Date | Source | Verbatim evidence / data | Supports |",
            "Tomcat stopped serving the management application.",
        ):
            self.assertIn(marker, markdown)
        self.assertIn("## Claim–Evidence Matrix", markdown)

    def test_unchanged_follow_up_defaults_to_complete_standard(self):
        delta = {
            "state_changes": [],
            "ownership_changes": [],
            "new_evidence": [],
            "unchanged_blockers": ["Production validation remains pending."],
        }
        result = review_presenter.render_review(
            request_text="Review 1-23700000001 again",
            snapshot=snapshot(),
            review_count=2,
            delta=delta,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("standard", result["mode"])
        self.assertIn("# Case Card - 1-23700000001", result["markdown"])
        self.assertNotIn("Changed since last review", result["markdown"])
        self.assertIn("## Investigation Progress", result["markdown"])
        self.assertIn("## Timeline", result["markdown"])
        self.assertIn("## Evidence Register", result["markdown"])

    def test_explicit_flow_request_never_routes_to_another_visual(self):
        result = review_presenter.render_review(
            request_text="Draw the investigation progress flow chart",
            snapshot=final_drift_regression_snapshot(),
            review_count=2,
            delta={},
            record_path="C:/records/1-23780000000/record.md",
        )

        self.assertEqual("flow", result["mode"])
        self.assertEqual("progress-flow", result["visual"])
        self.assertIn("## Investigation Progress", result["markdown"])
        self.assertIn("flowchart TD", result["markdown"])
        self.assertNotIn("Claim–Evidence Matrix", result["markdown"])

    def test_explicit_standard_follow_up_puts_delta_first(self):
        delta = {
            "state_changes": ["rca state: Under Investigation -> Suspected"],
            "ownership_changes": [],
            "new_evidence": ["A new exception stack was analyzed."],
            "unchanged_blockers": ["Production validation remains pending."],
        }
        result = review_presenter.render_review(
            request_text="Give me the standard review for 1-23700000001",
            snapshot=snapshot(),
            review_count=2,
            delta=delta,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("standard", result["mode"])
        self.assertLess(
            result["markdown"].index("Changed since last review"),
            result["markdown"].index("Primary problem"),
        )
        self.assertIn("## Key Technical Specification", result["markdown"])

    def test_dry_technical_request_uses_fixed_technical_spec(self):
        result = review_presenter.render_review(
            request_text="Dry technical review for 1-23700000001",
            snapshot=snapshot(),
            review_count=2,
            delta={},
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("technical", result["mode"])
        for field in (
            "Scope",
            "Environment",
            "Symptom",
            "Confirmed mechanism",
            "Production outcome",
            "Evidence gaps",
        ):
            self.assertIn(field, result["markdown"])
        for state in (
            "OBSERVED",
            "NOT OBSERVED",
            "NOT COLLECTED",
            "UNKNOWN",
            "NOT APPLICABLE",
        ):
            self.assertIn(state, result["markdown"])
        self.assertIn("Evidence basis", result["markdown"])
        self.assertNotIn("Executive Summary", result["markdown"])

    def test_full_report_is_explicit_and_evidence_register_is_last(self):
        result = review_presenter.render_review(
            request_text="Show the full report for 1-23700000001",
            snapshot=snapshot(),
            review_count=2,
            delta={},
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("full", result["mode"])
        self.assertIn("## Problem Lineage", result["markdown"])
        self.assertIn("## Technical Specification", result["markdown"])
        self.assertIn("## Timeline", result["markdown"])
        appendix = result["markdown"].index("## Appendix A — Evidence Register")
        self.assertGreater(appendix, result["markdown"].index("## Timeline"))
        self.assertNotIn("## ", result["markdown"][appendix + 3 :])

    def test_flow_request_renders_bounded_semantic_investigation_flow(self):
        data = copy.deepcopy(snapshot())
        data["visual_context"] = {
            "transitions": [
                {"label": "Outage observed", "state": "OBSERVED"},
                {"label": "Logs unavailable", "state": "BLOCKER"},
                {"label": "Heap limit hypothesis", "state": "SUSPECTED"},
                {"label": "Stack analyzed", "state": "CONFIRMED MECHANISM"},
                {"label": "Service restarted", "state": "PRODUCTION DEPLOYED"},
                {"label": "Long-term outcome unknown", "state": "PENDING"},
            ]
        }
        result = review_presenter.render_review(
            request_text="Draw the investigation progress flow chart",
            snapshot=data,
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("flow", result["mode"])
        self.assertEqual("progress-flow", result["visual"])
        self.assertIn("flowchart TD", result["markdown"])
        self.assertIn("not causal proof", result["markdown"])
        for semantic_class in ("observed", "blocker", "hypothesis", "confirmed", "pending"):
            self.assertIn(f"classDef {semantic_class}", result["markdown"])
        node_lines = [
            line for line in result["markdown"].splitlines() if line.strip().startswith("N") and "[\"" in line
        ]
        self.assertLessEqual(len(node_lines), 7)

    def test_recurring_events_add_event_comparison_to_standard_view(self):
        data = copy.deepcopy(snapshot())
        data["visual_context"] = {
            "recurrences": [
                {
                    "date": "2026-08-18",
                    "symptom": "Tomcat unavailable",
                    "change": "Service restart",
                    "outcome": "Recovered",
                },
                {
                    "date": "2026-08-20",
                    "symptom": "Tomcat unavailable again",
                    "change": "No new change evidenced",
                    "outcome": "Pending validation",
                },
            ]
        }
        result = review_presenter.render_review(
            request_text="Review 1-23700000001",
            snapshot=data,
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("standard", result["mode"])
        self.assertEqual("event-comparison", result["visual"])
        self.assertIn("## Event Comparison", result["markdown"])
        self.assertIn("Tomcat unavailable again", result["markdown"])

    def test_competing_hypotheses_use_claim_evidence_matrix(self):
        data = copy.deepcopy(snapshot())
        data["visual_context"] = {
            "hypotheses": [
                {
                    "claim": "Configured heap was too small",
                    "state": "SUSPECTED",
                    "evidence": "OutOfMemoryError was reported",
                    "validation": "Inspect JVM flags and GC evidence",
                },
                {
                    "claim": "Application memory leak",
                    "state": "NOT TESTED",
                    "evidence": "No heap trend was collected",
                    "validation": "Analyze heap dump retention paths",
                },
            ]
        }
        result = review_presenter.render_review(
            request_text="Review 1-23700000001",
            snapshot=data,
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("claim-evidence-matrix", result["visual"])
        self.assertIn("## Claim–Evidence Matrix", result["markdown"])
        self.assertIn("Configured heap was too small", result["markdown"])
        self.assertIn("Validation needed", result["markdown"])

    def test_cross_product_case_uses_component_swimlane(self):
        data = copy.deepcopy(snapshot())
        data["visual_context"] = {
            "components": [
                {"name": "EPM", "finding": "Tomcat unavailable", "state": "OBSERVED"},
                {"name": "POM", "finding": "REST API unavailable", "state": "OBSERVED"},
                {"name": "WAS", "finding": "Restarted during recovery", "state": "PRODUCTION DEPLOYED"},
            ],
            "handoffs": [
                {"from": "EPM", "to": "POM", "label": "reported dependency"},
                {"from": "POM", "to": "WAS", "label": "recovery sequence"},
            ],
        }
        result = review_presenter.render_review(
            request_text="Review 1-23700000001",
            snapshot=data,
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("component-swimlane", result["visual"])
        self.assertIn("## Component Swimlane", result["markdown"])
        self.assertIn("flowchart LR", result["markdown"])
        for component in ("EPM", "POM", "WAS"):
            self.assertIn(component, result["markdown"])
        self.assertIn("reported dependency", result["markdown"])

    def test_ownership_stall_uses_owner_action_deadline_table(self):
        data = copy.deepcopy(snapshot())
        data["visual_context"] = {
            "ownership_stall": True,
            "ownership": [
                {
                    "owner": "BBE",
                    "action": "Analyze the heap evidence",
                    "deadline": "not stated",
                    "status": "Pending",
                }
            ],
        }
        result = review_presenter.render_review(
            request_text="Review 1-23700000001",
            snapshot=data,
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("ownership-table", result["visual"])
        self.assertIn("## Ownership Checkpoint", result["markdown"])
        self.assertIn("| Owner | Action | Deadline | Status |", result["markdown"])
        self.assertIn("Analyze the heap evidence", result["markdown"])

    def test_complex_default_review_adds_progress_flow_automatically(self):
        data = copy.deepcopy(snapshot())
        data["visual_context"] = {
            "transitions": [
                {"label": "Outage observed", "state": "OBSERVED"},
                {"label": "Heap hypothesis", "state": "SUSPECTED"},
                {"label": "Validation pending", "state": "PENDING"},
            ]
        }
        result = review_presenter.render_review(
            request_text="Review 1-23700000001",
            snapshot=data,
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )

        self.assertEqual("standard", result["mode"])
        self.assertEqual("progress-flow", result["visual"])
        self.assertIn("## Investigation Progress", result["markdown"])
        self.assertIn("flowchart TD", result["markdown"])

    def test_chinese_explicit_requests_override_follow_up_default(self):
        data = copy.deepcopy(snapshot())
        data["visual_context"] = {
            "transitions": [
                {"label": "发现故障", "state": "OBSERVED"},
                {"label": "等待验证", "state": "PENDING"},
            ]
        }
        expectations = (
            ("输出完整报告", "full"),
            ("给我技术规格", "technical"),
            ("画调查进展流程图", "flow"),
        )
        for request, expected_mode in expectations:
            with self.subTest(request=request):
                result = review_presenter.render_review(
                    request_text=request,
                    snapshot=data,
                    review_count=2,
                    delta={},
                    record_path="C:/records/1-23700000001/record.md",
                )
                self.assertEqual(expected_mode, result["mode"])

    def test_visual_router_uses_documented_priority_order(self):
        data = copy.deepcopy(snapshot())
        data["visual_context"] = {
            "recurrences": [
                {"date": "D1", "symptom": "S1", "change": "C1", "outcome": "O1"},
                {"date": "D2", "symptom": "S2", "change": "C2", "outcome": "O2"},
            ],
            "hypotheses": [
                {"claim": "H1", "state": "SUSPECTED", "evidence": "E1", "validation": "V1"},
                {"claim": "H2", "state": "NOT TESTED", "evidence": "E2", "validation": "V2"},
            ],
            "components": [
                {"name": "A", "finding": "F1", "state": "OBSERVED"},
                {"name": "B", "finding": "F2", "state": "OBSERVED"},
                {"name": "C", "finding": "F3", "state": "OBSERVED"},
            ],
            "handoffs": [{"from": "A", "to": "B", "label": "handoff"}],
            "transitions": [
                {"label": "T1", "state": "OBSERVED"},
                {"label": "T2", "state": "SUSPECTED"},
                {"label": "T3", "state": "PENDING"},
            ],
            "ownership_stall": True,
            "ownership": [
                {"owner": "A", "action": "Act", "deadline": "D", "status": "Pending"}
            ],
        }

        result = review_presenter.render_review(
            request_text="Review 1-23700000001",
            snapshot=data,
            review_count=1,
            delta=None,
            record_path="C:/records/1-23700000001/record.md",
        )
        self.assertEqual("event-comparison", result["visual"])


if __name__ == "__main__":
    unittest.main()
