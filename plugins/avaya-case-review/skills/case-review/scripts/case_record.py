#!/usr/bin/env python3
"""Durable per-case follow-up records and approved local knowledge overlays."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from review_presenter import PresentationError, render_review, validate_snapshot


SCHEMA_VERSION = 2
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,63}$")

RCA_STATES = {"Under Investigation", "Suspected", "Identified", "Validated", "unknown"}
MITIGATION_STATES = {
    "Proposed",
    "Lab Validated",
    "Production Deployed",
    "Production Outcome Confirmed",
    "None Active",
}
EVIDENCE_STATES = {
    "OBSERVED",
    "CONFIRMED MECHANISM",
    "SUSPECTED",
    "CONTRADICTED",
    "NOT TESTED",
    "PRODUCTION DEPLOYED",
    "OUTCOME CONFIRMED",
    "unknown",
}
LEARNING_STRENGTHS = {"Validated", "Identified", "Suspected"}
LEARNING_TYPES = {
    "verified-pattern",
    "diagnostic-heuristic",
    "negative-evidence",
    "operational-check",
}
DOMAINS = {
    "aes-cti-jtapi",
    "contact-center",
    "recording-wfo",
    "analytics-kubernetes",
    "security-vulnerability",
    "sip-voice-quality",
    "certificates-login-outage",
    "digital-channels",
    "ip-office",
    "log-collection",
}
CLOSED_STATUSES = {
    "closed",
    "resolved",
    "completed",
    "cancelled",
    "canceled",
}

CURRENT_FIELDS = (
    "title",
    "source",
    "official_status",
    "priority",
    "assignee",
    "primary_problem",
    "confirmed_finding",
    "unproven_or_contradicted",
    "rca_state",
    "mitigation_state",
    "production_outcome",
    "current_blocker",
    "next_action",
    "next_action_owner",
    "next_due",
)
STATE_FIELDS = (
    "official_status",
    "administrative_state",
    "primary_problem",
    "confirmed_finding",
    "unproven_or_contradicted",
    "rca_state",
    "mitigation_state",
    "production_outcome",
    "current_blocker",
)
OWNERSHIP_FIELDS = ("assignee", "next_action", "next_action_owner", "next_due")
COVERAGE_EQUALITIES = (
    ("case_notes_discovered", "case_notes_processed"),
    ("unique_threads_discovered", "threads_read_complete"),
    ("messages_expected", "messages_completed"),
    ("message_chunks_expected", "message_chunks_completed"),
    ("messages_completed", "body_hashes_verified"),
    ("threads_read_complete", "manifest_hashes_stable"),
)


class RecordError(ValueError):
    """Raised when a record operation would weaken the lifecycle contract."""


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{field} must be a non-empty ISO-8601 timestamp")
    normalized = value.strip()
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecordError(f"{field} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RecordError(f"{field} must include a timezone")
    return normalized


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_case_id(value: Any) -> str:
    if not isinstance(value, str) or not CASE_ID_PATTERN.fullmatch(value.strip()):
        raise RecordError("case_id contains unsupported characters")
    return value.strip().upper()


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    override = os.environ.get("CASE_REVIEW_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AvayaCaseReview"
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "avaya-case-review"
    return Path.home() / ".local" / "share" / "avaya-case-review"


def case_paths(data_dir: Path, case_id: str) -> dict[str, Path]:
    directory = data_dir / "case-records" / normalize_case_id(case_id)
    return {
        "directory": directory,
        "json": directory / "record.json",
        "markdown": directory / "record.md",
        "chat_output": directory / "chat-output.md",
        "chat_output_sha256": directory / "chat-output.sha256",
        "learning_json": directory / "learning-candidate.json",
        "learning_markdown": directory / "learning-candidate.md",
    }


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_chat_output(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + "\n"


def write_chat_output_artifact(
    paths: dict[str, Path], markdown: str
) -> dict[str, str]:
    normalized = normalize_chat_output(markdown)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    atomic_write(paths["chat_output"], normalized)
    atomic_write(
        paths["chat_output_sha256"],
        f"{digest}  {paths['chat_output'].name}\n",
    )
    return {
        "markdown": normalized,
        "chat_output": str(paths["chat_output"]),
        "chat_output_sha256": digest,
        "chat_output_sha256_file": str(paths["chat_output_sha256"]),
    }


def verify_final_output(
    case_id: str,
    candidate_path: str | Path,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    root = resolve_data_dir(data_dir)
    paths = case_paths(root, normalize_case_id(case_id))
    try:
        artifact = paths["chat_output"].read_text(encoding="utf-8")
        digest_line = paths["chat_output_sha256"].read_text(
            encoding="ascii"
        ).strip()
        candidate = Path(candidate_path).read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise RecordError(f"final output artifact not found: {exc.filename}") from exc
    normalized_artifact = normalize_chat_output(artifact)
    artifact_sha256 = hashlib.sha256(
        normalized_artifact.encode("utf-8")
    ).hexdigest()
    expected_digest_line = f"{artifact_sha256}  {paths['chat_output'].name}"
    if not hmac.compare_digest(digest_line, expected_digest_line):
        raise RecordError("stored chat-output artifact hash is invalid")
    normalized_candidate = normalize_chat_output(candidate)
    candidate_sha256 = hashlib.sha256(
        normalized_candidate.encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(artifact_sha256, candidate_sha256) or not hmac.compare_digest(
        normalized_artifact.encode("utf-8"), normalized_candidate.encode("utf-8")
    ):
        raise RecordError("final output integrity mismatch")
    return {
        "verified": True,
        "case_id": normalize_case_id(case_id),
        "artifact": str(paths["chat_output"]),
        "artifact_sha256": artifact_sha256,
        "candidate_sha256": candidate_sha256,
    }


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RecordError(f"record not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RecordError(f"invalid JSON record: {path}") from exc
    if not isinstance(value, dict):
        raise RecordError(f"JSON object required: {path}")
    return value


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def record_lock(directory: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".record.lock"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RecordError(f"case record is busy: {directory}")
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.rmdir()


def require_string_map(value: Any, field: str, required: tuple[str, ...]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RecordError(f"{field} must be an object")
    result: dict[str, str] = {}
    for key in required:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise RecordError(f"{field}.{key} must be a non-empty string; use unknown")
        result[key] = item.strip()
    return result


def validate_coverage(value: Any, snapshot_before: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecordError("coverage must be an object")
    coverage = dict(value)
    required_numbers = {
        key for pair in COVERAGE_EQUALITIES for key in pair
    } | {"record_ids_planned", "record_id_queries_completed"}
    for key in required_numbers:
        item = coverage.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise RecordError(f"coverage.{key} must be a non-negative integer")
    for left, right in COVERAGE_EQUALITIES:
        if coverage[left] != coverage[right]:
            raise RecordError(f"coverage incomplete: {left} != {right}")
    if coverage["record_ids_planned"] != 1 or coverage["record_id_queries_completed"] != 1:
        raise RecordError("coverage requires exactly one completed primary-ID query")
    if coverage.get("query_complete") is not True:
        raise RecordError("coverage.query_complete must be true")
    if coverage.get("snapshot_before") != snapshot_before:
        raise RecordError("coverage.snapshot_before must match snapshot_before")
    return coverage


def validate_evidence_digest(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise RecordError("evidence_digest must contain at least one decisive evidence item")
    evidence: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise RecordError(f"evidence_digest[{index}] must be an object")
        normalized = require_string_map(
            item, f"evidence_digest[{index}]", ("state", "date", "source", "fact")
        )
        if normalized["state"] not in EVIDENCE_STATES:
            raise RecordError(f"unsupported evidence state: {normalized['state']}")
        evidence.append(normalized)
    return evidence


def validate_presentation(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RecordError("presentation must be an object")
    required = (
        "technical_spec",
        "problem_lineage",
        "milestones",
        "timeline",
        "evidence_register",
        "visual_context",
    )
    for key in required:
        if key not in value:
            raise RecordError(f"presentation.{key} is required")
    if not isinstance(value["technical_spec"], dict):
        raise RecordError("presentation.technical_spec must be an object")
    if not isinstance(value["problem_lineage"], dict):
        raise RecordError("presentation.problem_lineage must be an object")
    for key in ("milestones", "timeline", "evidence_register"):
        if not isinstance(value[key], list):
            raise RecordError(f"presentation.{key} must be a list")
    if not value["evidence_register"]:
        raise RecordError("presentation.evidence_register must contain evidence")
    if not isinstance(value["visual_context"], dict):
        raise RecordError("presentation.visual_context must be an object")
    return dict(value)


def validate_update_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RecordError("update payload must be a JSON object")
    if payload.get("collection_status") != "complete":
        raise RecordError("case record is updated only after complete context collection")
    case_id = normalize_case_id(payload.get("case_id"))
    reviewed_at = validate_timestamp(payload.get("reviewed_at"), "reviewed_at")
    snapshot_before = validate_timestamp(payload.get("snapshot_before"), "snapshot_before")
    current = require_string_map(payload.get("current"), "current", CURRENT_FIELDS)
    if current["rca_state"] not in RCA_STATES:
        raise RecordError(f"unsupported RCA state: {current['rca_state']}")
    if current["mitigation_state"] not in MITIGATION_STATES:
        raise RecordError(f"unsupported mitigation state: {current['mitigation_state']}")
    coverage = validate_coverage(payload.get("coverage"), snapshot_before)
    if parse_timestamp(snapshot_before) > parse_timestamp(reviewed_at):
        raise RecordError("snapshot_before cannot be later than reviewed_at")
    evidence_digest = validate_evidence_digest(payload.get("evidence_digest"))
    presentation = validate_presentation(payload.get("presentation"))
    full_review = payload.get("full_review_markdown")
    if presentation is None:
        if not isinstance(full_review, str) or not full_review.strip():
            raise RecordError(
                "presentation or a non-empty full_review_markdown is required"
            )
    elif full_review is not None and not isinstance(full_review, str):
        raise RecordError("full_review_markdown must be a string when supplied")
    return {
        "case_id": case_id,
        "reviewed_at": reviewed_at,
        "snapshot_before": snapshot_before,
        "current": current,
        "coverage": coverage,
        "evidence_digest": evidence_digest,
        "presentation": presentation,
        "full_review_markdown": full_review.strip() if isinstance(full_review, str) else None,
    }


def derive_administrative_state(status: str, prior_state: str | None) -> str:
    normalized = status.strip().casefold()
    if normalized in CLOSED_STATUSES or any(
        normalized.startswith(f"{closed} ") or normalized.startswith(f"{closed}-")
        for closed in CLOSED_STATUSES
    ):
        return "closed"
    if normalized == "unknown":
        return "unknown"
    if prior_state in {"closed", "reopened"}:
        return "reopened"
    return "open"


def evidence_fingerprint(item: dict[str, str]) -> str:
    return canonical_hash({key: item[key] for key in ("date", "source", "fact")})


def describe_change(label: str, old: str, new: str) -> str:
    return f"{label}: {old} -> {new}"


def compute_delta(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    evidence_digest: list[dict[str, str]],
) -> dict[str, list[str]]:
    if previous is None:
        return {
            "state_changes": ["Initial case record created"],
            "ownership_changes": [],
            "new_evidence": [item["fact"] for item in evidence_digest],
            "unchanged_blockers": [],
        }
    state_changes = [
        describe_change(field.replace("_", " "), str(previous.get(field, "unknown")), current[field])
        for field in STATE_FIELDS
        if str(previous.get(field, "unknown")) != current[field]
    ]
    ownership_changes = [
        describe_change(field.replace("_", " "), str(previous.get(field, "unknown")), current[field])
        for field in OWNERSHIP_FIELDS
        if str(previous.get(field, "unknown")) != current[field]
    ]
    previous_evidence = previous.get("evidence_digest", [])
    previous_fingerprints = {
        evidence_fingerprint(item)
        for item in previous_evidence
        if isinstance(item, dict) and all(key in item for key in ("date", "source", "fact"))
    }
    new_evidence = [
        item["fact"]
        for item in evidence_digest
        if evidence_fingerprint(item) not in previous_fingerprints
    ]
    current_blocker = current["current_blocker"]
    unchanged_blockers = []
    if (
        current_blocker not in {"unknown", "not stated", "none"}
        and previous.get("current_blocker") == current_blocker
    ):
        unchanged_blockers.append(current_blocker)
    return {
        "state_changes": state_changes,
        "ownership_changes": ownership_changes,
        "new_evidence": new_evidence,
        "unchanged_blockers": unchanged_blockers,
    }


def md_inline(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def render_delta(delta: dict[str, list[str]]) -> str:
    labels = (
        ("State changes", "state_changes"),
        ("Ownership or checkpoint changes", "ownership_changes"),
        ("New decisive evidence", "new_evidence"),
        ("Unchanged blockers", "unchanged_blockers"),
    )
    lines: list[str] = []
    for label, key in labels:
        items = delta.get(key, [])
        if items:
            lines.append(f"- **{label}:** " + "; ".join(md_inline(item) for item in items))
    if not lines:
        lines.append("- No material state, evidence, ownership, or checkpoint change.")
    return "\n".join(lines)


def render_record(record: dict[str, Any]) -> str:
    current = record["current"]
    history = record["reviews"]
    latest_delta = history[-1]["delta"]
    learning = record["learning"]
    lines = [
        f"# Case Follow-up Record - {record['case_id']}",
        "",
        "> Comparison baseline only. Recollect CaseToMD and Gmail under a fresh complete snapshot before every follow-up; never use this record as case evidence.",
        "",
        f"**Created:** {record['created_at']}  ",
        f"**Last reviewed:** {record['updated_at']}  ",
        f"**Administrative state:** {current['administrative_state']}  ",
        f"**Learning option:** {learning['option']}",
        "",
        "## Current Case Card",
        "",
        "| Field | Current value |",
        "|---|---|",
    ]
    card_fields = (
        ("Title", "title"),
        ("Official status", "official_status"),
        ("Priority", "priority"),
        ("Assignee", "assignee"),
        ("Primary problem", "primary_problem"),
        ("Confirmed technical finding", "confirmed_finding"),
        ("Unproven or contradicted", "unproven_or_contradicted"),
        ("RCA state", "rca_state"),
        ("Mitigation state", "mitigation_state"),
        ("Production outcome", "production_outcome"),
        ("Current blocker", "current_blocker"),
        ("Next action", "next_action"),
        ("Next-action owner", "next_action_owner"),
        ("Next due", "next_due"),
    )
    lines.extend(f"| {label} | {md_inline(current[key])} |" for label, key in card_fields)
    lines.extend(["", "## Delta from Previous Review", "", render_delta(latest_delta), ""])
    lines.extend(
        [
            "## Follow-up History",
            "",
            "| Reviewed | Official status | RCA | Mitigation | Production outcome | Owner | Next checkpoint |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for review in history:
        snapshot = review["current"]
        next_checkpoint = f"{snapshot['next_action_owner']} / {snapshot['next_due']}"
        lines.append(
            "| "
            + " | ".join(
                md_inline(value)
                for value in (
                    review["reviewed_at"],
                    snapshot["official_status"],
                    snapshot["rca_state"],
                    snapshot["mitigation_state"],
                    snapshot["production_outcome"],
                    snapshot["assignee"],
                    next_checkpoint,
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Current Evidence Digest",
            "",
            "| Proof state | Date | Source | Decisive fact |",
            "|---|---|---|---|",
        ]
    )
    for item in current["evidence_digest"]:
        lines.append(
            "| "
            + " | ".join(
                md_inline(item[key]) for key in ("state", "date", "source", "fact")
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Closure Learning",
            "",
            f"- **Option:** {learning['option']}",
            f"- **Status:** {learning['status']}",
            f"- **Target:** {md_inline(learning.get('target', 'not selected'))}",
            "- Learning is drafted only on explicit request and applied only after explicit user approval.",
            "- Administrative closure does not establish validated RCA or confirmed production outcome.",
        ]
    )
    if record.get("current_report_markdown"):
        lines.extend(
            [
                "",
                "<details>",
                "<summary>Legacy full evidence-grounded review</summary>",
                "",
                record["current_report_markdown"],
                "",
                "</details>",
            ]
        )
    elif record.get("review_snapshot"):
        lines.extend(
            [
                "",
                "> Detailed technical, visual, and full views are generated on explicit request from the structured review snapshot.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def save_record(paths: dict[str, Path], record: dict[str, Any]) -> None:
    write_json(paths["json"], record)
    atomic_write(paths["markdown"], render_record(record))


def migrate_record(record: dict[str, Any]) -> bool:
    version = record.get("schema_version", 1)
    if version == SCHEMA_VERSION:
        return False
    if version != 1:
        raise RecordError(f"unsupported record schema version: {version}")
    legacy_report = record.pop("current_report_markdown", None)
    if isinstance(legacy_report, str) and legacy_report.strip():
        record["legacy_full_report_markdown"] = legacy_report
    record["schema_version"] = SCHEMA_VERSION
    record["migrated_at"] = utc_now()
    return True


def update_case_record(payload: Any, data_dir: str | Path | None = None) -> dict[str, Any]:
    normalized = validate_update_payload(payload)
    root = resolve_data_dir(data_dir)
    paths = case_paths(root, normalized["case_id"])
    with record_lock(paths["directory"]):
        existing = read_json(paths["json"]) if paths["json"].exists() else None
        migrated = migrate_record(existing) if existing else False
        if existing and existing.get("case_id") != normalized["case_id"]:
            raise RecordError("existing record case ID does not match the update")
        review_key = canonical_hash(
            {
                "case_id": normalized["case_id"],
                "snapshot_before": normalized["snapshot_before"],
                "current": normalized["current"],
                "coverage": normalized["coverage"],
                "evidence_digest": normalized["evidence_digest"],
                "presentation": normalized["presentation"],
            }
        )
        if existing and any(item.get("review_key") == review_key for item in existing["reviews"]):
            if migrated:
                save_record(paths, existing)
            return {
                "updated": False,
                "reason": "duplicate review snapshot",
                "record_json": str(paths["json"]),
                "record_markdown": str(paths["markdown"]),
                "delta": existing["reviews"][-1]["delta"],
                "review_count": len(existing["reviews"]),
                "is_first_review": len(existing["reviews"]) == 1,
            }

        if existing:
            if parse_timestamp(normalized["reviewed_at"]) < parse_timestamp(existing["updated_at"]):
                raise RecordError("reviewed_at cannot move the case record backwards")
            latest_snapshot = existing["reviews"][-1]["snapshot_before"]
            if parse_timestamp(normalized["snapshot_before"]) <= parse_timestamp(latest_snapshot):
                raise RecordError("a follow-up requires a newer fresh snapshot_before")

        previous = existing.get("current") if existing else None
        prior_state = previous.get("administrative_state") if previous else None
        current = dict(normalized["current"])
        current["administrative_state"] = derive_administrative_state(
            current["official_status"], prior_state
        )
        current["evidence_digest"] = normalized["evidence_digest"]
        review_snapshot = None
        if normalized["presentation"] is not None:
            review_snapshot = {
                "case_id": normalized["case_id"],
                "current": current,
                **normalized["presentation"],
            }
            try:
                validate_snapshot(review_snapshot)
            except PresentationError as exc:
                raise RecordError(str(exc)) from exc
        delta = compute_delta(previous, current, normalized["evidence_digest"])
        review = {
            "review_key": review_key,
            "reviewed_at": normalized["reviewed_at"],
            "snapshot_before": normalized["snapshot_before"],
            "coverage": normalized["coverage"],
            "current": current,
            "delta": delta,
        }
        now = utc_now()
        if existing:
            record = existing
            record["updated_at"] = normalized["reviewed_at"]
            record["current"] = current
            if review_snapshot is not None:
                record["schema_version"] = SCHEMA_VERSION
                record["review_snapshot"] = review_snapshot
                record.pop("current_report_markdown", None)
            elif normalized["full_review_markdown"] is not None:
                record["current_report_markdown"] = normalized["full_review_markdown"]
            record["reviews"].append(review)
        else:
            record = {
                "schema_version": SCHEMA_VERSION,
                "case_id": normalized["case_id"],
                "created_at": normalized["reviewed_at"],
                "updated_at": normalized["reviewed_at"],
                "written_at": now,
                "current": current,
                "reviews": [review],
                "learning": {
                    "option": "not_available",
                    "status": "not_started",
                    "target": "not selected",
                },
            }
            if review_snapshot is not None:
                record["review_snapshot"] = review_snapshot
            elif normalized["full_review_markdown"] is not None:
                record["current_report_markdown"] = normalized["full_review_markdown"]
        record["written_at"] = now
        record["learning"]["option"] = (
            "available" if current["administrative_state"] == "closed" else "not_available"
        )
        if current["administrative_state"] == "reopened":
            if record["learning"]["status"] == "drafted":
                record["learning"]["status"] = "paused_reopened"
            elif record["learning"]["status"] == "applied":
                suspend_applied_learning(record)
                record["learning"]["status"] = "review_required_reopened"
        save_record(paths, record)
    return {
        "updated": True,
        "record_json": str(paths["json"]),
        "record_markdown": str(paths["markdown"]),
        "administrative_state": current["administrative_state"],
        "learning_option": record["learning"]["option"],
        "delta": delta,
        "review_count": len(record["reviews"]),
        "is_first_review": len(record["reviews"]) == 1,
    }


def present_case_record(
    case_id: str,
    request_text: str,
    data_dir: str | Path | None = None,
    write_chat_output: bool = False,
) -> dict[str, Any]:
    root = resolve_data_dir(data_dir)
    paths = case_paths(root, normalize_case_id(case_id))
    with record_lock(paths["directory"]):
        record = read_json(paths["json"])
        if record.get("schema_version") != SCHEMA_VERSION or not isinstance(
            record.get("review_snapshot"), dict
        ):
            raise RecordError(
                "record must be refreshed with a structured v2 review before presentation"
            )
        result = render_review(
            request_text=request_text,
            snapshot=record["review_snapshot"],
            review_count=len(record["reviews"]),
            delta=record["reviews"][-1]["delta"],
            record_path=str(paths["markdown"]),
        )
        artifact = (
            write_chat_output_artifact(paths, result["markdown"])
            if write_chat_output
            else {}
        )
    return {
        **result,
        **artifact,
        "record_json": str(paths["json"]),
        "record_markdown": str(paths["markdown"]),
        "review_count": len(record["reviews"]),
    }


def validate_learning_candidate(candidate: Any, case_id: str) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise RecordError("learning candidate must be a JSON object")
    candidate_case_id = normalize_case_id(candidate.get("case_id"))
    if candidate_case_id != case_id:
        raise RecordError("learning candidate case ID does not match the record")
    domain = candidate.get("domain")
    if domain not in DOMAINS:
        raise RecordError(f"unsupported learning domain: {domain}")
    learning_type = candidate.get("learning_type")
    if learning_type not in LEARNING_TYPES:
        raise RecordError(f"unsupported learning type: {learning_type}")
    evidence_strength = candidate.get("evidence_strength")
    if evidence_strength not in LEARNING_STRENGTHS:
        raise RecordError(f"unsupported evidence strength: {evidence_strength}")
    if candidate.get("customer_data_removed") is not True:
        raise RecordError("customer_data_removed must be true")
    title = candidate.get("title")
    finding = candidate.get("generalized_finding")
    if not isinstance(title, str) or not title.strip():
        raise RecordError("learning title must be non-empty")
    if not isinstance(finding, str) or not finding.strip():
        raise RecordError("generalized_finding must be non-empty")
    list_fields = (
        "activation_conditions",
        "diagnostic_steps",
        "disconfirming_signals",
        "limitations",
    )
    normalized_lists: dict[str, list[str]] = {}
    for field in list_fields:
        values = candidate.get(field)
        if not isinstance(values, list) or not values:
            raise RecordError(f"{field} must be a non-empty list")
        if not all(isinstance(item, str) and item.strip() for item in values):
            raise RecordError(f"{field} items must be non-empty strings")
        normalized_lists[field] = [item.strip() for item in values]
    generalized_text = " ".join(
        [title, finding] + [item for field in list_fields for item in normalized_lists[field]]
    )
    if case_id.casefold() in generalized_text.casefold():
        raise RecordError("remove the case ID from generalized learning text")
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "domain": domain,
        "title": title.strip(),
        "learning_type": learning_type,
        "evidence_strength": evidence_strength,
        "generalized_finding": finding.strip(),
        **normalized_lists,
        "customer_data_removed": True,
    }


def render_learning_candidate(candidate: dict[str, Any], record: dict[str, Any]) -> str:
    lines = [
        f"# Learning Candidate - {record['case_id']}",
        "",
        f"**Domain:** {candidate['domain']}  ",
        f"**Type:** {candidate['learning_type']}  ",
        f"**Evidence strength:** {candidate['evidence_strength']}  ",
        f"**Closed review:** {record['updated_at']}",
        "",
        f"## {candidate['title']}",
        "",
        candidate["generalized_finding"],
    ]
    for heading, field in (
        ("Activation Conditions", "activation_conditions"),
        ("Diagnostic Steps", "diagnostic_steps"),
        ("Disconfirming Signals", "disconfirming_signals"),
        ("Limitations", "limitations"),
    ):
        lines.extend(["", f"### {heading}", ""])
        lines.extend(f"- {item}" for item in candidate[field])
    lines.extend(
        [
            "",
            "> Draft only. Apply to the local domain-knowledge overlay only after explicit user approval.",
            "",
        ]
    )
    return "\n".join(lines)


def draft_learning_candidate(
    candidate: Any, data_dir: str | Path | None = None
) -> dict[str, Any]:
    root = resolve_data_dir(data_dir)
    case_id = normalize_case_id(candidate.get("case_id") if isinstance(candidate, dict) else None)
    paths = case_paths(root, case_id)
    with record_lock(paths["directory"]):
        record = read_json(paths["json"])
        if record["current"]["administrative_state"] != "closed":
            raise RecordError("learning can be drafted only from an administratively closed record")
        normalized = validate_learning_candidate(candidate, case_id)
        normalized["source_reviewed_at"] = record["updated_at"]
        normalized["drafted_at"] = utc_now()
        normalized["fingerprint"] = canonical_hash(
            {key: value for key, value in normalized.items() if key not in {"drafted_at", "fingerprint"}}
        )
        write_json(paths["learning_json"], normalized)
        atomic_write(paths["learning_markdown"], render_learning_candidate(normalized, record))
        record["learning"].update(
            {
                "option": "available",
                "status": "drafted",
                "target": normalized["domain"],
                "candidate": str(paths["learning_markdown"]),
            }
        )
        save_record(paths, record)
    return {
        "drafted": True,
        "candidate_json": str(paths["learning_json"]),
        "candidate_markdown": str(paths["learning_markdown"]),
        "requires_user_approval": True,
    }


def render_overlay_entry(candidate: dict[str, Any], record: dict[str, Any]) -> str:
    start_marker = f"<!-- learning:{candidate['fingerprint']}:start -->"
    end_marker = f"<!-- learning:{candidate['fingerprint']}:end -->"
    lines = [
        start_marker,
        f"## {candidate['title']}",
        "",
        "- **Approval state:** active",
        f"- **Evidence strength:** {candidate['evidence_strength']}",
        f"- **Learning type:** {candidate['learning_type']}",
        f"- **Generalized finding:** {candidate['generalized_finding']}",
        "- **Activation conditions:**",
    ]
    lines.extend(f"  - {item}" for item in candidate["activation_conditions"])
    lines.append("- **Diagnostic steps:**")
    lines.extend(f"  - {item}" for item in candidate["diagnostic_steps"])
    lines.append("- **Disconfirming signals:**")
    lines.extend(f"  - {item}" for item in candidate["disconfirming_signals"])
    lines.append("- **Limitations:**")
    lines.extend(f"  - {item}" for item in candidate["limitations"])
    lines.extend(
        [
            f"- **Provenance:** {record['case_id']}, closed review {candidate['source_reviewed_at']}",
            "",
            end_marker,
            "",
        ]
    )
    return "\n".join(lines)


def set_overlay_entry_state(content: str, fingerprint: str, state: str) -> tuple[str, bool]:
    start_marker = f"<!-- learning:{fingerprint}:start -->"
    end_marker = f"<!-- learning:{fingerprint}:end -->"
    start = content.find(start_marker)
    if start < 0:
        return content, False
    end = content.find(end_marker, start)
    if end < 0:
        return content, False
    section = content[start:end]
    replacement = f"- **Approval state:** {state}"
    updated_section, count = re.subn(
        r"- \*\*Approval state:\*\* (?:active|suspended)",
        replacement,
        section,
        count=1,
    )
    if count == 0 or updated_section == section:
        return content, False
    return content[:start] + updated_section + content[end:], True


def suspend_applied_learning(record: dict[str, Any]) -> None:
    learning = record.get("learning", {})
    overlay_value = learning.get("overlay")
    fingerprint = learning.get("fingerprint")
    if not isinstance(overlay_value, str) or not isinstance(fingerprint, str):
        return
    overlay = Path(overlay_value)
    if not overlay.is_file():
        return
    content = overlay.read_text(encoding="utf-8")
    updated, changed = set_overlay_entry_state(content, fingerprint, "suspended")
    if changed:
        atomic_write(overlay, updated)


def apply_learning(
    case_id: str,
    approved_by_user: bool,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not approved_by_user:
        raise RecordError("explicit user approval is required to apply domain learning")
    root = resolve_data_dir(data_dir)
    paths = case_paths(root, normalize_case_id(case_id))
    with record_lock(paths["directory"]):
        record = read_json(paths["json"])
        if record["current"]["administrative_state"] != "closed":
            raise RecordError("learning can be applied only while the record is closed")
        candidate = read_json(paths["learning_json"])
        overlay = root / "domain-knowledge" / f"{candidate['domain']}.md"
        start_marker = f"<!-- learning:{candidate['fingerprint']}:start -->"
        if overlay.exists():
            content = overlay.read_text(encoding="utf-8")
        else:
            content = (
                f"# Approved Local Domain Knowledge - {candidate['domain']}\n\n"
                "> Local, user-approved overlay. Treat as diagnostic guidance, never as case-specific proof. Ignore entries whose Approval state is suspended.\n\n"
            )
        reason = "already present"
        applied = start_marker not in content
        if applied:
            if not content.endswith("\n"):
                content += "\n"
            content += render_overlay_entry(candidate, record)
            atomic_write(overlay, content)
            reason = "applied"
        else:
            reactivated, changed = set_overlay_entry_state(
                content, candidate["fingerprint"], "active"
            )
            if changed:
                atomic_write(overlay, reactivated)
                applied = True
                reason = "reactivated"
        record["learning"].update(
            {
                "option": "available",
                "status": "applied",
                "target": candidate["domain"],
                "overlay": str(overlay),
                "fingerprint": candidate["fingerprint"],
                "applied_at": utc_now(),
            }
        )
        save_record(paths, record)
    return {
        "applied": applied,
        "reason": reason,
        "domain": candidate["domain"],
        "overlay": str(overlay),
        "record_markdown": str(paths["markdown"]),
    }


def load_payload(path: str) -> dict[str, Any]:
    return read_json(Path(path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", help="Override the persistent data directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update", help="Create or update a case record")
    update.add_argument("--input", required=True, help="Complete-review JSON payload")

    show = subparsers.add_parser("show", help="Print an existing Markdown record")
    show.add_argument("--case-id", required=True)

    paths = subparsers.add_parser("paths", help="Print record paths and existence")
    paths.add_argument("--case-id", required=True)

    present = subparsers.add_parser("present", help="Render a stored structured review")
    present.add_argument("--case-id", required=True)
    present.add_argument("--request", required=True, help="Original user request text")
    present.add_argument(
        "--markdown-only",
        action="store_true",
        help="Write the canonical chat artifact and print only its Markdown",
    )

    verify = subparsers.add_parser(
        "verify-final", help="Verify a candidate final response against the chat artifact"
    )
    verify.add_argument("--case-id", required=True)
    verify.add_argument("--input", required=True, help="UTF-8 candidate Markdown")

    draft = subparsers.add_parser("draft-learning", help="Draft closed-case learning")
    draft.add_argument("--input", required=True, help="Learning-candidate JSON payload")

    apply = subparsers.add_parser("apply-learning", help="Apply an approved learning candidate")
    apply.add_argument("--case-id", required=True)
    apply.add_argument("--approved-by-user", action="store_true")

    knowledge = subparsers.add_parser("knowledge-path", help="Locate a local domain overlay")
    knowledge.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="strict")
    parser = build_parser()
    args = parser.parse_args()
    try:
        root = resolve_data_dir(args.data_dir)
        if args.command == "update":
            result = update_case_record(load_payload(args.input), root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "show":
            paths = case_paths(root, args.case_id)
            print(paths["markdown"].read_text(encoding="utf-8"), end="")
        elif args.command == "paths":
            paths = case_paths(root, args.case_id)
            print(
                json.dumps(
                    {
                        "record_json": str(paths["json"]),
                        "record_markdown": str(paths["markdown"]),
                        "exists": paths["json"].exists() and paths["markdown"].exists(),
                    },
                    indent=2,
                )
            )
        elif args.command == "present":
            result = present_case_record(
                args.case_id,
                args.request,
                root,
                write_chat_output=args.markdown_only,
            )
            if args.markdown_only:
                print(result["markdown"], end="")
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "verify-final":
            result = verify_final_output(args.case_id, args.input, root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "draft-learning":
            result = draft_learning_candidate(load_payload(args.input), root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "apply-learning":
            result = apply_learning(args.case_id, args.approved_by_user, root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "knowledge-path":
            overlay = root / "domain-knowledge" / f"{args.domain}.md"
            print(json.dumps({"path": str(overlay), "exists": overlay.exists()}, indent=2))
        else:
            parser.error("unsupported command")
    except (PresentationError, RecordError, OSError) as exc:
        parser.exit(2, f"case-record error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
