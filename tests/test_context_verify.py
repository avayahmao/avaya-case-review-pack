import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugins/avaya-case-review/skills/case-review/scripts/context_verify.py"
)


class ContextVerifyTests(unittest.TestCase):
    def write_json(self, directory, name, value):
        path = Path(directory) / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_verifies_case_notes_pages_segments_and_body_hashes(self):
        body = "A UTF-8 body — verified."
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_json(
                temporary,
                "case.json",
                {"success": True, "markdown": "# Case\n\n### Note 1\ntext\n### Note 2\ntext"},
            )
            listing = self.write_json(
                temporary,
                "list.json",
                {
                    "success": True,
                    "query": "1-20000000001",
                    "snapshot_before": "2026-09-16T00:00:00Z",
                    "thread_ids": ["thread-1"],
                    "next_page_token": "",
                    "complete": True,
                },
            )
            thread = self.write_json(
                temporary,
                "thread.json",
                {
                    "success": True,
                    "snapshot_before": "2026-09-16T00:00:00Z",
                    "thread_id": "thread-1",
                    "message_count": 1,
                    "manifest_sha256": "manifest",
                    "segments": [
                        {
                            "message_id": "message-1",
                            "thread_id": "thread-1",
                            "body_chunk": body,
                            "chunk_index": 0,
                            "chunk_count": 1,
                            "body_bytes": len(body.encode("utf-8")),
                            "body_sha256": digest,
                        }
                    ],
                    "next_cursor": None,
                    "complete": True,
                },
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--case-markdown",
                    str(case),
                    "--list-page",
                    str(listing),
                    "--thread-page",
                    str(thread),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["case_notes_discovered"], 2)
            self.assertEqual(result["unique_threads_discovered"], 1)
            self.assertEqual(result["messages_completed"], 1)
            self.assertEqual(result["message_chunks_completed"], 1)
            self.assertEqual(result["body_hashes_verified"], 1)

    def test_rejects_body_hash_mismatch_without_emitting_partial_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            case = self.write_json(
                temporary,
                "case.json",
                {"success": True, "markdown": "### Note"},
            )
            listing = self.write_json(
                temporary,
                "list.json",
                {
                    "success": True,
                    "query": "1-20000000001",
                    "snapshot_before": "2026-09-16T00:00:00Z",
                    "thread_ids": ["thread-1"],
                    "next_page_token": "",
                    "complete": True,
                },
            )
            thread = self.write_json(
                temporary,
                "thread.json",
                {
                    "success": True,
                    "snapshot_before": "2026-09-16T00:00:00Z",
                    "thread_id": "thread-1",
                    "message_count": 1,
                    "manifest_sha256": "manifest",
                    "segments": [
                        {
                            "message_id": "message-1",
                            "thread_id": "thread-1",
                            "body_chunk": "body",
                            "chunk_index": 0,
                            "chunk_count": 1,
                            "body_bytes": 4,
                            "body_sha256": "wrong",
                        }
                    ],
                    "next_cursor": None,
                    "complete": True,
                },
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--case-markdown",
                    str(case),
                    "--list-page",
                    str(listing),
                    "--thread-page",
                    str(thread),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("message-1", completed.stderr)
            self.assertNotIn("wrong", completed.stderr)


if __name__ == "__main__":
    unittest.main()
