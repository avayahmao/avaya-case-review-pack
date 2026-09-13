import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools.gmail import gmail_brokerctl
from tools.gmail.cloud.bridge_identity import (
    CONTRACT_REVISION,
    BRIDGE_PROTOCOL_VERSION,
    validate_source_identity,
    write_attestation,
)
from tools.gmail.gmail_broker_client import (
    BrokerClientError,
    BrokerProtocolMismatch,
    BrokerStartTimeout,
    BrokerUnavailable,
)


def make_health_result(**overrides):
    result = {
        "protocol_version": 1,
        "pid": 12345,
        "edge_state": "AUTHENTICATED",
        "queue_depth": 0,
        "request_count": 7,
        "browser_start_count": 1,
        "browser_crash_count": 0,
        "current_browser_concurrency": 0,
        "max_browser_concurrency": 1,
        "build_id": "test-build",
        "instance_id": "test-instance",
        "uptime_seconds": 60,
    }
    result.update(overrides)
    return result


class RecordingClient:
    def __init__(self, results=None, error=None):
        self.results = results or {}
        self.error = error
        self.calls = []

    def request(self, method, params):
        self.calls.append(("request", method, params))
        if self.error is not None:
            raise self.error
        return self.results[method]

    def request_existing(self, method, params):
        self.calls.append(("request_existing", method, params))
        if self.error is not None:
            raise self.error
        return self.results[method]


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = ROOT / "tools/gmail/cloud/GmailMcpBridge.gs"
PLUGIN_VERSION = "1.10.1"


def make_capabilities(**overrides):
    result = {
        "success": True,
        "bridge_version": BRIDGE_PROTOCOL_VERSION,
        "contract_revision": CONTRACT_REVISION,
        "bridge_source_sha256": validate_source_identity(
            BRIDGE_SOURCE.read_text(encoding="utf-8")
        ),
        "capabilities": {
            "stable_snapshots": True,
            "thread_pagination": True,
            "cursor_pagination": True,
            "manifest_sha256": True,
            "body_bytes": True,
            "body_sha256": True,
        },
    }
    result.update(overrides)
    return result


def run_cli(command, client, *arguments):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = gmail_brokerctl.main([command, *arguments], client=client)
    return exit_code, json.loads(stdout.getvalue()), stderr.getvalue()


