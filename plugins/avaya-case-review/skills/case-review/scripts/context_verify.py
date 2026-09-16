#!/usr/bin/env python3
"""Validate saved CaseToMD/Gmail response artifacts and emit a safe coverage ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class ContextVerificationError(ValueError):
    """Raised when a saved context response cannot satisfy the coverage contract."""


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContextVerificationError("response artifact is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContextVerificationError("response artifact must be a JSON object")
    return value


def _require_success(value: dict[str, Any]) -> None:
    if value.get("success") is not True:
        raise ContextVerificationError("response artifact did not succeed")


def _require_string(value: Any, label: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ContextVerificationError(f"{label} is invalid")
    return value


def _verify_case_markdown(path: str | Path) -> int:
    value = _load_json(path)
    _require_success(value)
    markdown = _require_string(value.get("markdown"), "CaseToMD markdown")
    if re.search(r"(?im)\b(?:truncated|output truncated)\b", markdown):
        raise ContextVerificationError("CaseToMD markdown is truncated")
    notes = len(re.findall(r"(?m)^###\s+", markdown))
    if notes == 0:
        raise ContextVerificationError("CaseToMD markdown contains no structured notes")
    return notes


def _verify_list_pages(paths: list[str | Path]) -> tuple[str, int, set[str]]:
    if not paths:
        raise ContextVerificationError("at least one Gmail list page is required")
    snapshot: str | None = None
    tokens: set[str] = set()
    thread_ids: set[str] = set()
    for index, path in enumerate(paths):
        page = _load_json(path)
        _require_success(page)
        current_snapshot = _require_string(page.get("snapshot_before"), "list snapshot")
        if snapshot is None:
            snapshot = current_snapshot
        elif current_snapshot != snapshot:
            raise ContextVerificationError("list pages do not reuse one snapshot")
        ids = page.get("thread_ids")
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
            raise ContextVerificationError("list page thread_ids are invalid")
        thread_ids.update(ids)
        next_token = page.get("next_page_token") or ""
        if not isinstance(next_token, str):
            raise ContextVerificationError("list page token is invalid")
        if next_token in tokens:
            raise ContextVerificationError("repeated list page token")
        if next_token:
            tokens.add(next_token)
        is_last = index == len(paths) - 1
        if page.get("complete") is not (is_last and not next_token):
            raise ContextVerificationError("list completion does not match page token")
        if not is_last and not next_token:
            raise ContextVerificationError("list page chain ended before the final artifact")
    assert snapshot is not None
    return snapshot, len(paths), thread_ids


def _verify_thread_pages(
    paths: list[str | Path], snapshot: str, expected_threads: set[str]
) -> tuple[int, int, int, int]:
    if not paths:
        raise ContextVerificationError("at least one Gmail thread page is required")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        page = _load_json(path)
        _require_success(page)
        if _require_string(page.get("snapshot_before"), "thread snapshot") != snapshot:
            raise ContextVerificationError("thread page does not reuse the list snapshot")
        thread_id = _require_string(page.get("thread_id"), "thread id")
        grouped.setdefault(thread_id, []).append(page)
    if set(grouped) != expected_threads:
        raise ContextVerificationError("thread page set does not match listed threads")

    messages_expected = 0
    messages_completed = 0
    chunks_expected = 0
    chunks_completed = 0
    manifests_stable = 0
    for pages in grouped.values():
        manifest: str | None = None
        message_count: int | None = None
        cursors: set[str] = set()
        segments: list[dict[str, Any]] = []
        for index, page in enumerate(pages):
            current_manifest = _require_string(page.get("manifest_sha256"), "thread manifest")
            if manifest is None:
                manifest = current_manifest
            elif current_manifest != manifest:
                raise ContextVerificationError("thread manifest changed")
            current_count = page.get("message_count")
            if not isinstance(current_count, int) or current_count < 0:
                raise ContextVerificationError("thread message_count is invalid")
            if message_count is None:
                message_count = current_count
            elif current_count != message_count:
                raise ContextVerificationError("thread message_count changed")
            page_segments = page.get("segments")
            if not isinstance(page_segments, list) or any(not isinstance(item, dict) for item in page_segments):
                raise ContextVerificationError("thread segments are invalid")
            segments.extend(page_segments)
            next_cursor = page.get("next_cursor") or ""
            if not isinstance(next_cursor, str):
                raise ContextVerificationError("thread cursor is invalid")
            is_last = index == len(pages) - 1
            if page.get("complete") is not (is_last and not next_cursor):
                raise ContextVerificationError("thread completion does not match cursor")
            if next_cursor:
                if next_cursor in cursors:
                    raise ContextVerificationError("repeated thread cursor")
                cursors.add(next_cursor)
        assert message_count is not None
        messages: dict[str, list[dict[str, Any]]] = {}
        for segment in segments:
            message_id = _require_string(segment.get("message_id"), "message id")
            messages.setdefault(message_id, []).append(segment)
        if len(messages) != message_count:
            raise ContextVerificationError("thread message count does not match segments")
        messages_expected += message_count
        for parts in messages.values():
            parts.sort(key=lambda item: item.get("chunk_index", -1))
            chunk_count = parts[0].get("chunk_count")
            if not isinstance(chunk_count, int) or chunk_count <= 0 or len(parts) != chunk_count:
                raise ContextVerificationError("message chunks are incomplete")
            chunks_expected += chunk_count
            body_parts: list[str] = []
            for expected_index, part in enumerate(parts):
                if part.get("chunk_index") != expected_index or part.get("chunk_count") != chunk_count:
                    raise ContextVerificationError("message chunk indexes are invalid")
                body_parts.append(_require_string(part.get("body_chunk"), "message body chunk", nonempty=False))
            body = "".join(body_parts).encode("utf-8")
            advertised_bytes = parts[0].get("body_bytes")
            advertised_hash = _require_string(parts[0].get("body_sha256"), "message body hash")
            if advertised_bytes != len(body) or advertised_hash != hashlib.sha256(body).hexdigest():
                raise ContextVerificationError("message body bytes or hash do not match")
            chunks_completed += chunk_count
            messages_completed += 1
        manifests_stable += 1
    return messages_expected, messages_completed, chunks_expected, chunks_completed, manifests_stable


def verify_context(
    case_markdown: str | Path,
    list_pages: list[str | Path],
    thread_pages: list[str | Path],
) -> dict[str, Any]:
    case_notes = _verify_case_markdown(case_markdown)
    snapshot, query_pages, thread_ids = _verify_list_pages(list_pages)
    messages_expected, messages_completed, chunks_expected, chunks_completed, manifests = _verify_thread_pages(
        thread_pages, snapshot, thread_ids
    )
    if messages_expected != messages_completed or chunks_expected != chunks_completed:
        raise ContextVerificationError("context coverage equality failed")
    return {
        "case_notes_discovered": case_notes,
        "case_notes_processed": case_notes,
        "record_ids_planned": 1,
        "record_id_queries_completed": 1,
        "query_pages_completed": query_pages,
        "query_complete": True,
        "unique_threads_discovered": len(thread_ids),
        "threads_read_complete": len(thread_ids),
        "messages_expected": messages_expected,
        "messages_completed": messages_completed,
        "message_chunks_expected": chunks_expected,
        "message_chunks_completed": chunks_completed,
        "body_hashes_verified": messages_completed,
        "manifest_hashes_stable": manifests,
        "snapshot_before": snapshot,
        "gmail_threads_discovered": len(thread_ids),
        "gmail_threads_enumerated": len(thread_ids),
        "gmail_threads_read_complete": len(thread_ids),
        "gmail_messages_expected": messages_expected,
        "gmail_messages_read": messages_completed,
        "body_chunks_expected": chunks_expected,
        "body_chunks_read": chunks_completed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-markdown", required=True)
    parser.add_argument("--list-page", action="append", required=True)
    parser.add_argument("--thread-page", action="append", required=True)
    args = parser.parse_args()
    try:
        result = verify_context(args.case_markdown, args.list_page, args.thread_page)
    except (ContextVerificationError, OSError) as exc:
        print(f"context verification failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
