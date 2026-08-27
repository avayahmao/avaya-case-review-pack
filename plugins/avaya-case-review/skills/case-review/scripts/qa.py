#!/usr/bin/env python3
"""Validate, score, and summarize case-review QA assessments."""

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
    ("diagnostic_solution", "Diagnostic & Solution", 5),
    ("service_communication", "Service & Communication", 3),
    ("plus", "Plus", 5),
)
QA_MAX_SCORE = sum(maximum for _, _, maximum in DIMENSIONS)
REQUIRED_FIELDS = ("name", "manager", "case_id")


class QAError(ValueError):
    """Raised when QA input cannot be normalized safely."""


def _text(value: Any, field: str, *, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if required and not value:
        raise QAError(f"{field} must be non-empty")
    return value


def _header_key(value: Any) -> str:
    text = _text(value, "column", required=False).lstrip("\ufeff")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\(\s*\d+\s*[-–]\s*\d+\s*\)", "", text)
    text = re.sub(r"[\s_\-]+", " ", text.casefold()).strip()
    aliases = {
        "name": "name",
        "engineer": "name",
        "agent": "name",
        "manager": "manager",
        "case id": "case_id",
        "case": "case_id",
        "product": "product",
        "diagnostic & solution": "diagnostic_solution",
        "diagnostic and solution": "diagnostic_solution",
        "diagnostic solution": "diagnostic_solution",
        "service & communication": "service_communication",
        "service and communication": "service_communication",
        "service communication": "service_communication",
        "plus": "plus",
        "score": "score",
        "comments": "comments",
        "comment": "comments",
    }
    return aliases.get(text, text.replace(" ", "_"))


def _integer(value: Any, field: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise QAError(f"{field} must be an integer from 0 to {maximum}")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"\+?\d+", value.strip()):
        result = int(value.strip())
    else:
        raise QAError(f"{field} must be an integer from 0 to {maximum}")
    if not 0 <= result <= maximum:
        raise QAError(f"{field} must be an integer from 0 to {maximum}")
    return result


def normalize_entry(raw: dict[str, Any], index: int = 1) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise QAError(f"entry {index} must be an object")
    values = {_header_key(key): value for key, value in raw.items()}
    result = {
        "name": _text(values.get("name"), f"entry {index}.name"),
        "manager": _text(values.get("manager"), f"entry {index}.manager"),
        "case_id": _text(values.get("case_id"), f"entry {index}.case_id"),
        "product": _text(values.get("product"), f"entry {index}.product", required=False),
        "comments": _text(values.get("comments"), f"entry {index}.comments", required=False),
    }
    for key, label, maximum in DIMENSIONS:
        result[key] = _integer(values.get(key), f"entry {index}.{label}", maximum)
    result["score"] = sum(result[key] for key, _, _ in DIMENSIONS)
    supplied_score = values.get("score")
    if supplied_score not in (None, ""):
        supplied = _integer(supplied_score, f"entry {index}.score", QA_MAX_SCORE)
        if supplied != result["score"]:
            raise QAError(
                f"entry {index}.score ({supplied}) does not equal the calculated total ({result['score']})"
            )
    comment_reasons = []
    if result["diagnostic_solution"] < 5:
        comment_reasons.append("the Diagnostic & Solution deduction")
    if result["service_communication"] < 3:
        comment_reasons.append("the Service & Communication deduction")
    if result["plus"] > 0:
        comment_reasons.append("the Plus award")
    if comment_reasons and not result["comments"]:
        raise QAError(
            f"entry {index}.comments must explain " + ", ".join(comment_reasons)
        )
    comment = result["comments"].casefold()
    if result["diagnostic_solution"] < 5:
        expected = f"diagnostic & solution -{5 - result['diagnostic_solution']}:"
        if expected not in comment:
            raise QAError(f"entry {index}.comments must include '{expected}'")
    if result["service_communication"] < 3:
        expected = f"service & communication -{3 - result['service_communication']}:"
        if expected not in comment:
            raise QAError(f"entry {index}.comments must include '{expected}'")
    if result["plus"] > 0:
        expected = "plus +1:"
        if comment.count(expected) != result["plus"]:
            raise QAError(
                f"entry {index}.comments must include '{expected}' once per Plus point"
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
        raise QAError("Markdown input must contain a header and at least one row")
    headers = _split_markdown_row(rows[0])
    start = 1
    separator = _split_markdown_row(rows[1])
    if _is_markdown_separator(separator):
        start = 2
    entries: list[dict[str, Any]] = []
    for line in rows[start:]:
        cells = _split_markdown_row(line)
        if not any(cells):
            continue
        if len(cells) != len(headers):
            raise QAError("Markdown row has a different number of cells than the header")
        entries.append(dict(zip(headers, cells)))
    return entries


def parse_text(text: str, suffix: str = "") -> list[dict[str, Any]]:
    stripped = text.lstrip("\ufeff").strip()
    if not stripped:
        raise QAError("QA input is empty")
    if suffix.casefold() == ".json" or stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise QAError(f"invalid JSON input: {exc.msg}") from exc
        if isinstance(parsed, dict):
            parsed = parsed.get("entries", parsed.get("qa", parsed.get("records")))
        if not isinstance(parsed, list):
            raise QAError("JSON input must be an array or an object containing entries")
        return parsed
    if "|" in stripped and "---" in stripped:
        return parse_markdown(stripped)
    try:
        return list(csv.DictReader(stripped.splitlines()))
    except csv.Error as exc:
        raise QAError(f"invalid CSV input: {exc}") from exc


def load_entries(path: str | Path) -> list[dict[str, Any]]:
    input_path = Path(path)
    try:
        text = input_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise QAError(f"unable to read QA input: {input_path}") from exc
    raw_entries = parse_text(text, input_path.suffix)
    if not raw_entries:
        raise QAError("QA input contains no entries")
    return [normalize_entry(entry, index) for index, entry in enumerate(raw_entries, 1)]


def score_entry(
    *,
    name: str,
    manager: str,
    case_id: str,
    diagnostic_solution: int,
    service_communication: int,
    plus: int,
    product: str = "",
    comments: str = "",
) -> dict[str, Any]:
    return normalize_entry(
        {
            "Name": name,
            "Manager": manager,
            "Case ID": case_id,
            "Product": product,
            "Diagnostic & Solution": diagnostic_solution,
            "Service & Communication": service_communication,
            "Plus": plus,
            "comments": comments,
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
                "average_diagnostic_solution": _average([item["diagnostic_solution"] for item in members]),
                "average_service_communication": _average([item["service_communication"] for item in members]),
                "average_plus": _average([item["plus"] for item in members]),
            }
        )
    return sorted(summaries, key=lambda item: str(item[key]).casefold())


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        raise QAError("cannot summarize an empty QA set")
    return {
        "reviews": len(entries),
        "max_score": QA_MAX_SCORE,
        "average_score": _average([item["score"] for item in entries]),
        "minimum_score": min(item["score"] for item in entries),
        "maximum_score": max(item["score"] for item in entries),
        "average_diagnostic_solution": _average([item["diagnostic_solution"] for item in entries]),
        "average_service_communication": _average([item["service_communication"] for item in entries]),
        "average_plus": _average([item["plus"] for item in entries]),
        "by_name": _group_summary(entries, "name"),
        "by_manager": _group_summary(entries, "manager"),
    }


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def render_report(entries: list[dict[str, Any]], title: str = "Case Review QA Report") -> str:
    summary = summarize(entries)
    lines = [
        f"# {title}",
        "",
        f"**Reviews:** {summary['reviews']}  ",
        f"**Score scale:** 0-{summary['max_score']}  ",
        "**Scoring rule:** Diagnostic & Solution + Service & Communication + Plus",
        "",
        "## Overall Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Average score | {summary['average_score']} |",
        f"| Minimum score | {summary['minimum_score']} |",
        f"| Maximum score | {summary['maximum_score']} |",
        f"| Average Diagnostic & Solution | {summary['average_diagnostic_solution']} |",
        f"| Average Service & Communication | {summary['average_service_communication']} |",
        f"| Average Plus | {summary['average_plus']} |",
        "",
    ]
    for heading, key, label in (
        ("By Engineer", "name", "Engineer"),
        ("By Manager", "manager", "Manager"),
    ):
        lines.extend(
            [
                f"## {heading}",
                "",
                f"| {label} | {'Manager(s)' if key == 'name' else 'Engineer(s)'} | Reviews | Avg score | Avg Diagnostic & Solution | Avg Service & Communication | Avg Plus |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary[f"by_{key}"]:
            related_text = ", ".join(item["managers"] if key == "name" else item["engineers"])
            lines.append(
                f"| {_md(item[key])} | {_md(related_text)} | {item['reviews']} | "
                f"{item['average_score']} | {item['average_diagnostic_solution']} | "
                f"{item['average_service_communication']} | {item['average_plus']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## QA Entries",
            "",
            "| Name | Manager | Case ID | Product | Diagnostic & Solution | Service & Communication | Plus | Score | Comments |",
            "|---|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for entry in entries:
        lines.append(
            f"| {_md(entry['name'])} | {_md(entry['manager'])} | {_md(entry['case_id'])} | "
            f"{_md(entry['product'] or 'not stated')} | {entry['diagnostic_solution']} | "
            f"{entry['service_communication']} | {entry['plus']} | {entry['score']} | {_md(entry['comments'])} |"
        )
    return "\n".join(lines) + "\n"


def _json_report(entries: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"entries": entries, "summary": summarize(entries)},
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("validate", "report"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--input", required=True, help="QA input file (.md, .csv, or .json)")
        subparser.add_argument("--json", action="store_true", help="Emit normalized JSON")
    score = subparsers.add_parser("score", help="Score one QA entry")
    score.add_argument("--name", required=True)
    score.add_argument("--manager", required=True)
    score.add_argument("--case-id", required=True)
    score.add_argument("--diagnostic-solution", required=True, type=int)
    score.add_argument("--service-communication", required=True, type=int)
    score.add_argument("--plus", required=True, type=int)
    score.add_argument("--product", default="")
    score.add_argument("--comments", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "score":
            print(json.dumps(score_entry(
                name=args.name,
                manager=args.manager,
                case_id=args.case_id,
                diagnostic_solution=args.diagnostic_solution,
                service_communication=args.service_communication,
                plus=args.plus,
                product=args.product,
                comments=args.comments,
            ), ensure_ascii=False, indent=2))
            return 0
        entries = load_entries(args.input)
        if args.command == "validate" and args.json:
            print(_json_report(entries), end="")
        elif args.command == "validate":
            print(f"Valid QA input: {len(entries)} entries; maximum score {QA_MAX_SCORE}.")
        elif args.json:
            print(_json_report(entries), end="")
        else:
            print(render_report(entries), end="")
        return 0
    except QAError as exc:
        print(f"QA input error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