class VerifyBridgeTests(unittest.TestCase):
    def write_attestation(self, directory):
        path = Path(directory) / "bridge_release_attestation.json"
        write_attestation(
            BRIDGE_SOURCE,
            path,
            plugin_version=PLUGIN_VERSION,
            verified_at_utc="2026-09-09T12:34:56Z",
        )
        return path

    def run_verify(self, path, client):
        return run_cli(
            "verify-bridge",
            client,
            "--source",
            str(BRIDGE_SOURCE),
            "--attestation",
            str(path),
            "--plugin-version",
            PLUGIN_VERSION,
        )

    def test_verify_bridge_reports_only_compatible_result(self):
        with TemporaryDirectory() as directory:
            path = self.write_attestation(directory)
            client = RecordingClient({"bridge_capabilities": make_capabilities()})

            exit_code, payload, stderr = self.run_verify(path, client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("request", "bridge_capabilities", {})])
        self.assertEqual(
            payload,
            {"ok": True, "command": "verify-bridge", "result": {"compatible": True}},
        )
        self.assertEqual(stderr, "")

    def test_verify_bridge_does_not_construct_an_unbounded_client(self):
        with TemporaryDirectory() as directory:
            path = self.write_attestation(directory)
            client = RecordingClient({"bridge_capabilities": make_capabilities()})
            with patch.object(gmail_brokerctl, "BrokerClient", return_value=client) as factory:
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    exit_code = gmail_brokerctl.main(
                        [
                            "verify-bridge",
                            "--source",
                            str(BRIDGE_SOURCE),
                            "--attestation",
                            str(path),
                            "--plugin-version",
                            PLUGIN_VERSION,
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["result"], {"compatible": True})
        factory.assert_called_once_with(request_timeout=60)

    def test_verify_bridge_sanitizes_invalid_explicit_inputs(self):
        sentinel = "SENSITIVE_SOURCE_PATH_AND_VERSION"
        with TemporaryDirectory() as directory:
            path = self.write_attestation(directory)
            exit_code, payload, stderr = run_cli(
                "verify-bridge",
                RecordingClient({"bridge_capabilities": make_capabilities()}),
                "--source",
                str(Path(directory) / sentinel),
                "--attestation",
                str(path),
                "--plugin-version",
                sentinel,
            )

        self.assertEqual(exit_code, 30)
        self.assertEqual(payload["code"], "BRIDGE_INCOMPATIBLE")
        self.assertNotIn(sentinel, json.dumps(payload))
        self.assertNotIn(sentinel, stderr)

    def test_verify_bridge_sanitizes_unknown_live_response_fields(self):
        sentinel = "SENSITIVE_URL_IDENTITY_COOKIE_TOKEN_CASE_BODY_DIGEST"
        with TemporaryDirectory() as directory:
            path = self.write_attestation(directory)
            live = make_capabilities(
                url=sentinel,
                identity=sentinel,
                cookie=sentinel,
                token=sentinel,
                case_id=sentinel,
                body=sentinel,
                digest=sentinel,
            )
            exit_code, payload, stderr = self.run_verify(
                path,
                RecordingClient({"bridge_capabilities": live}),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["result"], {"compatible": True})
        self.assertNotIn(sentinel, json.dumps(payload))
        self.assertNotIn(sentinel, stderr)

    def test_verify_bridge_maps_broker_failures_to_existing_exit_codes(self):
        cases = (
            (BrokerClientError("AUTH_REQUIRED"), 10, "AUTH_REQUIRED"),
            (BrokerClientError("REQUEST_TIMEOUT"), 20, "REQUEST_TIMEOUT"),
            (BrokerUnavailable(), 20, "BROKER_UNAVAILABLE"),
        )
        with TemporaryDirectory() as directory:
            path = self.write_attestation(directory)
            for error, expected_exit, expected_code in cases:
                with self.subTest(code=expected_code):
                    exit_code, payload, stderr = self.run_verify(
                        path,
                        RecordingClient(error=error),
                    )
                    self.assertEqual(exit_code, expected_exit)
                    self.assertEqual(payload["code"], expected_code)
                    self.assertEqual(stderr, "")

    def test_verify_bridge_rejects_malformed_or_incompatible_live_responses(self):
        cases = (
            "malformed-json",
            {"bridge_version": 3},
        )
        valid = make_capabilities()
        for field, bad_value in (
            ("success", None),
            ("success", "true"),
            ("success", False),
            ("bridge_version", None),
            ("bridge_version", "4"),
            ("bridge_version", 3),
            ("contract_revision", None),
            ("contract_revision", "1"),
            ("contract_revision", 2),
            ("bridge_source_sha256", None),
            ("bridge_source_sha256", "not-a-digest"),
            ("bridge_source_sha256", "0" * 64),
            ("capabilities", None),
        ):
            invalid = dict(valid)
            invalid[field] = bad_value
            cases += (invalid,)
        for capability in valid["capabilities"]:
            missing = make_capabilities(capabilities=dict(valid["capabilities"]))
            del missing["capabilities"][capability]
            cases += (missing,)
            wrong_type = make_capabilities(capabilities=dict(valid["capabilities"]))
            wrong_type["capabilities"][capability] = "true"
            cases += (wrong_type,)
            false_value = make_capabilities(capabilities=dict(valid["capabilities"]))
            false_value["capabilities"][capability] = False
            cases += (false_value,)

        with TemporaryDirectory() as directory:
            path = self.write_attestation(directory)
            for live in cases:
                with self.subTest(live=repr(live)[:60]):
                    exit_code, payload, stderr = self.run_verify(
                        path,
                        RecordingClient({"bridge_capabilities": live}),
                    )
                    self.assertEqual(exit_code, 30)
                    self.assertEqual(payload["code"], "BRIDGE_INCOMPATIBLE")
                    self.assertEqual(stderr, "")

    def test_verify_bridge_rejects_duplicate_capabilities_json_without_echoing_it(self):
        sentinel = "DUPLICATE_SECRET_7b91"
        duplicate_json = (
            '{"success":true,"success":true,"bridge_version":4,'
            '"contract_revision":1,"bridge_source_sha256":"' + sentinel + '"}'
        )
        with TemporaryDirectory() as directory:
            path = self.write_attestation(directory)
            exit_code, payload, stderr = self.run_verify(
                path,
                RecordingClient({"bridge_capabilities": duplicate_json}),
            )

        self.assertEqual(exit_code, 30)
        self.assertEqual(payload["code"], "BRIDGE_INCOMPATIBLE")
        self.assertNotIn(sentinel, json.dumps(payload))
        self.assertNotIn(sentinel, stderr)


class CommandDispatchTests(unittest.TestCase):
    def test_status_requests_health(self):
        client = RecordingClient({"health": make_health_result()})

        exit_code, payload, stderr = run_cli("status", client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("request", "health", {})])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "status")
        self.assertEqual(stderr, "")

    def test_diagnostics_requests_health(self):
        client = RecordingClient({"health": make_health_result()})

        exit_code, payload, stderr = run_cli("diagnostics", client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("request", "health", {})])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "diagnostics")
        self.assertEqual(stderr, "")

    def test_start_requests_health(self):
        client = RecordingClient({"health": make_health_result()})

        exit_code, payload, stderr = run_cli("start", client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("request", "health", {})])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "start")
        self.assertEqual(stderr, "")

    def test_login_requests_auth_login(self):
        client = RecordingClient({"auth_login": {"state": "AUTHENTICATED"}})

        exit_code, payload, stderr = run_cli("login", client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(client.calls, [("request", "auth_login", {})])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "login")
        self.assertEqual(stderr, "")

    def test_stop_requests_existing_broker_shutdown(self):
        client = RecordingClient({"shutdown": {"stopping": True}})

        exit_code, payload, stderr = run_cli("stop", client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            client.calls,
            [("request_existing", "shutdown", {})],
        )
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["command"], "stop")
        self.assertEqual(stderr, "")


