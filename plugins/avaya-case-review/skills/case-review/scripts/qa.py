#!/usr/bin/env python3
"""Validate, score, and summarize case-review QA assessments."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from io import StringIO
from pathlib import Path
from typing import Any, Iterable


DIMENSIONS = (
    ("diagnostic_solution", "Diagnostic & Solution", 5),
    ("service_communication", "Service & Communication", 3),
    ("plus", "Plus", 5),
)
QA_MAX_SCORE = sum(maximum for _, _, maximum in DIMENSIONS)
REQUIRED_FIELDS = ("name", "manager", "case_id")
LEGACY_COLUMNS = (
    "Name",
    "Manager",
    "Case ID",
    "Product",
    "Auditor",
    "Diagnostic & Solution",
    "Service & Communication",
    "Plus",
    "score",
    "Problem",
    "efforts",
    "comments",
)
CURRENT_COLUMNS = (
    "Name",
    "Manager",
    "Case ID",
    "Product",
    "Auditor",
    "Reviewability",
    "Reviewability Reason",
    "Diagnostic & Solution",
    "Service & Communication",
    "Plus",
    "score",
    "Problem",
    "efforts",
    "comments",
)
NOT_REVIEWABLE_VALUES = {
    "n/a",
    "na",
    "non reviewable",
    "not applicable",
    "not reviewable",
    "unscored",
}
REVIEWABLE_VALUES = {"reviewable", "scored"}
PLUS_ITEMS = (
    "Code Defect Discovery",
    "Infrastructure & Hypervisor Isolation",
    "Cross-Product Integration",
    "Customer Pressure & Ownership",
    "Scope Extension",
    "Trace Package Hygiene",
)
VAGUE_RATIONALES = {
    "convinced conclusion",
    "fair enough",
    "job done",
    "knowledge",
    "provided info",
    "solved quickly",
    "sounds good",
    "swift solution",
}
SCORING_TOKEN_PATTERN = re.compile(
    r"(?:diagnostic\s*&\s*solution\s*-\s*\d+\s*:?)|"
    r"(?:service\s*&\s*communication\s*-\s*\d+\s*:?)|"
    r"(?:plus\s*\+\s*\d+\s*:?)",
    re.IGNORECASE,
)


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


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _source_login(value: Any, field: str, *, required: bool = True) -> str:
    login = _text(value, field, required=required)
    if login and (login != login.casefold() or any(character.isspace() for character in login)):
        raise QAError(f"{field} must be a lowercase source login or 'unknown'")
    return login


def _reviewability(value: Any, field: str) -> str:
    raw = _text(value, field, required=False)
    if not raw:
        return "Reviewable"
    normalized = re.sub(r"[\s_-]+", " ", raw.casefold()).strip()
    if normalized in REVIEWABLE_VALUES:
        return "Reviewable"
    if normalized in NOT_REVIEWABLE_VALUES:
        return "Not Reviewable"
    raise QAError(
        f"{field} must be 'Reviewable' or 'Not Reviewable' "
        "(accepted unscored variants: N/A, NA, or unscored)"
    )


def _header_key(value: Any) -> str:
    text = _text(value, "column", required=False).lstrip("\ufeff")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\(\s*\d+\s*[-–]\s*\d+\s*\)", "", text)
    text = re.sub(r"[\s_\-]+", " ", text.casefold()).strip()
    aliases = {
        "name": "name",
        "engineer": "name",
        "agent": "name",
        "assigned to login": "name",
        "manager": "manager",
        "manager login": "manager",
        "case id": "case_id",
        "case": "case_id",
        "product": "product",
        "auditor": "auditor",
        "auditor login": "auditor",
        "auditor source login": "auditor",
        "reviewability": "reviewability",
        "reviewability status": "reviewability",
        "reviewability reason": "reviewability_reason",
        "diagnostic & solution": "diagnostic_solution",
        "diagnostic and solution": "diagnostic_solution",
        "diagnostic solution": "diagnostic_solution",
        "service & communication": "service_communication",
        "service and communication": "service_communication",
        "service communication": "service_communication",
        "plus": "plus",
        "technical plus": "plus",
        "score": "score",
        "problem": "problem",
        "efforts": "efforts",
        "effort": "efforts",
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


def _validate_deduction(
    *,
    comment: str,
    index: int,
    label: str,
    score: int,
    maximum: int,
) -> None:
    token_pattern = re.escape(label).replace(r"\ ", r"\s+").replace(r"\&", r"\s*&\s*")
    broad = list(re.finditer(rf"{token_pattern}\s*-\s*\d+\s*: ?", comment, re.IGNORECASE))
    matches = list(re.finditer(rf"{token_pattern} -(\d+):", comment, re.IGNORECASE))
    expected = maximum - score
    if expected == 0:
        if broad:
            raise QAError(
                f"entry {index}.comments must not include a {label} deduction when the dimension is full"
            )
        return
    if broad and len(matches) != len(broad):
        raise QAError(
            f"entry {index}.comments must use exact '{label} -N:' notation"
        )
    if not matches:
        raise QAError(f"entry {index}.comments must include '{label} -{expected}:'")
    if any(int(match.group(1)) != expected for match in matches):
        raise QAError(
            f"entry {index}.comments {label} deduction must be -{expected}"
        )
    for match in matches:
        _validate_reason(comment, match, index, f"{label} deduction")


def _segment_after(comment: str, match: re.Match[str]) -> str:
    next_starts = [
        token.start()
        for token in SCORING_TOKEN_PATTERN.finditer(comment, match.end())
    ]
    end = min(next_starts) if next_starts else len(comment)
    return comment[match.end():end].strip(" \t\r\n;")


def _validate_reason(
    comment: str,
    match: re.Match[str],
    index: int,
    label: str,
) -> str:
    reason = _segment_after(comment, match)
    if not reason:
        raise QAError(f"entry {index}.comments {label} must include a non-empty reason")
    normalized = re.sub(r"\s+", " ", reason.casefold()).strip(" .;:—–-")
    if normalized in VAGUE_RATIONALES:
        raise QAError(
            f"entry {index}.comments {label} must state evidence or impact, not vague wording"
        )
    return reason


def _validate_plus(comment: str, index: int, plus: int) -> None:
    allocation_tokens = list(re.finditer(r"plus\s*\+\s*\d+\s*: ?", comment, re.IGNORECASE))
    allocations = list(re.finditer(r"plus \+(\d+):", comment, re.IGNORECASE))
    if plus == 0:
        if allocation_tokens:
            raise QAError(
                f"entry {index}.comments must not include a Plus allocation when Plus is 0"
            )
        return
    if len(allocation_tokens) != len(allocations):
        raise QAError(
            f"entry {index}.comments Technical Plus items must use exact 'Plus +N:' notation"
        )
    values = [int(match.group(1)) for match in allocations]
    if any(value not in (1, 2, 3) for value in values):
        raise QAError(
            f"entry {index}.comments Technical Plus items must use +1, +2, or +3"
        )
    if sum(values) != plus:
        raise QAError(
            f"entry {index}.comments Technical Plus allocations must sum to the Plus score ({plus})"
        )
    for match in allocations:
        segment = _segment_after(comment, match)
        item_match = None
        for item in PLUS_ITEMS:
            item_match = re.match(
                rf"{re.escape(item)}\s*(?:—|–|-)\s*(.+)",
                segment,
                re.IGNORECASE | re.DOTALL,
            )
            if item_match is not None:
                break
        if item_match is None:
            allowed = "; ".join(PLUS_ITEMS)
            raise QAError(
                f"entry {index}.comments each Technical Plus allocation must use "
                f"'<item> — <evidenced reason>' with one canonical item: {allowed}"
            )
        reason = item_match.group(1).strip(" \t\r\n;")
        normalized = re.sub(r"\s+", " ", reason.casefold()).strip(" .;:—–-")
        if not reason or normalized in VAGUE_RATIONALES:
            raise QAError(
                f"entry {index}.comments Technical Plus reason must state evidence or impact, not vague wording"
            )


def normalize_entry(raw: dict[str, Any], index: int = 1) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise QAError(f"entry {index} must be an object")
    values = {_header_key(key): value for key, value in raw.items()}
    reviewability = _reviewability(values.get("reviewability"), f"entry {index}.reviewability")
    result = {
        "name": _source_login(values.get("name"), f"entry {index}.name"),
        "manager": _source_login(values.get("manager"), f"entry {index}.manager"),
        "case_id": _text(values.get("case_id"), f"entry {index}.case_id"),
        "product": _text(values.get("product"), f"entry {index}.product", required=False),
        "auditor": _source_login(
            values.get("auditor"), f"entry {index}.auditor", required=False
        ),
        "reviewability": reviewability,
        "reviewability_reason": _text(
            values.get("reviewability_reason"),
            f"entry {index}.reviewability_reason",
            required=reviewability == "Not Reviewable",
        ),
        "problem": _text(
            values.get("problem"),
            f"entry {index}.problem",
            required=False,
        ),
        "efforts": _text(
            values.get("efforts"),
            f"entry {index}.efforts",
            required=False,
        ),
        "comments": _text(values.get("comments"), f"entry {index}.comments", required=False),
    }

    if reviewability == "Reviewable" and result["reviewability_reason"]:
        raise QAError(
            f"entry {index}.reviewability_reason must be blank when Reviewability is Reviewable"
        )

    populated_dimensions = [
        (key, label, maximum)
        for key, label, maximum in DIMENSIONS
        if not _is_blank(values.get(key))
    ]
    supplied_score = values.get("score")
    score_is_populated = not _is_blank(supplied_score)

    if reviewability == "Not Reviewable":
        if populated_dimensions or score_is_populated:
            raise QAError(
                f"entry {index} is Not Reviewable; Diagnostic & Solution, "
                "Service & Communication, Plus, and score must all be blank "
                "(do not use 0 for an unscored row)"
            )
        for key, _, _ in DIMENSIONS:
            result[key] = None
        result["score"] = None
        return result

    if len(populated_dimensions) != len(DIMENSIONS):
        if populated_dimensions:
            raise QAError(
                f"entry {index} mixes blank and populated score dimensions; "
                "a Reviewable row requires all three dimensions"
            )
        if score_is_populated:
            raise QAError(
                f"entry {index}.score cannot substitute for blank dimensions; "
                "use Reviewability=Not Reviewable with a reason and leave all scores blank"
            )
        raise QAError(f"entry {index} is Reviewable and requires all three score dimensions")

    result["problem"] = _text(
        result["problem"], f"entry {index}.problem", required=True
    )
    result["efforts"] = _text(
        result["efforts"], f"entry {index}.efforts", required=True
    )

    for key, label, maximum in DIMENSIONS:
        result[key] = _integer(values.get(key), f"entry {index}.{label}", maximum)
    result["score"] = sum(result[key] for key, _, _ in DIMENSIONS)
    if score_is_populated:
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
    comment = result["comments"]
    _validate_deduction(
        comment=comment,
        index=index,
        label="Diagnostic & Solution",
        score=result["diagnostic_solution"],
        maximum=5,
    )
    _validate_deduction(
        comment=comment,
        index=index,
        label="Service & Communication",
        score=result["service_communication"],
        maximum=3,
    )
    _validate_plus(comment, index, result["plus"])
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


def _looks_like_header(row: list[str]) -> bool:
    keys = {_header_key(cell) for cell in row}
    return {"name", "manager", "case_id"}.issubset(keys) and bool(
        {"diagnostic_solution", "service_communication", "reviewability"} & keys
    )


def _parse_delimited(text: str, delimiter: str) -> list[dict[str, Any]]:
    kind = "TSV" if delimiter == "\t" else "CSV"
    records: list[tuple[int, list[str]]] = []
    try:
        reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter, strict=True)
        for row in reader:
            if any(cell.strip() for cell in row):
                records.append((reader.line_num, row))
    except csv.Error as exc:
        raise QAError(
            f"invalid {kind} input: {exc}. Quote fields that contain tabs, commas, or line breaks"
        ) from exc
    if not records:
        return []

    first_line, first_row = records[0]
    if _looks_like_header(first_row):
        headers = first_row
        data_rows = records[1:]
    else:
        positional_headers = {
            len(LEGACY_COLUMNS): LEGACY_COLUMNS,
            len(CURRENT_COLUMNS): CURRENT_COLUMNS,
        }.get(len(first_row))
        if positional_headers is None:
            raise QAError(
                f"headerless {kind} input at line {first_line} has {len(first_row)} columns; "
                "expected the 12-column legacy schema or 14-column current schema. "
                "Add the canonical header and quote fields containing delimiters or line breaks"
            )
        headers = list(positional_headers)
        data_rows = records

    expected = len(headers)
    entries: list[dict[str, Any]] = []
    for line_number, row in data_rows:
        if len(row) != expected:
            raise QAError(
                f"{kind} row ending at line {line_number} has {len(row)} columns; expected {expected}. "
                "Do not split or stitch rows; add the canonical header and quote fields containing "
                "delimiters or line breaks"
            )
        entries.append(dict(zip(headers, row)))
    return entries


def parse_text(text: str, suffix: str = "") -> list[dict[str, Any]]:
    source = text.lstrip("\ufeff")
    stripped = source.strip()
    if not stripped:
        raise QAError("QA input is empty")
    if suffix.casefold() == ".json" or stripped.startswith(("[", "{")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise QAError(f"invalid JSON input: {exc.msg}") from exc
        if isinstance(parsed, dict):
            for envelope in ("entries", "qa", "records", "rows"):
                if envelope in parsed:
                    parsed = parsed[envelope]
                    break
        if not isinstance(parsed, list):
            raise QAError("JSON input must be an array or an object containing entries, qa, records, or rows")
        return parsed
    if "|" in stripped and "---" in stripped:
        return parse_markdown(stripped)
    normalized_suffix = suffix.casefold()
    if normalized_suffix == ".tsv":
        delimiter = "\t"
    elif normalized_suffix == ".csv":
        delimiter = ","
    else:
        delimiter = "\t" if "\t" in source else ","
    return _parse_delimited(source, delimiter)


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
    diagnostic_solution: int | None = None,
    service_communication: int | None = None,
    plus: int | None = None,
    product: str = "",
    auditor: str = "",
    reviewability: str = "",
    reviewability_reason: str = "",
    problem: str = "",
    efforts: str = "",
    comments: str = "",
) -> dict[str, Any]:
    return normalize_entry(
        {
            "Name": name,
            "Manager": manager,
            "Case ID": case_id,
            "Product": product,
            "Auditor": auditor,
            "Reviewability": reviewability,
            "Reviewability Reason": reviewability_reason,
            "Diagnostic & Solution": diagnostic_solution,
            "Service & Communication": service_communication,
            "Plus": plus,
            "Problem": problem,
            "efforts": efforts,
            "comments": comments,
        }
    )


def _average(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _group_summary(entries: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        groups[entry[key]].append(entry)
    summaries = []
    for group, members in groups.items():
        scored = [item for item in members if item["score"] is not None]
        not_reviewable = [item for item in members if item["reviewability"] == "Not Reviewable"]
        summaries.append(
            {
                key: group,
                "managers": sorted({item["manager"] for item in members}),
                "engineers": sorted({item["name"] for item in members}),
                "total_rows": len(members),
                "reviews": len(scored),
                "scored_reviews": len(scored),
                "not_reviewable_rows": len(not_reviewable),
                "average_score": _average([item["score"] for item in scored]),
                "average_diagnostic_solution": _average(
                    [item["diagnostic_solution"] for item in scored]
                ),
                "average_service_communication": _average(
                    [item["service_communication"] for item in scored]
                ),
                "average_plus": _average([item["plus"] for item in scored]),
            }
        )
    return sorted(summaries, key=lambda item: str(item[key]).casefold())


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not entries:
        raise QAError("cannot summarize an empty QA set")
    scored = [item for item in entries if item["score"] is not None]
    not_reviewable = [item for item in entries if item["reviewability"] == "Not Reviewable"]
    return {
        "total_rows": len(entries),
        "reviews": len(scored),
        "scored_reviews": len(scored),
        "not_reviewable_rows": len(not_reviewable),
        "max_score": QA_MAX_SCORE,
        "average_score": _average([item["score"] for item in scored]),
        "minimum_score": min((item["score"] for item in scored), default=None),
        "maximum_score": max((item["score"] for item in scored), default=None),
        "average_diagnostic_solution": _average(
            [item["diagnostic_solution"] for item in scored]
        ),
        "average_service_communication": _average(
            [item["service_communication"] for item in scored]
        ),
        "average_plus": _average([item["plus"] for item in scored]),
        "by_name": _group_summary(entries, "name"),
        "by_manager": _group_summary(entries, "manager"),
    }


def _md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _display(value: Any) -> str:
    return "" if value is None else str(value)


def render_report(entries: list[dict[str, Any]], title: str = "Case Review QA Report") -> str:
    summary = summarize(entries)
    lines = [
        f"# {title}",
        "",
        f"**Total rows:** {summary['total_rows']}  ",
        f"**Scored reviews:** {summary['scored_reviews']}  ",
        f"**Not-reviewable rows:** {summary['not_reviewable_rows']}  ",
        f"**Score scale:** 0-{summary['max_score']}  ",
        "**Scoring rule:** Diagnostic & Solution + Service & Communication + Plus",
        "",
        "## Overall Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Average score | {_display(summary['average_score']) or 'not available'} |",
        f"| Minimum score | {_display(summary['minimum_score']) or 'not available'} |",
        f"| Maximum score | {_display(summary['maximum_score']) or 'not available'} |",
        f"| Average Diagnostic & Solution | {_display(summary['average_diagnostic_solution']) or 'not available'} |",
        f"| Average Service & Communication | {_display(summary['average_service_communication']) or 'not available'} |",
        f"| Average Plus | {_display(summary['average_plus']) or 'not available'} |",
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
                f"| {label} | {'Manager(s)' if key == 'name' else 'Engineer(s)'} | Total rows | Scored reviews | Not reviewable | Avg score | Avg Diagnostic & Solution | Avg Service & Communication | Avg Plus |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary[f"by_{key}"]:
            related_text = ", ".join(item["managers"] if key == "name" else item["engineers"])
            lines.append(
                f"| {_md(item[key])} | {_md(related_text)} | {item['total_rows']} | "
                f"{item['scored_reviews']} | {item['not_reviewable_rows']} | "
                f"{_display(item['average_score']) or 'not available'} | "
                f"{_display(item['average_diagnostic_solution']) or 'not available'} | "
                f"{_display(item['average_service_communication']) or 'not available'} | "
                f"{_display(item['average_plus']) or 'not available'} |"
            )
        lines.append("")
    lines.extend(
        [
            "## QA Entries",
            "",
            "| Name | Manager | Case ID | Product | Auditor | Reviewability | Reviewability Reason | Diagnostic & Solution | Service & Communication | Plus | Score | Problem | efforts | comments |",
            "|---|---|---|---|---|---|---|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for entry in entries:
        lines.append(
            f"| {_md(entry['name'])} | {_md(entry['manager'])} | {_md(entry['case_id'])} | "
            f"{_md(entry['product'] or 'not stated')} | {_md(entry['auditor'])} | "
            f"{_md(entry['reviewability'])} | {_md(entry['reviewability_reason'])} | "
            f"{_display(entry['diagnostic_solution'])} | {_display(entry['service_communication'])} | "
            f"{_display(entry['plus'])} | {_display(entry['score'])} | {_md(entry['problem'])} | "
            f"{_md(entry['efforts'])} | {_md(entry['comments'])} |"
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
        subparser.add_argument(
            "--input", required=True, help="QA input file (.md, .csv, .tsv, .txt, or .json)"
        )
        subparser.add_argument("--json", action="store_true", help="Emit normalized JSON")
    score = subparsers.add_parser("score", help="Score one QA entry")
    score.add_argument("--name", required=True)
    score.add_argument("--manager", required=True)
    score.add_argument("--case-id", required=True)
    score.add_argument("--diagnostic-solution", type=int)
    score.add_argument("--service-communication", type=int)
    score.add_argument("--plus", type=int)
    score.add_argument("--product", default="")
    score.add_argument("--auditor", default="")
    score.add_argument("--reviewability", default="")
    score.add_argument("--reviewability-reason", default="")
    score.add_argument("--problem", default="")
    score.add_argument("--efforts", default="")
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
                auditor=args.auditor,
                reviewability=args.reviewability,
                reviewability_reason=args.reviewability_reason,
                problem=args.problem,
                efforts=args.efforts,
                comments=args.comments,
            ), ensure_ascii=False, indent=2))
            return 0
        entries = load_entries(args.input)
        if args.command == "validate" and args.json:
            print(_json_report(entries), end="")
        elif args.command == "validate":
            summary = summarize(entries)
            print(
                f"Valid QA input: {summary['total_rows']} rows; "
                f"{summary['scored_reviews']} scored; "
                f"{summary['not_reviewable_rows']} not reviewable; "
                f"maximum score {QA_MAX_SCORE}."
            )
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
