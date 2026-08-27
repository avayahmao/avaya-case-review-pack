#!/usr/bin/env python3
"""Validate, score, and summarize Avaya alarm-ticket audits."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


DIMENSIONS = (
    ("check", "Check", 1),
    ("cause", "Cause", 1),
    ("chronic", "Chronic", 1),
    ("plus", "PLUS", 2),
)
AUDIT_MAX_SCORE = sum(maximum for _, _, maximum in DIMENSIONS)


class AlarmAuditError(ValueError):
    """Raised when alarm-audit input cannot be normalized safely."""


def _text(value: Any, field: str, *, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if required and not value:
        raise AlarmAuditError(f"{field} must be non-empty")
    return value


def _header_key(value: Any) -> str:
    text = _text(value, "column", required=False).lstrip("\ufeff")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\(\s*\d+\s*[-–]\s*\d+\s*\)", "", text)
    text = re.sub(r"[\s_\-]+", " ", text.casefold()).strip()
    aliases = {
        "ticket id": "ticket_id",
        "case id": "ticket_id",
        "ticket": "ticket_id",
        "name": "name",
        "engineer": "name",
        "manager": "manager",
        "account tier": "account_tier",
        "tier": "account_tier",
        "alarm": "alarm",
        "check": "check",
        "cause": "cause",
        "chronic": "chronic",
        "plus": "plus",
        "score": "score",
        "comments": "comments",
        "comment": "comments",
    }
    return aliases.get(text, text.replace(" ", "_"))


def _integer(value: Any, field: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise AlarmAuditError(f"{field} must be an integer from 0 to {maximum}")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"\+?\d+", value.strip()):
        result = int(value.strip())
    else:
        raise AlarmAuditError(f"{field} must be an integer from 0 to {maximum}")
    if not 0 <= result <= maximum:
        raise AlarmAuditError(f"{field} must be an integer from 0 to {maximum}")
    return result


def normalize_entry(raw: dict[str, Any], index: int = 1) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AlarmAuditError(f"entry {index} must be an object")
    values = {_header_key(key): value for key, value in raw.items()}
    result = {
        "ticket_id": _text(values.get("ticket_id"), f"entry {index}.ticket_id"),
        "name": _text(values.get("name"), f"entry {index}.name"),
        "manager": _text(values.get("manager"), f"entry {index}.manager"),
        "account_tier": _text(values.get("account_tier"), f"entry {index}.account_tier", required=False),
        "alarm": _text(values.get("alarm"), f"entry {index}.alarm", required=False),
        "comments": _text(values.get("comments"), f"entry {index}.comments"),
    }
    for key, label, maximum in DIMENSIONS:
        result[key] = _integer(values.get(key), f"entry {index}.{label}", maximum)
    result["score"] = sum(result[key] for key, _, _ in DIMENSIONS)
    supplied_score = values.get("score")
    if supplied_score not in (None, ""):
        supplied = _integer(supplied_score, f"entry {index}.score", AUDIT_MAX_SCORE)
        if supplied != result["score"]:
            raise AlarmAuditError(
                f"entry {index}.score ({supplied}) does not equal the calculated total ({result['score']})"
            )
    plus_count = result["comments"].casefold().count("plus +1:")
    if plus_count != result["plus"]:
        raise AlarmAuditError(
            f"entry {index}.comments must include 'Plus +1:' once per PLUS point"
        )
    return result


def _split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith("\\|"):
        value = value[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in value:
        if character == "|" and not escaped:
            cells.append("".join(current).replace("\\|", "|").strip())
            current = []
            continue
        current.append(character)
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    cells.append("".join(current).replace("\\|", "|").strip())
    return cells


def _is_markdown_separator(cells: Iterable[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def parse_markdown(text: str) -> list[dict[str, Any]]:
    rows = [line for line in text.splitlines() if "|" in line]
    if len(rows) < 2:
        raise AlarmAuditError("Markdown input must contain a header and at least one row")
    headers = _split_markdown_row(rows[0])
    start = 2 if _is_markdown_separator(_split_markdown_row(rows[1])) else 1
    entries: list[dict[str, Any]] = []
    for line in rows[start:]:
        cells = _split_markdown_row(line)
        if not any(cells):
            continue
        if len(cells) != len(headers):
            raise AlarmAuditError("Markdown row has a different number of cells than the header")
        entries.append(dict(zip(headers, cells)))
    return entries


def parse_text(text: str, suffix: str = "") -> list[dict[str, Any]]:
    stripped = text.lstrip("\ufeff").strip()
    if not stripped:
        raise AlarmAuditError("Alarm audit input is empty")
    if suffix.casefold() == ".json" or stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AlarmAuditError(f"invalid JSON input: {exc.msg}") from exc
        if isinstance(parsed, dict):
            parsed = parsed.get("entries", parsed.get("audit", parsed.get("records")))
        if not isinstance(parsed, list):
            raise AlarmAuditError("JSON input must be an array or an object containing entries")
        return parsed
    if "|" in stripped and "---" in stripped:
        return parse_markdown(stripped)
    try:
        return list(csv.DictReader(stripped.splitlines()))
    except csv.Error as exc:
        raise AlarmAuditError(f"invalid CSV input: {exc}") from exc


def load_entries(path: str | Path) -> list[dict[str, Any]]:
    input_path = Path(path)
    try:
        text = input_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise AlarmAuditError(f"unable to read alarm audit input: {input_path}") from exc
    raw_entries = parse_text(text, input_path.suffix)
    if not raw_entries:
        raise AlarmAuditError("Alarm audit input contains no entries")
    return [normalize_entry(entry, index) for index, entry in enumerate(raw_entries, 1)]


def score_entry(
    *,
    ticket_id: str,
    name: str,
    manager: str,
    check: int,
    cause: int,
    chronic: int,
    plus: int,
    comments: str,
    account_tier: str = "",
    alarm: str = "",
) -> dict[str, Any]:
    return normalize_entry(
        {
            "Ticket ID": ticket_id,
            "Name": name,
            "Manager": manager,
            "Account Tier": account_tier,
            "Alarm": alarm,
            "Check": check,
            "Cause": cause,
            "Chronic": chronic,
            "PLUS": plus,
            "Comments": comments,
        }
    )


def _average(values: list[int]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _group_summary(entries: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        groups[entry[key]].append(entry)
    summaries = []
    for group, members in groups.items():
        summaries.append(
            {
                key: group,
                "managers": sorted({item["manager"] for item in members}),
                "engineers": sorted({item["name"] for item in members}),
                "reviews": len(members),
                "average_score": _average([item["score"] for item in members]),
                "average_check": _average([item["check"] for item in members]),
                "average_cause": _average([item["cause"] for item in members]),
                "average_chronic": _average([item["chronic"] for item in members]),
                "average_plus": _average([item["plus"] for item in members]),
            }
        )
    return sorted(summaries, key=lambda item: str(item[key]).casefold())


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        raise AlarmAuditError("cannot summarize an empty alarm audit")
    return {
        "reviews": len(entries),
        "max_score": AUDIT_MAX_SCORE,
        "average_score": _average([item["score"] for item in entries]),
        "minimum_score": min(item["score"] for item in entries),
        "maximum_score": max(item["score"] for item in entries),
        "average_check": _average([item["check"] for item in entries]),
        "average_cause": _average([item["cause"] for item in entries]),
        "average_chronic": _average([item["chronic"] for item in entries]),
        "average_plus": _average([item["plus"] for item in entries]),
        "by_name": _group_summary(entries, "name"),
        "by_manager": _group_summary(entries, "manager"),
    }


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def render_report(entries: list[dict[str, Any]], title: str = "Alarm Ticket Audit Report") -> str:
    summary = summarize(entries)
    lines = [
        f"# {title}",
        "",
        f"**Audits:** {summary['reviews']}  ",
        f"**Score scale:** 0-{summary['max_score']}  ",
        "**Scoring rule:** Check + Cause + Chronic + PLUS",
        "",
        "## Overall Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Average score | {summary['average_score']} |",
        f"| Minimum score | {summary['minimum_score']} |",
        f"| Maximum score | {summary['maximum_score']} |",
        f"| Average Check | {summary['average_check']} |",
        f"| Average Cause | {summary['average_cause']} |",
        f"| Average Chronic | {summary['average_chronic']} |",
        f"| Average PLUS | {summary['average_plus']} |",
        "",
    ]
    for heading, key, label in (("By Engineer", "name", "Engineer"), ("By Manager", "manager", "Manager")):
        lines.extend([
            f"## {heading}",
            "",
            f"| {label} | {'Manager(s)' if key == 'name' else 'Engineer(s)'} | Audits | Avg score | Avg Check | Avg Cause | Avg Chronic | Avg PLUS |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ])
        for item in summary[f"by_{key}"]:
            related = ", ".join(item["managers"] if key == "name" else item["engineers"])
            lines.append(
                f"| {_md(item[key])} | {_md(related)} | {item['reviews']} | {item['average_score']} | "
                f"{item['average_check']} | {item['average_cause']} | {item['average_chronic']} | {item['average_plus']} |"
            )
        lines.append("")
    lines.extend([
        "## Alarm Audit Entries",
        "",
        "| Ticket ID | Name | Manager | Account Tier | Alarm | Check | Cause | Chronic | PLUS | Score | Comments |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for entry in entries:
        lines.append(
            f"| {_md(entry['ticket_id'])} | {_md(entry['name'])} | {_md(entry['manager'])} | "
            f"{_md(entry['account_tier'] or 'not stated')} | {_md(entry['alarm'] or 'not stated')} | "
            f"{entry['check']} | {entry['cause']} | {entry['chronic']} | {entry['plus']} | "
            f"{entry['score']} | {_md(entry['comments'])} |"
        )
    return "\n".join(lines) + "\n"


def _json_report(entries: list[dict[str, Any]]) -> str:
    return json.dumps({"entries": entries, "summary": summarize(entries)}, ensure_ascii=False, indent=2) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "report"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--input", required=True, help="Alarm audit input (.md, .csv, or .json)")
        subparser.add_argument("--json", action="store_true", help="Emit normalized JSON")
    score = subparsers.add_parser("score", help="Score one alarm ticket")
    score.add_argument("--ticket-id", required=True)
    score.add_argument("--name", required=True)
    score.add_argument("--manager", required=True)
    score.add_argument("--account-tier", default="")
    score.add_argument("--alarm", default="")
    score.add_argument("--check", required=True, type=int)
    score.add_argument("--cause", required=True, type=int)
    score.add_argument("--chronic", required=True, type=int)
    score.add_argument("--plus", required=True, type=int)
    score.add_argument("--comments", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "score":
            print(json.dumps(score_entry(
                ticket_id=args.ticket_id,
                name=args.name,
                manager=args.manager,
                account_tier=args.account_tier,
                alarm=args.alarm,
                check=args.check,
                cause=args.cause,
                chronic=args.chronic,
                plus=args.plus,
                comments=args.comments,
            ), ensure_ascii=False, indent=2))
            return 0
        entries = load_entries(args.input)
        if args.command == "validate" and args.json:
            print(_json_report(entries), end="")
        elif args.command == "validate":
            print(f"Valid alarm audit input: {len(entries)} entries; maximum score {AUDIT_MAX_SCORE}.")
        elif args.json:
            print(_json_report(entries), end="")
        else:
            print(render_report(entries), end="")
        return 0
    except AlarmAuditError as exc:
        print(f"Alarm audit input error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