class SanitizedOutputTests(unittest.TestCase):
    def test_health_output_uses_a_strict_public_allowlist(self):
        sentinel = "SENSITIVE_EMAIL_CONTENT_7b91"
        health = make_health_result(
            token=sentinel,
            state_token=sentinel,
            params={"query": sentinel},
            email_content=sentinel,
        )
        client = RecordingClient({"health": health})

        exit_code, payload, _stderr = run_cli("diagnostics", client)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["result"], make_health_result())
        self.assertNotIn(sentinel, json.dumps(payload))

    def test_login_and_stop_outputs_drop_unapproved_fields(self):
        sentinel = "SENSITIVE_STATE_TOKEN_2d44"
        cases = (
            (
                "login",
                {"auth_login": {"state": "AUTHENTICATED", "state_token": sentinel}},
                {"state": "AUTHENTICATED"},
            ),
            (
                "stop",
                {"shutdown": {"stopping": True, "token": sentinel}},
                {"stopping": True},
            ),
        )
        for command, results, expected in cases:
            with self.subTest(command=command):
                exit_code, payload, _stderr = run_cli(
                    command,
                    RecordingClient(results),
                )
                self.assertEqual(exit_code, 0)
                self.assertEqual(payload["result"], expected)
                self.assertNotIn(sentinel, json.dumps(payload))

    def test_unexpected_result_shape_is_a_sanitized_invalid_error(self):
        sentinel = "SENSITIVE_RESULT_8841"
        client = RecordingClient({"health": [sentinel]})

        exit_code, payload, stderr = run_cli("status", client)

        self.assertEqual(exit_code, 30)
        self.assertEqual(payload["code"], "INVALID_REQUEST")
        self.assertEqual(payload["message"], "Broker returned an invalid result")
        self.assertNotIn(sentinel, json.dumps(payload))
        self.assertEqual(stderr, "")


class ExitCodeTests(unittest.TestCase):
    def test_typed_errors_map_to_stable_sanitized_exit_contract(self):
        sentinel = "SENSITIVE_REMOTE_MESSAGE_9912"
        cases = (
            (BrokerClientError("AUTH_REQUIRED", sentinel), 10, "AUTH_REQUIRED"),
            (BrokerUnavailable(sentinel), 20, "BROKER_UNAVAILABLE"),
            (BrokerStartTimeout(sentinel), 20, "BROKER_START_TIMEOUT"),
            (BrokerClientError("REQUEST_TIMEOUT", sentinel), 20, "REQUEST_TIMEOUT"),
            (BrokerClientError("BROWSER_ERROR", sentinel), 20, "BROWSER_ERROR"),
            (BrokerProtocolMismatch(sentinel), 30, "BROKER_PROTOCOL_MISMATCH"),
            (BrokerClientError("RESPONSE_TOO_LARGE", sentinel), 30, "RESPONSE_TOO_LARGE"),
            (BrokerClientError("APP_ERROR", sentinel), 30, "APP_ERROR"),
            (BrokerClientError("INVALID_REQUEST", sentinel), 30, "INVALID_REQUEST"),
            (BrokerClientError("LOGIN_IN_PROGRESS", sentinel), 30, "LOGIN_IN_PROGRESS"),
        )
        for error, expected_exit, expected_code in cases:
            with self.subTest(code=expected_code):
                exit_code, payload, stderr = run_cli(
                    "status",
                    RecordingClient(error=error),
                )
                self.assertEqual(exit_code, expected_exit)
                self.assertEqual(payload["code"], expected_code)
                self.assertNotIn(sentinel, json.dumps(payload))
                self.assertEqual(stderr, "")

    def test_status_reports_authentication_required_from_health(self):
        client = RecordingClient(
            {"health": make_health_result(edge_state="AUTH_REQUIRED_MICROSOFT")}
        )

        exit_code, payload, _stderr = run_cli("status", client)

        self.assertEqual(exit_code, 10)
        self.assertTrue(payload["ok"])

    def test_status_treats_unprobed_starting_broker_as_authentication_required(self):
        client = RecordingClient({"health": make_health_result(edge_state="STARTING")})

        exit_code, payload, _stderr = run_cli("status", client)

        self.assertEqual(exit_code, 10)
        self.assertTrue(payload["ok"])


class EntryPointTests(unittest.TestCase):
    def test_direct_and_package_help_work_without_browser_imports(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "tools/gmail/gmail_brokerctl.py"
        commands = (
            [sys.executable, str(script), "--help"],
            [sys.executable, "-m", "tools.gmail.gmail_brokerctl", "--help"],
        )
        with TemporaryDirectory() as tmp:
            for command in commands:
                with self.subTest(command=command):
                    completed = subprocess.run(
                        command,
                        cwd=tmp if str(script) in command else root,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertIn("status", completed.stdout)
                    self.assertIn("diagnostics", completed.stdout)

        imported = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import tools.gmail.gmail_brokerctl; "
                    "print(any(name.startswith('playwright') for name in sys.modules))"
                ),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.assertEqual(imported.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
