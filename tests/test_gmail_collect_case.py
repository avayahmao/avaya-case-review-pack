import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


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
            for page in pages:
                if page["next_cursor"] == cursor:
                    return json.dumps(page)
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
    def test_resume_preserves_snapshot_and_skips_completed(self):
        threads = sample_threads()

        class FailingOnBeta(FakeClient):
            def request(self, method, params):
                if method == "gmail_read_thread_page" and params["thread_id"] == "t-beta":
                    raise RuntimeError("broker exploded")
                return super().request(method, params)

        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            code = gcc.collect_case(
                "INC123", data_dir, client_factory=lambda: FailingOnBeta(threads)
            )
            self.assertEqual(code, 1)
            paths = gcc.collection_paths(data_dir, "INC123")
            progress = json.loads(paths["progress"].read_text(encoding="utf-8"))
            self.assertIn("t-alpha", progress["completed_threads"])
            self.assertNotIn("t-beta", progress["completed_threads"])

            good_client = FakeClient(threads)
            code = gcc.collect_case(
                "INC123",
                data_dir,
                resume=True,
                client_factory=lambda: good_client,
            )
            self.assertEqual(code, 0)
            list_calls = [c for c in good_client.calls if c[0] == "gmail_list_threads"]
            self.assertEqual(list_calls, [])
            beta_reads = [
                c
                for c in good_client.calls
                if c[0] == "gmail_read_thread_page" and c[1]["thread_id"] == "t-beta"
            ]
            self.assertTrue(beta_reads)
            manifest = json.loads(paths["stable_manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "pass")
            self.assertEqual(manifest["snapshot_before"], progress["snapshot_before"])


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
                env=environment,
                timeout=60,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Context collection incomplete", result.stdout)
            # import succeeded: the failure came from the stub broker, not IMPORT_PATH
            self.assertNotIn("IMPORT_PATH", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
