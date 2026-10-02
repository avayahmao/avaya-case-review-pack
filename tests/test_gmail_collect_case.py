import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugins/avaya-case-review/skills/case-review/scripts/gmail_collect_case.py"
)
SPEC = importlib.util.spec_from_file_location("gmail_collect_case", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load gmail_collect_case.py")
gcc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gcc)


def make_segment(message_id, body, chunk_index, chunk_count, date, from_):
    encoded = body.encode("utf-8")
    return {
        "message_id": message_id,
        "thread_id": "t",
        "internal_date": date,
        "from": from_,
        "to": ["\"Ops\" <ops@avaya.com>"],
        "cc": [],
        "subject": f"Re: SR case thread {message_id}",
        "attachment_names": ["image.png"] if chunk_index == 0 else [],
        "body_chunk": body,
        "body_bytes": None,  # filled by builder below
        "body_sha256": None,
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
    }


def build_thread_pages(thread_id, messages, per_page=32):
    """Split message chunks into broker-shaped pages with message-level hashes."""

    final_segments = []
    message_ids = {
        position: f"msg-{thread_id}-{position}" for position in range(len(messages))
    }
    for message_position, (date, from_, chunks) in enumerate(messages):
        body = "".join(chunks)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        size = len(body.encode("utf-8"))
        for index, chunk in enumerate(chunks):
            segment = make_segment(
                message_ids[message_position],
                chunk,
                index,
                len(chunks),
                date,
                from_,
            )
            segment["body_sha256"] = digest
            segment["body_bytes"] = size
            final_segments.append(segment)
    pages = []
    for start in range(0, len(final_segments), per_page):
        chunk_batch = final_segments[start : start + per_page]
        is_last = start + per_page >= len(final_segments)
        pages.append(
            {
                "success": True,
                "bridge_version": 4,
                "thread_id": thread_id,
                "snapshot_before": "2026-09-19T00:00:00.000Z",
                "message_count": len(messages),
                "messages_completed": 0,
                "manifest_sha256": f"manifest-{thread_id}",
                "segments": chunk_batch,
                "next_cursor": "" if is_last else f"cursor-{thread_id}-{start}",
                "complete": is_last,
            }
        )
    seen_messages = set()
    for page in pages:
        for segment in page["segments"]:
            seen_messages.add(segment["message_id"])
        page["messages_completed"] = len(seen_messages)
    return pages


class FakeClient:
    """BrokerClient stand-in with scripted list/read responses."""

    def __init__(self, threads, snapshot="2026-09-19T00:00:00.000Z"):
        self.threads = threads  # {thread_id: [pages]}
        self.snapshot = snapshot
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "gmail_list_threads":
            return json.dumps(
                {
                    "success": True,
                    "bridge_version": 4,
                    "query": params["query"],
                    "snapshot_before": self.snapshot,
                    "thread_ids": list(self.threads.keys()),
                    "next_page_token": "",
                    "complete": True,
                }
            )
        if method == "gmail_read_thread_page":
            pages = self.threads[params["thread_id"]]
            cursor = params.get("cursor", "")
            if cursor == "":
                return json.dumps(pages[0])
            for index, page in enumerate(pages[:-1]):
                if page["next_cursor"] == cursor:
                    return json.dumps(pages[index + 1])
            return json.dumps({"success": False, "error": "cursor not found"})
        raise AssertionError(f"unexpected method {method}")


def sample_threads():
    return {
        "t-alpha": build_thread_pages(
            "t-alpha",
            [
                ("2026-09-01T00:00:00.000Z", "A <a@avaya.com>", ["alpha body one"]),
                (
                    "2026-09-02T00:00:00.000Z",
                    "B <b@avaya.com>",
                    ["chunk one ", "chunk two ", "chunk three"],
                ),
            ],
        ),
        "t-beta": build_thread_pages(
            "t-beta",
            [
                ("2026-09-03T00:00:00.000Z", "C <c@avaya.com>", ["beta body"]),
            ],
        ),
    }


