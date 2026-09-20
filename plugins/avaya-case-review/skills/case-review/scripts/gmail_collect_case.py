#!/usr/bin/env python3
"""Exhaustive case-bounded Gmail collection with a deterministic coverage manifest.

Replaces agent-driven per-page MCP loops for the Complete Context Before
Analysis gate: one invocation enumerates the primary-ID thread chain, exhausts
every page cursor, reassembles and hash-verifies every message, and writes a
corpus, a compact digest, and a Context Coverage Ledger manifest that the
review workflow consumes instead of raw page payloads. The underlying broker
methods are the same ones the ``gmail_list_threads`` and
``gmail_read_thread_page`` MCP tools expose; those tools remain the documented
manual rollback path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

COLLECTION_DIR_NAME = "collection"
STAGING_DIR_NAME = "collection.staging"
PREVIOUS_DIR_NAME = "collection.prev"
DIGEST_SIZE_LIMIT_BYTES = 40 * 1024
DEFAULT_QUERY_CHAR_BUDGET = 12_000
SUBJECT_LIMIT = 120
FROM_LIMIT = 80
PARTICIPANT_LIMIT = 10


class CollectionError(RuntimeError):
    """A sanitized collection failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


def resolve_gmail_tools_dir() -> Path:
    """Locate ``tools/gmail`` in the repo, installed, or env-overridden layout."""

    override = os.environ.get("GMAIL_TOOLS_DIR")
    if override:
        candidate = Path(override).expanduser().resolve()
        if (candidate / "gmail_broker_client.py").is_file():
            return candidate
        raise CollectionError(
            "IMPORT_PATH",
            f"GMAIL_TOOLS_DIR does not contain gmail_broker_client.py: {candidate}",
        )
    repo_layout = Path(__file__).resolve().parents[5] / "tools" / "gmail"
    if (repo_layout / "gmail_broker_client.py").is_file():
        return repo_layout
    installed_layout = Path.home() / ".gemini" / "tools" / "gmail"
    if (installed_layout / "gmail_broker_client.py").is_file():
        return installed_layout
    raise CollectionError(
        "IMPORT_PATH",
        "tools/gmail not found; set GMAIL_TOOLS_DIR to the directory holding "
        "gmail_broker_client.py",
    )


def import_broker_client() -> Any:
    tools_dir = resolve_gmail_tools_dir()
    package_root = tools_dir.parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from tools.gmail.gmail_broker_client import BrokerClient, BrokerClientError

    return BrokerClient, BrokerClientError


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_case_id(value: str) -> str:
    normalized = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,63}", normalized):
        raise CollectionError("CASE_ID", f"unsupported case ID: {value!r}")
    return normalized


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    override = os.environ.get("CASE_REVIEW_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AvayaCaseReview"
    return Path.home() / ".local" / "share" / "avaya-case-review"


def collection_paths(data_dir: Path, case_id: str) -> dict[str, Path]:
    base = data_dir / "case-records" / normalize_case_id(case_id)
    return {
        "record_dir": base,
        "stable": base / COLLECTION_DIR_NAME,
        "staging": base / STAGING_DIR_NAME,
        "previous": base / PREVIOUS_DIR_NAME,
        "progress": base / STAGING_DIR_NAME / "progress.json",
        "corpus": base / STAGING_DIR_NAME / "corpus.json",
        "manifest": base / STAGING_DIR_NAME / "manifest.json",
        "digest": base / STAGING_DIR_NAME / "digest.json",
        "stable_manifest": base / COLLECTION_DIR_NAME / "manifest.json",
    }


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=1))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def request_json(client: Any, method: str, params: dict[str, Any]) -> dict[str, Any]:
    raw = client.request(method, params)
    if not isinstance(raw, str) or not raw.strip():
        raise CollectionError("PROTOCOL", f"{method} returned an empty result")
    try:
        parsed = json.loads(raw)
    except ValueError as error:
        raise CollectionError("PROTOCOL", f"{method} returned invalid JSON") from error
    if not isinstance(parsed, dict) or parsed.get("success") is not True:
        detail = "unsuccessful response"
        if isinstance(parsed, dict) and parsed.get("error"):
            detail = f"error: {parsed['error']}"
        raise CollectionError("BACKEND", f"{method} {detail}")
    return parsed


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def enumerate_threads(
    client: Any, case_id: str, snapshot: str
) -> tuple[list[str], int, str]:
    """Exhaust the primary-ID list chain; returns (thread_ids, pages, snapshot)."""

    thread_ids: list[str] = []
    seen_ids: set[str] = set()
    seen_tokens: set[str] = {""}
    page_token = ""
    pages = 0
    while True:
        response = request_json(
            client,
            "gmail_list_threads",
            {
                "query": case_id,
                "snapshot_before": snapshot,
                "page_token": page_token,
                "max_results": 100,
            },
        )
        pages += 1
        if snapshot:
            if response.get("snapshot_before") != snapshot:
                raise CollectionError("PROTOCOL", "snapshot changed inside list chain")
        else:
            snapshot = str(response.get("snapshot_before") or "")
            if not snapshot:
                raise CollectionError("PROTOCOL", "bootstrap response missing snapshot")
        for thread_id in response.get("thread_ids", []):
            if thread_id not in seen_ids:
                seen_ids.add(thread_id)
                thread_ids.append(thread_id)
        next_token = str(response.get("next_page_token") or "")
        complete = response.get("complete") is True
        if complete and not next_token:
            break
        if next_token:
            if next_token in seen_tokens:
                raise CollectionError("PROTOCOL", "repeated page token in list chain")
            seen_tokens.add(next_token)
            page_token = next_token
        elif not complete:
            raise CollectionError("PROTOCOL", "list chain ended without complete flag")
    return thread_ids, pages, snapshot


