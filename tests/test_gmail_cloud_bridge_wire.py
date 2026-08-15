"""Cross-layer frame regression: GmailMcpBridge doGet output -> broker wire.

Runs the Node wire probe (which drives the real ``doGet`` of
``tools/gmail/cloud/GmailMcpBridge.gs`` against deterministic fixtures),
then feeds every emitted response page — including error pages — through the
broker's real ``encode_response`` so the JS emission budgets and the Python
frame encoding are verified against each other.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tools.gmail.gmail_broker_protocol import (
    MAX_FRAME_BYTES,
    BrokerErrorCode,
    BrokerResponse,
    ProtocolError,
    encode_response,
)

ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "tests" / "js" / "gmail_cloud_bridge_wire_probe.mjs"
ENVELOPE_LIMIT_BYTES = 1024


def _run_probe() -> bytes:
    node = shutil.which("node")
    if node is None:
        raise unittest.SkipTest("Node.js is required for the cloud bridge wire probe")
    completed = subprocess.run(
        [node, str(PROBE_PATH)],
        cwd=ROOT,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "wire probe failed:\n"
            f"stdout:\n{completed.stdout.decode('utf-8', 'replace')}\n"
            f"stderr:\n{completed.stderr.decode('utf-8', 'replace')}"
        )
    return completed.stdout


def _parse_records(data: bytes) -> list[tuple[str, bytes]]:
    records: list[tuple[str, bytes]] = []
    position = 0
    while position < len(data):
        newline = data.index(b"\n", position)
        name, _, length_text = data[position:newline].decode("ascii").partition(" ")
        length = int(length_text)
        payload = data[newline + 1 : newline + 1 + length]
        if len(payload) != length or data[newline + 1 + length : newline + 2 + length] != b"\n":
            raise AssertionError(f"malformed probe record frame for {name}")
        records.append((name, payload))
        position = newline + 2 + length
    return records


def _encoded_frame(payload: bytes) -> bytes:
    return encode_response(BrokerResponse.success("wire-test", payload.decode("utf-8")))


class GmailCloudBridgeWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = _parse_records(_run_probe())

    def test_probe_emitted_all_fixtures(self) -> None:
        names = [name for name, _ in self.records]
        self.assertIn("typical", names)
        self.assertIn("adversarial", names)
        self.assertIn("pass-domain", names)
        self.assertIn("oversized-refused", names)
        self.assertIn("oversized-error", names)

    def test_every_page_encodes_within_the_broker_frame_limit(self) -> None:
        pages = [(name, payload) for name, payload in self.records if name != "oversized-refused"]
        self.assertGreater(len(pages), 5)
        for name, payload in pages:
            with self.subTest(fixture=name, size=len(payload)):
                frame = _encoded_frame(payload)
                self.assertLessEqual(
                    len(frame),
                    MAX_FRAME_BYTES,
                    f"{name}: frame {len(frame)} exceeds {MAX_FRAME_BYTES}",
                )

    def test_inflation_model_matches_the_python_encoder(self) -> None:
        # frame == utf8(text) + quotes + backslashes + fixed envelope; any drift
        # between the JS budget model and the broker encoder breaks this.
        pages = [(name, payload) for name, payload in self.records if name != "oversized-refused"]
        for name, payload in pages:
            with self.subTest(fixture=name):
                frame = _encoded_frame(payload)
                escaped_estimate = (
                    len(payload) + payload.count(b'"') + payload.count(b"\\")
                )
                envelope = len(frame) - escaped_estimate
                self.assertGreater(envelope, 0, f"{name}: envelope underflow")
                self.assertLess(envelope, ENVELOPE_LIMIT_BYTES, f"{name}: envelope {envelope}")

    def test_error_page_is_returned_as_a_broker_frame(self) -> None:
        error_pages = [payload for name, payload in self.records if name == "oversized-error"]
        self.assertEqual(len(error_pages), 1)
        document = json.loads(error_pages[0].decode("utf-8"))
        self.assertEqual(document, {"success": False, "error": "RESPONSE_TOO_LARGE"})
        frame = _encoded_frame(error_pages[0])
        self.assertLessEqual(len(frame), MAX_FRAME_BYTES)

    def test_refused_segment_would_have_broken_the_v3_broker_limit(self) -> None:
        refused = [
            payload for name, payload in self.records if name == "oversized-refused"
        ]
        self.assertEqual(len(refused), 1)
        projected = json.loads(refused[0].decode("utf-8"))
        self.assertLessEqual(projected["inner"], 6 * 1024 * 1024)
        self.assertGreater(projected["wire"], 8 * 1024 * 1024)
        # Stand-in for the page JSON v3 would have serialized: quote-dense text
        # with the same inner size passes the cloud-side 6 MiB check but must
        # still be rejected by the broker's 8 MiB frame limit.
        stand_in = '"' * projected["inner"]
        with self.assertRaises(ProtocolError) as caught:
            encode_response(BrokerResponse.success("wire-test", stand_in))
        self.assertEqual(caught.exception.code, BrokerErrorCode.RESPONSE_TOO_LARGE)


if __name__ == "__main__":
    unittest.main()