class CollectPassTests(unittest.TestCase):
    def run_collect(self, threads, case_id="INC123", resume=False, client_factory=None):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name)
        if client_factory is None:
            client_factory = lambda: FakeClient(threads)
        code = gcc.collect_case(case_id, data_dir, resume=resume, client_factory=client_factory)
        paths = gcc.collection_paths(data_dir, gcc.normalize_case_id(case_id))
        return code, paths, data_dir

    def test_pass_end_to_end_writes_manifest_corpus_digest(self):
        code, paths, _ = self.run_collect(sample_threads())
        self.assertEqual(code, 0)
        manifest = json.loads(paths["stable_manifest"].read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "pass")
        ledger = manifest["ledger"]
        self.assertEqual(ledger["unique_threads_discovered"], 2)
        self.assertEqual(ledger["messages_completed"], 3)
        self.assertEqual(ledger["messages_expected"], 3)
        self.assertEqual(ledger["body_hashes_verified"], 3)
        self.assertEqual(ledger["manifest_hashes_stable"], 2)
        self.assertEqual(ledger["message_chunks_completed"], 5)
        self.assertEqual(ledger["record_id_queries_completed"], 1)
        self.assertTrue((paths["stable"] / "corpus.json").exists())
        self.assertLess(
            (paths["stable"] / "digest.json").stat().st_size,
            gcc.DIGEST_SIZE_LIMIT_BYTES,
        )

    def test_collect_exhausts_successive_thread_cursor_pages(self):
        threads = {
            "t-long": build_thread_pages(
                "t-long",
                [("2026-09-01T00:00:00.000Z", "A <a@avaya.com>", ["one", "two", "three"])],
                per_page=1,
            )
        }
        client = FakeClient(threads)
        code, paths, _ = self.run_collect(threads, client_factory=lambda: client)
        self.assertEqual(code, 0)
        corpus = json.loads((paths["stable"] / "corpus.json").read_text(encoding="utf-8"))
        self.assertEqual(corpus["threads"][0]["messages"][0]["body"], "onetwothree")
        cursors = [
            params["cursor"]
            for method, params in client.calls
            if method == "gmail_read_thread_page"
        ]
        self.assertEqual(cursors, ["", "cursor-t-long-0", "cursor-t-long-1"])

    def test_second_collection_rotates_previous(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name)
        code = gcc.collect_case(
            "INC123", data_dir, client_factory=lambda: FakeClient(sample_threads())
        )
        self.assertEqual(code, 0)
        paths = gcc.collection_paths(data_dir, "INC123")
        first_manifest = paths["stable_manifest"].read_text(encoding="utf-8")
        code = gcc.collect_case(
            "INC123", data_dir, client_factory=lambda: FakeClient(sample_threads())
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            (paths["previous"] / "manifest.json").read_text(encoding="utf-8"),
            first_manifest,
        )

    def test_failed_promotion_restores_the_prior_stable_collection(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            first_threads = sample_threads()
            self.assertEqual(
                gcc.collect_case(
                    "INC123", data_dir, client_factory=lambda: FakeClient(first_threads)
                ),
                0,
            )
            paths = gcc.collection_paths(data_dir, "INC123")
            replacement_threads = sample_threads()
            replacement_threads["t-beta"] = build_thread_pages(
                "t-beta",
                [("2026-09-03T00:00:00.000Z", "C <c@avaya.com>", ["new body"])],
            )
            self.assertEqual(
                gcc.collect_case(
                    "INC123",
                    data_dir,
                    client_factory=lambda: FakeClient(replacement_threads),
                ),
                0,
            )
            original_corpus = (paths["stable"] / "corpus.json").read_bytes()
            original_backup = (paths["previous"] / "corpus.json").read_bytes()
            third_threads = sample_threads()
            third_threads["t-beta"] = build_thread_pages(
                "t-beta",
                [("2026-09-03T00:00:00.000Z", "C <c@avaya.com>", ["third body"])],
            )
            original_rename = Path.rename

            def fail_staging_promotion(source, target):
                if source == paths["staging"] and Path(target) == paths["stable"]:
                    raise OSError("injected second rename failure")
                return original_rename(source, target)

            with patch.object(Path, "rename", fail_staging_promotion):
                code = gcc.collect_case(
                    "INC123",
                    data_dir,
                    client_factory=lambda: FakeClient(third_threads),
                )
            self.assertEqual(code, 1)
            self.assertEqual((paths["stable"] / "corpus.json").read_bytes(), original_corpus)
            self.assertEqual((paths["previous"] / "corpus.json").read_bytes(), original_backup)
            self.assertTrue(paths["staging"].is_dir())
            self.assertFalse(paths["promotion_backup"].exists())

    def test_promotion_recovers_an_interrupted_prior_rename(self):
        with TemporaryDirectory() as tmp:
            paths = gcc.collection_paths(Path(tmp), "INC123")
            paths["previous"].mkdir(parents=True)
            paths["staging"].mkdir()
            (paths["previous"] / "old.txt").write_text("old", encoding="utf-8")
            (paths["staging"] / "new.txt").write_text("new", encoding="utf-8")

            gcc.promote_collection(paths)

            self.assertEqual((paths["stable"] / "new.txt").read_text(encoding="utf-8"), "new")
            self.assertEqual((paths["previous"] / "old.txt").read_text(encoding="utf-8"), "old")

    def test_digest_contains_message_index_and_thread_rollup(self):
        code, paths, _ = self.run_collect(sample_threads())
        digest = json.loads(
            (paths["stable"] / "digest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(digest["messages"]), 3)
        self.assertEqual(len(digest["threads"]), 2)
        entry = digest["messages"][0]
        self.assertIsInstance(entry, list)
        self.assertEqual(entry[6], "Re: SR case thread msg-t-alpha-0")

    def test_ledger_equalities_helper(self):
        ledger = gcc.build_ledger(["a", "b"], 1, [])
        passed, failures = gcc.ledger_passes(ledger)
        self.assertFalse(passed)
        self.assertTrue(any("unique_threads_discovered" in f for f in failures))


class CollectFailureTests(unittest.TestCase):
    def test_failed_list_does_not_claim_completed_query(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        class FailingList:
            def request(self, method, params):
                raise RuntimeError("broker unavailable")

        with TemporaryDirectory() as tmp:
            output = io.StringIO()
            error_output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(error_output):
                code = gcc.collect_case(
                    "INC123", Path(tmp), client_factory=FailingList
                )
        self.assertEqual(code, 1)
        self.assertIn("Record-ID queries: 0/1", output.getvalue())
        self.assertIn("Gmail threads: 0/unknown", output.getvalue())
        self.assertIn("Gmail messages: 0/unknown", output.getvalue())
        self.assertIn(
            "no frozen snapshot was saved; re-run collect without --resume",
            error_output.getvalue(),
        )
        self.assertNotIn("re-run with --resume to continue", error_output.getvalue())

    def test_message_count_mismatch_blocks(self):
        threads = sample_threads()
        for page in threads["t-beta"]:
            page["message_count"] = 5
        with self.assertRaises(gcc.CollectionError) as raised:
            gcc.thread_page_stats(threads["t-beta"])
        self.assertEqual(getattr(raised.exception, "code", ""), "COVERAGE")

    def test_body_hash_corruption_raises_body_verify(self):
        pages = build_thread_pages(
            "t-alpha",
            [("2026-09-01T00:00:00.000Z", "A <a@avaya.com>", ["good body"])],
        )
        pages[0]["segments"][0]["body_chunk"] = "tampered body"
        with self.assertRaises(gcc.CollectionError) as raised:
            gcc.reassemble_messages(pages)
        self.assertEqual(raised.exception.code if hasattr(raised.exception, "code") else "", "BODY_VERIFY")

    def test_repeated_cursor_rejected(self):
        threads = sample_threads()
        client = FakeClient(threads)
        threads["t-beta"][0]["next_cursor"] = "loop"
        threads["t-beta"][0]["complete"] = False
        # second page also points at loop
        threads["t-beta"].append(dict(threads["t-beta"][0]))
        with self.assertRaises(gcc.CollectionError):
            gcc.read_thread(client, "t-beta", "2026-09-19T00:00:00.000Z")

    def test_thread_page_must_keep_the_requested_snapshot(self):
        pages = build_thread_pages(
            "t-alpha",
            [("2026-09-01T00:00:00.000Z", "A <a@avaya.com>", ["body"])],
        )
        pages[0]["snapshot_before"] = "2026-09-20T00:00:00.000Z"
        client = FakeClient({"t-alpha": pages})
        with self.assertRaises(gcc.CollectionError) as raised:
            gcc.read_thread(client, "t-alpha", "2026-09-19T00:00:00.000Z")
        self.assertEqual(raised.exception.code, "PROTOCOL")

    def test_missing_chunk_rejected(self):
        pages = build_thread_pages(
            "t-alpha",
            [("2026-09-01T00:00:00.000Z", "A <a@avaya.com>", ["one ", "two ", "three "])],
        )
        # drop chunk 1 from the only page
        pages[0]["segments"] = [
            s for s in pages[0]["segments"] if s["chunk_index"] != 1
        ]
        with self.assertRaises(gcc.CollectionError) as raised:
            gcc.reassemble_messages(pages)
        self.assertEqual(getattr(raised.exception, "code", ""), "BODY_VERIFY")


class ResumeTests(unittest.TestCase):
    def stopped_after_alpha(self, data_dir, threads):
        class FailingOnBeta(FakeClient):
            def request(self, method, params):
                if method == "gmail_read_thread_page" and params["thread_id"] == "t-beta":
                    raise RuntimeError("broker exploded")
                return super().request(method, params)

        code = gcc.collect_case(
            "INC123", data_dir, client_factory=lambda: FailingOnBeta(threads)
        )
        self.assertEqual(code, 1)
        return gcc.collection_paths(data_dir, "INC123")

    def test_resume_preserves_snapshot_and_skips_completed(self):
        import io
        from contextlib import redirect_stdout

        threads = sample_threads()
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            blocked_output = io.StringIO()
            with redirect_stdout(blocked_output):
                paths = self.stopped_after_alpha(data_dir, threads)
            self.assertIn("Record-ID queries: 1/1", blocked_output.getvalue())
            self.assertIn("Gmail threads: 1/2", blocked_output.getvalue())
            self.assertIn("Gmail messages: 2/unknown", blocked_output.getvalue())
            progress = json.loads(paths["progress"].read_text(encoding="utf-8"))
            self.assertEqual(progress["completed_threads"], {})
            self.assertTrue(
                gcc.thread_checkpoint_path(paths["checkpoints"], "t-alpha").is_file()
            )
            self.assertFalse(
                gcc.thread_checkpoint_path(paths["checkpoints"], "t-beta").exists()
            )

            good_client = FakeClient(threads)
            code = gcc.collect_case(
                "INC123",
                data_dir,
                resume=True,
                client_factory=lambda: good_client,
            )
            self.assertEqual(code, 0)
            list_calls = [c for c in good_client.calls if c[0] == "gmail_list_threads"]
            self.assertEqual(len(list_calls), 1)
            self.assertEqual(
                list_calls[0][1]["snapshot_before"], progress["snapshot_before"]
            )
            beta_reads = [
                c
                for c in good_client.calls
                if c[0] == "gmail_read_thread_page" and c[1]["thread_id"] == "t-beta"
            ]
            self.assertTrue(beta_reads)
            alpha_reads = [
                params
                for method, params in good_client.calls
                if method == "gmail_read_thread_page" and params["thread_id"] == "t-alpha"
            ]
            self.assertEqual(len(alpha_reads), 1)
            self.assertEqual(alpha_reads[0]["cursor"], "")
            manifest = json.loads(paths["stable_manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "pass")
            self.assertEqual(manifest["snapshot_before"], progress["snapshot_before"])

    def test_resume_rejects_a_corrupt_checkpoint(self):
        threads = sample_threads()
        for corruption in ("body", "count", "snapshot"):
            with self.subTest(corruption=corruption), TemporaryDirectory() as tmp:
                data_dir = Path(tmp)
                paths = self.stopped_after_alpha(data_dir, threads)
                checkpoint_path = gcc.thread_checkpoint_path(
                    paths["checkpoints"], "t-alpha"
                )
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                payload = checkpoint["payload"]
                if corruption == "body":
                    payload["state"]["messages"][0]["body"] = "tampered"
                elif corruption == "count":
                    payload["state"]["stats"]["message_count"] += 1
                else:
                    payload["snapshot_before"] = "2026-09-20T00:00:00.000Z"
                checkpoint["sha256"] = gcc.canonical_hash(payload)
                checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

                good_client = FakeClient(threads)
                code = gcc.collect_case(
                    "INC123", data_dir, resume=True, client_factory=lambda: good_client
                )
                self.assertEqual(code, 1)
                self.assertEqual(
                    [method for method, _params in good_client.calls],
                    ["gmail_list_threads"],
                )
                self.assertFalse(paths["stable_manifest"].exists())

    def test_resume_rejects_a_changed_frozen_thread_list(self):
        threads = sample_threads()
        for saved_ids in (["t-alpha"], ["t-beta", "t-alpha"]):
            with self.subTest(saved_ids=saved_ids), TemporaryDirectory() as tmp:
                data_dir = Path(tmp)
                paths = self.stopped_after_alpha(data_dir, threads)
                progress = json.loads(paths["progress"].read_text(encoding="utf-8"))
                progress["thread_ids"] = saved_ids
                paths["progress"].write_text(json.dumps(progress), encoding="utf-8")

                good_client = FakeClient(threads)
                code = gcc.collect_case(
                    "INC123", data_dir, resume=True, client_factory=lambda: good_client
                )
                self.assertEqual(code, 1)
                self.assertEqual(
                    [method for method, _params in good_client.calls],
                    ["gmail_list_threads"],
                )
                self.assertFalse(paths["stable_manifest"].exists())

    def test_resume_rejects_a_changed_thread_manifest(self):
        threads = sample_threads()
        for changed_field in ("manifest_sha256", "message_count"):
            with self.subTest(changed_field=changed_field), TemporaryDirectory() as tmp:
                data_dir = Path(tmp)
                paths = self.stopped_after_alpha(data_dir, threads)

                class ChangedThread(FakeClient):
                    def request(self, method, params):
                        raw = super().request(method, params)
                        if method == "gmail_read_thread_page" and params["thread_id"] == "t-alpha":
                            page = json.loads(raw)
                            if changed_field == "manifest_sha256":
                                page[changed_field] = "new-pre-cutoff-message-set"
                            else:
                                page[changed_field] += 1
                            return json.dumps(page)
                        return raw

                client = ChangedThread(threads)
                code = gcc.collect_case(
                    "INC123", data_dir, resume=True, client_factory=lambda: client
                )
                self.assertEqual(code, 1)
                self.assertEqual(
                    [method for method, _params in client.calls],
                    ["gmail_list_threads", "gmail_read_thread_page"],
                )
                self.assertFalse(paths["stable_manifest"].exists())

    def test_resume_migrates_legacy_inline_progress(self):
        threads = sample_threads()
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            paths = self.stopped_after_alpha(data_dir, threads)
            checkpoint_path = gcc.thread_checkpoint_path(
                paths["checkpoints"], "t-alpha"
            )
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            state = checkpoint["payload"]["state"]
            progress = json.loads(paths["progress"].read_text(encoding="utf-8"))
            progress["completed_threads"] = {"t-alpha": {**state, "pages": threads["t-alpha"]}}
            paths["progress"].write_text(json.dumps(progress), encoding="utf-8")
            checkpoint_path.unlink()

            good_client = FakeClient(threads)
            code = gcc.collect_case(
                "INC123", data_dir, resume=True, client_factory=lambda: good_client
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                sum(
                    method == "gmail_read_thread_page" and params["thread_id"] == "t-alpha"
                    for method, params in good_client.calls
                ),
                1,
            )
            saved_progress = json.loads(
                (paths["stable"] / "progress.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved_progress["completed_threads"], {})
            self.assertTrue(
                gcc.thread_checkpoint_path(paths["stable"] / "threads", "t-alpha").is_file()
            )


class CheckpointWriteTests(unittest.TestCase):
    def test_many_threads_write_one_checkpoint_each(self):
        threads = {
            f"t-{index}": build_thread_pages(
                f"t-{index}",
                [
                    (
                        "2026-09-01T00:00:00.000Z",
                        "A <a@avaya.com>",
                        [f"thread {index} " + "x" * 8_000],
                    )
                ],
            )
            for index in range(30)
        }
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            paths = gcc.collection_paths(data_dir, "INC123")
            writes = []
            original_atomic_write = gcc.atomic_write

            def count_staging_writes(path, content):
                if path == paths["progress"] or path.parent == paths["checkpoints"]:
                    writes.append((path, len(content.encode("utf-8"))))
                original_atomic_write(path, content)

            with patch.object(gcc, "atomic_write", side_effect=count_staging_writes):
                code = gcc.collect_case(
                    "INC123", data_dir, client_factory=lambda: FakeClient(threads)
                )
            self.assertEqual(code, 0)
            progress_bytes = [size for path, size in writes if path == paths["progress"]]
            checkpoint_bytes = [
                size for path, size in writes if path.parent == paths["checkpoints"]
            ]
            self.assertEqual(len(progress_bytes), 2)
            self.assertEqual(len(checkpoint_bytes), len(threads))
            corpus_bytes = (paths["stable"] / "corpus.json").stat().st_size
            self.assertLess(sum(progress_bytes) + sum(checkpoint_bytes), 2 * corpus_bytes)


class QueryTests(unittest.TestCase):
    def collected(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name)
        code = gcc.collect_case(
            "INC123", data_dir, client_factory=lambda: FakeClient(sample_threads())
        )
        self.assertEqual(code, 0)
        return data_dir

    def snippets_for_messages(self, messages, **options):
        import io
        from contextlib import redirect_stdout

        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name)
        stable = gcc.collection_paths(data_dir, "INC123")["stable"]
        stable.mkdir(parents=True)
        corpus = {
            "snapshot_before": "2026-09-19T00:00:00.000Z",
            "threads": [
                {
                    "thread_id": "t-alpha",
                    "messages": [
                        {
                            "message_id": f"m-{index}",
                            "internal_date": f"2026-09-19T00:00:{index:02d}.000Z",
                            "from": "a@avaya.com",
                            "subject": subject,
                            "attachment_names": [],
                            "body": body,
                        }
                        for index, (subject, body) in enumerate(messages)
                    ],
                }
            ],
        }
        (stable / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            code = gcc.query_snippets(
                "INC123",
                data_dir,
                terms=options.get("terms", ["target"]),
                chars=options.get("chars", 100),
                context_chars=options.get("context_chars", 20),
                max_per_message=options.get("max_per_message", 2),
            )
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def test_query_filters_and_budget(self):
        data_dir = self.collected()
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = gcc.query_corpus(
                "INC123",
                data_dir,
                thread_id=None,
                message_id=None,
                sender="b@avaya.com",
                since=None,
                chars=10,
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["matched"], 1)
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["messages"][0]["body_chars"], 10)

    def test_query_requires_corpus(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(
                gcc.main([f"--data-dir={tmp}", "query", "--case-id", "INC999"]), 2
            )

    def test_snippets_scan_complete_corpus_and_return_bounded_matches(self):
        data_dir = self.collected()
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = gcc.query_snippets(
                "INC123",
                data_dir,
                terms=["chunk", "missing-term"],
                chars=100,
                context_chars=18,
                max_per_message=2,
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["scanned_messages"], 3)
        self.assertEqual(payload["matched_messages"], 1)
        self.assertEqual(payload["snippet_count"], 2)
        self.assertLessEqual(
            sum(len(item) for item in payload["messages"][0]["snippets"]),
            36,
        )
        self.assertTrue(
            all(
                "chunk" in item.casefold()
                for item in payload["messages"][0]["snippets"]
            )
        )

    def test_snippets_cli_requires_a_search_term(self):
        data_dir = self.collected()
        with self.assertRaises(SystemExit):
            gcc.main(
                [
                    f"--data-dir={data_dir}",
                    "snippets",
                    "--case-id",
                    "INC123",
                ]
            )

    def test_snippets_use_original_offsets_after_unicode_casefold(self):
        payload = self.snippets_for_messages(
            [("other", "ß" * 100 + " target " + "x" * 300)]
        )
        self.assertEqual(payload["scanned_messages"], 1)
        self.assertFalse(payload["truncated"])
        self.assertIn("target", payload["messages"][0]["snippets"][0])

    def test_snippets_keep_the_full_match_in_narrow_context(self):
        payload = self.snippets_for_messages(
            [("other", "prefix target suffix")], context_chars=8
        )
        snippet = payload["messages"][0]["snippets"][0]
        self.assertIn("target", snippet)
        self.assertLessEqual(len(snippet), 8)
        self.assertFalse(payload["truncated"])

        oversized = self.snippets_for_messages(
            [("other", "prefix extraordinary suffix")],
            terms=["extraordinary"],
            context_chars=5,
        )
        self.assertEqual(oversized["messages"][0]["snippets"], ["extra"])
        self.assertTrue(oversized["truncated"])

    def test_snippets_include_subject_only_matches_with_empty_bodies(self):
        payload = self.snippets_for_messages([("Status target review", "")])
        self.assertEqual(payload["matching_messages_total"], 1)
        self.assertEqual(payload["matched_messages"], 1)
        self.assertEqual(payload["messages"][0]["snippet_source"], "subject")
        self.assertIn("target", payload["messages"][0]["snippets"][0])
        self.assertFalse(payload["truncated"])

    def test_snippets_count_all_messages_after_budget_is_exhausted(self):
        messages = [("other", "target"), ("other", "target")]
        limited = self.snippets_for_messages(
            messages, chars=6, context_chars=8
        )
        self.assertEqual(limited["scanned_messages"], 2)
        self.assertEqual(limited["matching_messages_total"], 2)
        self.assertEqual(limited["matched_messages"], 1)
        self.assertTrue(limited["truncated"])

        complete = self.snippets_for_messages(
            messages, chars=12, context_chars=8
        )
        self.assertEqual(complete["matched_messages"], 2)
        self.assertEqual(
            [item["message_id"] for item in complete["messages"]],
            ["m-0", "m-1"],
        )
        self.assertFalse(complete["truncated"])

    def test_snippets_do_not_accumulate_every_repeated_match(self):
        import tracemalloc

        tracemalloc.start()
        try:
            payload = self.snippets_for_messages(
                [("other", "a" * 500_000)],
                terms=["a"],
                chars=1000,
                context_chars=80,
                max_per_message=1,
            )
            peak_bytes = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(payload["snippet_count"], 1)
        self.assertTrue(payload["truncated"])
        self.assertLess(peak_bytes, 10 * 1024 * 1024)


class DigestBudgetTests(unittest.TestCase):
    def test_digest_degrades_to_threads_when_over_budget(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = Path(tmp.name)
        original = gcc.DIGEST_SIZE_LIMIT_BYTES
        code = gcc.collect_case(
            "INC123", data_dir, client_factory=lambda: FakeClient(sample_threads())
        )
        self.assertEqual(code, 0)
        paths = gcc.collection_paths(data_dir, "INC123")
        full_size = (paths["stable"] / "digest.json").stat().st_size
        gcc.DIGEST_SIZE_LIMIT_BYTES = full_size - 1
        try:
            code = gcc.collect_case(
                "INC123", data_dir, client_factory=lambda: FakeClient(sample_threads())
            )
            self.assertEqual(code, 0)
            digest = json.loads(
                (paths["stable"] / "digest.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("messages", digest)
            manifest = json.loads(
                paths["stable_manifest"].read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["digest_degraded"])
        finally:
            gcc.DIGEST_SIZE_LIMIT_BYTES = original


class LayoutBootstrapTests(unittest.TestCase):
    def test_repo_layout_resolves(self):
        tools_dir = gcc.resolve_gmail_tools_dir()
        self.assertEqual(tools_dir, ROOT / "tools" / "gmail")
        self.assertTrue((tools_dir / "gmail_broker_client.py").is_file())

    def test_env_override_and_error(self):
        with TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "gmail"
            candidate.mkdir()
            (candidate / "gmail_broker_client.py").write_text("", encoding="utf-8")
            os.environ["GMAIL_TOOLS_DIR"] = str(candidate)
            try:
                self.assertEqual(gcc.resolve_gmail_tools_dir(), candidate.resolve())
            finally:
                del os.environ["GMAIL_TOOLS_DIR"]
            os.environ["GMAIL_TOOLS_DIR"] = str(Path(tmp) / "missing")
            try:
                with self.assertRaises(gcc.CollectionError):
                    gcc.resolve_gmail_tools_dir()
            finally:
                del os.environ["GMAIL_TOOLS_DIR"]

    def test_deployed_layout_import_smoke(self):
        """The script must import its broker client from a simulated installed
        Antigravity layout when GMAIL_TOOLS_DIR points there."""

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            gmail_dir = root / "tools" / "gmail"
            gmail_dir.mkdir(parents=True)
            (gmail_dir / "gmail_broker_client.py").write_text(
                "class BrokerClientError(RuntimeError):\n"
                "    pass\n"
                "\n"
                "\n"
                "class BrokerClient:\n"
                "    def request(self, method, params):\n"
                "        raise RuntimeError('stub broker offline')\n",
                encoding="utf-8",
            )
            (gmail_dir / "__init__.py").write_text("", encoding="utf-8")
            (root / "tools" / "__init__.py").write_text("", encoding="utf-8")
            # simulate the deployed plugin depth: config/plugins/avaya-case-review/skills/case-review/scripts/
            script_dest = (
                root
                / "home/.gemini/config/plugins/avaya-case-review/skills/"
                "case-review/scripts/gmail_collect_case.py"
            )
            script_dest.parent.mkdir(parents=True)
            script_dest.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
            data_dir = root / "data"
            environment = dict(os.environ)
            environment["GMAIL_TOOLS_DIR"] = str(gmail_dir)
            environment["CASE_REVIEW_DATA_DIR"] = str(data_dir)
            result = subprocess.run(
                [sys.executable, str(script_dest), "collect", "--case-id", "INC1"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                timeout=60,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Context collection incomplete", result.stdout)
            # import succeeded: the failure came from the stub broker, not IMPORT_PATH
            self.assertNotIn("IMPORT_PATH", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