def read_thread(client: Any, thread_id: str, snapshot: str) -> list[dict[str, Any]]:
    """Exhaust one thread's cursor chain; returns its raw pages."""

    pages: list[dict[str, Any]] = []
    seen_cursors: set[str] = {""}
    cursor = ""
    while True:
        response = request_json(
            client,
            "gmail_read_thread_page",
            {"thread_id": thread_id, "snapshot_before": snapshot, "cursor": cursor},
        )
        pages.append(response)
        next_cursor = str(response.get("next_cursor") or "")
        complete = response.get("complete") is True
        if complete and not next_cursor:
            break
        if next_cursor:
            if next_cursor in seen_cursors:
                raise CollectionError(
                    "PROTOCOL", f"repeated cursor in thread {thread_id}"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        elif not complete:
            raise CollectionError(
                "PROTOCOL", f"thread {thread_id} chain ended without complete flag"
            )
    return pages


def reassemble_messages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate segments by (message_id, chunk_index) and verify each body."""

    segments: dict[tuple[str, int], dict[str, Any]] = {}
    for page in pages:
        for segment in page.get("segments", []):
            key = (str(segment.get("message_id")), int(segment.get("chunk_index", 0)))
            prior = segments.get(key)
            if prior is not None and canonical_hash(prior) != canonical_hash(segment):
                raise CollectionError(
                    "PROTOCOL",
                    f"conflicting duplicate chunk {key}",
                )
            segments[key] = segment
    by_message: dict[str, list[dict[str, Any]]] = {}
    for (message_id, _index), segment in segments.items():
        by_message.setdefault(message_id, []).append(segment)
    messages: list[dict[str, Any]] = []
    for message_id, chunks in by_message.items():
        chunks.sort(key=lambda item: int(item.get("chunk_index", 0)))
        chunk_count = int(chunks[0].get("chunk_count", len(chunks)))
        indices = [int(item.get("chunk_index", 0)) for item in chunks]
        if indices != list(range(chunk_count)):
            raise CollectionError(
                "BODY_VERIFY",
                f"message {message_id} chunk sequence incomplete",
            )
        body = "".join(str(chunk.get("body_chunk", "")) for chunk in chunks)
        advertised_bytes = int(chunks[0].get("body_bytes", -1))
        advertised_hash = str(chunks[0].get("body_sha256", ""))
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if digest != advertised_hash or len(body.encode("utf-8")) != advertised_bytes:
            raise CollectionError(
                "BODY_VERIFY",
                f"message {message_id} failed reassembled body verification",
            )
        messages.append(
            {
                "message_id": message_id,
                "internal_date": str(chunks[0].get("internal_date", "")),
                "from": str(chunks[0].get("from", "")),
                "to": list(chunks[0].get("to", [])),
                "cc": list(chunks[0].get("cc", [])),
                "subject": str(chunks[0].get("subject", "")),
                "attachment_names": list(chunks[0].get("attachment_names", [])),
                "chunk_count": chunk_count,
                "body_chars": len(body),
                "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "body": body,
            }
        )
    messages.sort(key=lambda item: item["internal_date"])
    return messages


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def thread_page_stats(pages: list[dict[str, Any]]) -> dict[str, Any]:
    message_counts = {int(page.get("message_count", -1)) for page in pages}
    manifests = {str(page.get("manifest_sha256", "")) for page in pages}
    completed = {int(page.get("messages_completed", -1)) for page in pages}
    if len(message_counts) != 1 or -1 in message_counts:
        raise CollectionError("PROTOCOL", "thread message_count unstable across pages")
    if len(manifests) != 1:
        raise CollectionError("PROTOCOL", "thread manifest hash changed across pages")
    if max(completed) != max(message_counts):
        raise CollectionError(
            "COVERAGE", "thread messages_completed never reached message_count"
        )
    return {
        "message_count": message_counts.pop(),
        "manifest_sha256": manifests.pop(),
        "pages": len(pages),
    }


def truncate_bytes(value: str, limit: int) -> str:
    """Truncate to a UTF-8 byte budget without splitting a character."""

    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


def build_digest(case_id: str, snapshot: str, threads: list[dict[str, Any]]) -> dict[str, Any]:
    thread_entries = []
    message_entries = []
    for index, thread in enumerate(threads):
        messages = thread["messages"]
        senders = []
        for message in messages:
            sender = message["from"][:FROM_LIMIT]
            if sender not in senders:
                senders.append(sender)
        subjects = []
        for message in messages:
            subject = message["subject"][:SUBJECT_LIMIT]
            if subject and subject not in subjects:
                subjects.append(subject)
        thread_entries.append(
            {
                "thread_id": thread["thread_id"],
                "message_count": len(messages),
                "pages": thread["pages"],
                "first_internal_date": messages[0]["internal_date"] if messages else "",
                "last_internal_date": messages[-1]["internal_date"] if messages else "",
                "manifest_sha256": thread["manifest_sha256"],
                "senders": senders[:PARTICIPANT_LIMIT],
                "subjects": subjects[:5],
            }
        )
        for message in messages:
            message_entries.append(
                [
                    message["message_id"],
                    index,
                    message["internal_date"][:10],
                    len(message["attachment_names"]),
                    message["body_chars"],
                    truncate_bytes(message["from"], 48),
                    truncate_bytes(message["subject"], 112),
                ]
            )
    return {
        "case_id": case_id,
        "snapshot_before": snapshot,
        "generated_at": utc_now(),
        "message_entry_legend": [
            "message_id",
            "thread index into threads[]",
            "date (UTC, day precision)",
            "attachment count",
            "body_chars",
            "from",
            "subject",
        ],
        "threads": thread_entries,
        "messages": message_entries,
    }


def dump_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_ledger(
    thread_ids: list[str],
    list_pages: int,
    threads: list[dict[str, Any]],
) -> dict[str, Any]:
    messages_expected = sum(thread["message_count"] for thread in threads)
    messages_completed = sum(len(thread["messages"]) for thread in threads)
    chunks_expected = sum(
        message["chunk_count"] for thread in threads for message in thread["messages"]
    )
    chunks_completed = sum(
        message["chunk_count"] for thread in threads for message in thread["messages"]
    )
    threads_read = len(threads)
    return {
        "record_ids_planned": 1,
        "record_id_queries_completed": 1,
        "query_pages_completed": list_pages,
        "unique_threads_discovered": len(thread_ids),
        "threads_read_complete": threads_read,
        "messages_expected": messages_expected,
        "messages_completed": messages_completed,
        "message_chunks_expected": chunks_expected,
        "message_chunks_completed": chunks_completed,
        "body_hashes_verified": messages_completed,
        "manifest_hashes_stable": threads_read,
        "gmail_threads_discovered": len(thread_ids),
        "gmail_threads_enumerated": len(thread_ids),
        "gmail_threads_read_complete": threads_read,
        "gmail_messages_expected": messages_expected,
        "gmail_messages_read": messages_completed,
        "body_chunks_expected": chunks_expected,
        "body_chunks_read": chunks_completed,
        "snapshot_before": "",
        "query_complete": True,
    }


LEDGER_EQUALITIES = (
    ("unique_threads_discovered", "threads_read_complete"),
    ("messages_expected", "messages_completed"),
    ("message_chunks_expected", "message_chunks_completed"),
    ("messages_completed", "body_hashes_verified"),
    ("threads_read_complete", "manifest_hashes_stable"),
)


def ledger_passes(ledger: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if ledger["record_ids_planned"] != 1 or ledger["record_id_queries_completed"] != 1:
        failures.append("record-ID query chain incomplete")
    for left, right in LEDGER_EQUALITIES:
        if ledger[left] != ledger[right]:
            failures.append(f"{left} != {right}")
    aliases = (
        ("gmail_threads_discovered", "unique_threads_discovered"),
        ("gmail_threads_enumerated", "unique_threads_discovered"),
        ("gmail_threads_read_complete", "threads_read_complete"),
        ("gmail_messages_expected", "messages_expected"),
        ("gmail_messages_read", "messages_completed"),
        ("body_chunks_expected", "message_chunks_expected"),
        ("body_chunks_read", "message_chunks_completed"),
    )
    for left, right in aliases:
        if ledger[left] != ledger[right]:
            failures.append(f"alias {left} != {right}")
    return (not failures), failures


def blocking_output(ledger: dict[str, Any], blocker: str) -> str:
    return (
        "Context collection incomplete — review not generated.\n"
        "\n"
        f"Case notes: <pending>\n"
        f"Record-ID queries: {ledger['record_id_queries_completed']}/{ledger['record_ids_planned']}\n"
        f"Gmail threads: {ledger['threads_read_complete']}/{ledger['unique_threads_discovered']}\n"
        f"Gmail messages: {ledger['messages_completed']}/{ledger['messages_expected']}\n"
        f"Blocker: {blocker}"
    )


def collect_case(
    case_id: str,
    data_dir: Path,
    resume: bool = False,
    client_factory: Any = None,
) -> int:
    case_id = normalize_case_id(case_id)
    paths = collection_paths(data_dir, case_id)
    if client_factory is None:
        BrokerClient, _BrokerClientError = import_broker_client()
        client_factory = BrokerClient
    client = client_factory()

    progress: dict[str, Any] = {
        "case_id": case_id,
        "snapshot_before": "",
        "thread_ids": [],
        "completed_threads": {},
        "list_pages": 0,
        "started_at": utc_now(),
    }
    if resume:
        if not paths["progress"].is_file():
            print("no staging progress to resume; run collect without --resume", file=sys.stderr)
            return 2
        progress = read_json(paths["progress"])
    else:
        if paths["staging"].exists():
            import shutil

            shutil.rmtree(paths["staging"])
        paths["staging"].mkdir(parents=True, exist_ok=True)
        write_json(paths["progress"], progress)

    started = time.perf_counter()
    try:
        if not progress["thread_ids"]:
            progress["thread_ids"], progress["list_pages"], progress["snapshot_before"] = (
                enumerate_threads(client, case_id, progress["snapshot_before"])
            )
            write_json(paths["progress"], progress)
        snapshot = progress["snapshot_before"]
        for thread_id in progress["thread_ids"]:
            if thread_id in progress["completed_threads"]:
                continue
            pages = read_thread(client, thread_id, snapshot)
            stats = thread_page_stats(pages)
            messages = reassemble_messages(pages)
            if len(messages) != stats["message_count"]:
                raise CollectionError(
                    "COVERAGE",
                    f"thread {thread_id} deduplicated {len(messages)} messages "
                    f"but manifest counts {stats['message_count']}",
                )
            progress["completed_threads"][thread_id] = {
                "pages": pages,
                "messages": messages,
                "stats": stats,
            }
            write_json(paths["progress"], progress)
    except CollectionError as error:
        ledger = build_ledger(progress["thread_ids"], progress["list_pages"], [
            {
                "thread_id": thread_id,
                "pages": state["stats"]["pages"],
                "message_count": state["stats"]["message_count"],
                "manifest_sha256": state["stats"]["manifest_sha256"],
                "messages": state["messages"],
            }
            for thread_id, state in progress["completed_threads"].items()
        ])
        print(blocking_output(ledger, f"Gmail collection failed — {error}"))
        print("staging progress retained; re-run with --resume to continue", file=sys.stderr)
        return 1
    except Exception as error:  # broker/OS failures stay sanitized
        print(blocking_output(build_ledger([], 0, []), f"Gmail collection failed — {type(error).__name__}"))
        return 1

    threads = [
        {
            "thread_id": thread_id,
            "pages": state["stats"]["pages"],
            "message_count": state["stats"]["message_count"],
            "manifest_sha256": state["stats"]["manifest_sha256"],
            "messages": state["messages"],
        }
        for thread_id, state in progress["completed_threads"].items()
    ]
    ledger = build_ledger(progress["thread_ids"], progress["list_pages"], threads)
    ledger["snapshot_before"] = snapshot
    passed, failures = ledger_passes(ledger)
    corpus = {
        "case_id": case_id,
        "snapshot_before": snapshot,
        "collected_at": utc_now(),
        "resumed": bool(resume),
        "threads": [
            {
                "thread_id": thread["thread_id"],
                "stats": {
                    "message_count": thread["message_count"],
                    "manifest_sha256": thread["manifest_sha256"],
                    "pages": thread["pages"],
                },
                "messages": thread["messages"],
            }
            for thread in threads
        ],
    }
    digest = build_digest(case_id, snapshot, threads)
    elapsed = round(time.perf_counter() - started, 3)
    write_json(paths["corpus"], corpus)
    digest_degraded = False
    atomic_write(paths["digest"], dump_compact(digest))
    if paths["digest"].stat().st_size > DIGEST_SIZE_LIMIT_BYTES:
        digest_degraded = True
        digest = {
            "case_id": digest["case_id"],
            "snapshot_before": digest["snapshot_before"],
            "generated_at": digest["generated_at"],
            "messages_index_omitted": "digest budget exceeded; use query with thread-level filters",
            "threads": digest["threads"],
        }
        atomic_write(paths["digest"], dump_compact(digest))
    digest_bytes = paths["digest"].stat().st_size
    manifest = {
        "case_id": case_id,
        "collected_at": utc_now(),
        "snapshot_before": snapshot,
        "status": "pass" if passed else "fail",
        "failures": failures,
        "elapsed_seconds": elapsed,
        "digest_degraded": digest_degraded,
        "ledger": ledger,
        "corpus_sha256": hashlib.sha256(
            paths["corpus"].read_bytes()
        ).hexdigest(),
        "digest_sha256": hashlib.sha256(
            paths["digest"].read_bytes()
        ).hexdigest(),
        "digest_bytes": digest_bytes,
    }
    write_json(paths["manifest"], manifest)

    if not passed:
        print(blocking_output(ledger, "; ".join(failures)))
        return 1
    if digest_bytes > DIGEST_SIZE_LIMIT_BYTES:
        print(
            f"digest exceeds {DIGEST_SIZE_LIMIT_BYTES} bytes ({digest_bytes}); "
            "collection aborted",
            file=sys.stderr,
        )
        return 1

    import shutil

    if paths["previous"].exists():
        shutil.rmtree(paths["previous"])
    if paths["stable"].exists():
        paths["stable"].rename(paths["previous"])
    paths["staging"].rename(paths["stable"])

    print(
        json.dumps(
            {
                "status": "pass",
                "case_id": case_id,
                "snapshot_before": snapshot,
                "threads": ledger["unique_threads_discovered"],
                "messages": ledger["messages_completed"],
                "chunks": ledger["message_chunks_completed"],
                "list_pages": ledger["query_pages_completed"],
                "elapsed_seconds": elapsed,
                "digest_bytes": digest_bytes,
                "manifest": str(paths["stable_manifest"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def query_corpus(
    case_id: str,
    data_dir: Path,
    thread_id: str | None,
    message_id: str | None,
    sender: str | None,
    since: str | None,
    chars: int,
) -> int:
    case_id = normalize_case_id(case_id)
    paths = collection_paths(data_dir, case_id)
    corpus_path = paths["stable"] / "corpus.json"
    if not corpus_path.is_file():
        print(f"no collected corpus for {case_id}; run collect first", file=sys.stderr)
        return 2
    corpus = read_json(corpus_path)
    candidates = []
    for thread in corpus["threads"]:
        if thread_id and thread["thread_id"] != thread_id:
            continue
        for message in thread["messages"]:
            if message_id and message["message_id"] != message_id:
                continue
            if sender and sender.casefold() not in message["from"].casefold():
                continue
            if since and message["internal_date"] < since:
                continue
            candidates.append((thread["thread_id"], message))
    candidates.sort(key=lambda item: item[1]["internal_date"])
    matches = []
    remaining = max(0, chars)
    truncated = False
    for thread_id_value, message in candidates:
        body = message["body"]
        if len(body) > remaining:
            body = body[:remaining]
            truncated = True
        remaining -= len(body)
        matches.append(
            {
                "message_id": message["message_id"],
                "thread_id": thread_id_value,
                "internal_date": message["internal_date"],
                "from": message["from"],
                "subject": message["subject"],
                "attachments": message["attachment_names"],
                "body_chars": len(body),
                "body": body,
            }
        )
        if remaining <= 0:
            break
    output = {
        "case_id": case_id,
        "snapshot_before": corpus["snapshot_before"],
        "matched": len(matches),
        "truncated": truncated,
        "messages": matches,
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


def status_case(case_id: str, data_dir: Path) -> int:
    case_id = normalize_case_id(case_id)
    paths = collection_paths(data_dir, case_id)
    manifest_path = paths["stable_manifest"]
    if not manifest_path.is_file():
        print(f"no completed collection manifest for {case_id}", file=sys.stderr)
        return 2
    manifest = read_json(manifest_path)
    summary = {
        "status": manifest.get("status"),
        "snapshot_before": manifest.get("snapshot_before"),
        "collected_at": manifest.get("collected_at"),
        "ledger": manifest.get("ledger"),
        "failures": manifest.get("failures"),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if manifest.get("status") == "pass" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", help="Override the persistent data directory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser(
        "collect", help="Exhaustively collect the case-bounded Gmail corpus"
    )
    collect.add_argument("--case-id", required=True)
    collect.add_argument(
        "--resume",
        action="store_true",
        help="Continue a retained staging collection under its original snapshot",
    )

    query = subparsers.add_parser(
        "query", help="Pull message bodies from the collected corpus under a char budget"
    )
    query.add_argument("--case-id", required=True)
    query.add_argument("--thread-id")
    query.add_argument("--message-id")
    query.add_argument("--from", dest="sender", help="Case-insensitive sender substring")
    query.add_argument("--since", help="ISO timestamp lower bound (inclusive)")
    query.add_argument(
        "--chars",
        type=int,
        default=DEFAULT_QUERY_CHAR_BUDGET,
        help=f"Character budget (default {DEFAULT_QUERY_CHAR_BUDGET})",
    )

    show = subparsers.add_parser("status", help="Print the completed collection manifest")
    show.add_argument("--case-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    if args.command == "collect":
        return collect_case(args.case_id, data_dir, resume=args.resume)
    if args.command == "query":
        return query_corpus(
            args.case_id,
            data_dir,
            thread_id=args.thread_id,
            message_id=args.message_id,
            sender=args.sender,
            since=args.since,
            chars=args.chars,
        )
    if args.command == "status":
        return status_case(args.case_id, data_dir)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
