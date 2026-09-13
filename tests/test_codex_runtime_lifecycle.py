import json
import os
import socket
import subprocess
import sys
import threading
import unittest
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from avaya_case_review_runtime import __version__
from avaya_case_review_runtime.gmail_broker_protocol import (
    BrokerErrorCode,
    BrokerRequest,
    BrokerResponse,
    decode_request,
    encode_response,
)
from tools.gmail.cloud.bridge_identity import write_attestation


ROOT = Path(__file__).resolve().parents[1]


class IsolatedBroker:
    def __init__(self, response_for):
        self.response_for = response_for
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen()
        self.socket.settimeout(0.1)
        self.host, self.port = self.socket.getsockname()
        self.requests = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.stopped.set()
        self.socket.close()
        self.thread.join(timeout=2)

    def _serve(self):
        while not self.stopped.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                frame = b""
                while not frame.endswith(b"\n"):
                    chunk = connection.recv(64 * 1024)
                    if not chunk:
                        break
                    frame += chunk
                request = decode_request(frame)
                self.requests.append(request.method)
                connection.sendall(encode_response(self.response_for(request)))


class CodexRuntimeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / "python-target"
        self.outside = self.root / "outside"
        self.outside.mkdir()
        self.local_app_data = self.root / "local"
        self.state_file = (
            self.local_app_data / "AvayaCaseReview/gmail-broker/state.json"
        )
        self.attestation = self.root / "bridge_release_attestation.json"
        self.source = ROOT / "tools/gmail/cloud/GmailMcpBridge.gs"
        write_attestation(
            self.source,
            self.attestation,
            __version__,
            "2026-09-09T00:00:00Z",
        )

    def _environment(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(self.target)
        environment["LOCALAPPDATA"] = str(self.local_app_data)
        environment["USERPROFILE"] = str(self.root / "user")
        return environment

    def _install_candidate(self):
        candidate = self.root / "candidate"
        candidate.mkdir()
        shutil.copy2(ROOT / "pyproject.toml", candidate / "pyproject.toml")
        shutil.copytree(
            ROOT / "avaya_case_review_runtime",
            candidate / "avaya_case_review_runtime",
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-cache-dir",
                "--no-build-isolation",
                "--target",
                str(self.target),
                str(candidate),
            ],
            cwd=self.outside,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def _run_control(self, command):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "avaya_case_review_runtime.gmail_brokerctl",
                command,
                *(
                    [
                        "--source",
                        str(self.source),
                        "--attestation",
                        str(self.attestation),
                        "--plugin-version",
                        __version__,
                    ]
                    if command == "verify-bridge"
                    else []
                ),
            ],
            cwd=self.outside,
            env=self._environment(),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    def _publish(self, broker, build_id):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(
                {
                    "protocol_version": 1,
                    "build_id": build_id,
                    "instance_id": "isolated-lifecycle",
                    "pid": os.getpid(),
                    "host": broker.host,
                    "port": broker.port,
                    "token": "isolated-token",
                    "started_at": "2026-09-09T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _health(request: BrokerRequest, build_id: str):
        return BrokerResponse.success(
            request.id,
            {
                "protocol_version": 1,
                "pid": os.getpid(),
                "edge_state": "AUTHENTICATED",
                "queue_depth": 0,
                "request_count": 1,
                "browser_start_count": 1,
                "browser_crash_count": 0,
                "current_browser_concurrency": 0,
                "max_browser_concurrency": 1,
                "build_id": build_id,
                "instance_id": "isolated-lifecycle",
                "uptime_seconds": 1,
            },
        )

    def test_real_isolated_candidate_lifecycle_covers_clean_old_failure_and_success(self):
        self.assertFalse((self.target / "avaya_case_review_runtime").exists())
        self.assertFalse(self.state_file.exists())
        self._install_candidate()
        self.assertTrue((self.target / "avaya_case_review_runtime").is_dir())

        def old_response(request):
            if request.method == "health":
                return self._health(request, "1.10.0-old")
            if request.method == "shutdown":
                return BrokerResponse.success(request.id, {"stopping": True})
            return BrokerResponse.failure(
                request.id,
                BrokerErrorCode.INVALID_REQUEST,
                "unsupported method",
            )

        with IsolatedBroker(old_response) as old:
            self._publish(old, "1.10.0-old")
            rejected = self._run_control("verify-bridge")
            self.assertEqual(rejected.returncode, 30, rejected.stdout + rejected.stderr)
            stopped = self._run_control("stop")
            self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.state_file.unlink(missing_ok=True)

        attestation = json.loads(self.attestation.read_text(encoding="utf-8"))

        def candidate_response(request, *, compatible):
            if request.method == "health":
                return self._health(request, "candidate")
            if request.method == "bridge_capabilities":
                digest = attestation["bridge_source_sha256"] if compatible else "f" * 64
                return BrokerResponse.success(
                    request.id,
                    {
                        "success": True,
                        "bridge_version": attestation["bridge_version"],
                        "contract_revision": attestation["contract_revision"],
                        "bridge_source_sha256": digest,
                        "capabilities": {
                            "stable_snapshots": True,
                            "thread_pagination": True,
                            "cursor_pagination": True,
                            "manifest_sha256": True,
                            "body_bytes": True,
                            "body_sha256": True,
                        },
                    },
                )
            return BrokerResponse.success(request.id, {"stopping": True})

        with IsolatedBroker(lambda request: candidate_response(request, compatible=False)) as bad:
            self._publish(bad, "candidate")
            failed = self._run_control("verify-bridge")
            self.assertEqual(failed.returncode, 30, failed.stdout + failed.stderr)
        self.state_file.unlink(missing_ok=True)

        with IsolatedBroker(lambda request: candidate_response(request, compatible=True)) as good:
            self._publish(good, "candidate")
            verified = self._run_control("verify-bridge")
            self.assertEqual(
                verified.returncode,
                0,
                verified.stdout + verified.stderr + repr(good.requests),
            )
            self.assertIn('"compatible": true', verified.stdout)


if __name__ == "__main__":
    unittest.main()
