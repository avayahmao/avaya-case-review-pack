import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from tools.gmail.gmail_broker_client import (
    CLIENT_TIMEOUT_SECONDS,
    STARTUP_TIMEOUT_SECONDS,
    BrokerClient,
    BrokerClientError,
    BrokerProtocolMismatch,
    BrokerStartTimeout,
    BrokerUnavailable,
)
from tools.gmail.gmail_broker_protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    BrokerErrorCode,
    BrokerRequest,
    BrokerResponse,
    decode_request,
    encode_response,
)
from tools.gmail.gmail_broker_state import (
    BrokerState,
    BrokerStateStore,
    StartupFileLock,
)


def make_health_result(**overrides):
    result = {
        "protocol_version": PROTOCOL_VERSION,
        "pid": os.getpid(),
        "edge_state": "AUTHENTICATED",
        "queue_depth": 0,
        "request_count": 1,
        "browser_start_count": 1,
        "browser_crash_count": 0,
        "current_browser_concurrency": 0,
        "max_browser_concurrency": 1,
        "build_id": "test-build",
        "instance_id": "test-instance",
        "uptime_seconds": 1,
    }
    result.update(overrides)
    return result


class FakeLoopbackBroker:
    def __init__(self, response_for):
        self.response_for = response_for
        self.requests: list[BrokerRequest] = []
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self._socket.settimeout(0.1)
        self.host, self.port = self._socket.getsockname()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self._stopped.set()
        self._socket.close()
        self._thread.join(timeout=2)

    def _serve(self):
        while not self._stopped.is_set():
            try:
                connection, _address = self._socket.accept()
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
                self.requests.append(request)
                response = self.response_for(request)
                encoded = response if isinstance(response, bytes) else encode_response(response)
                connection.sendall(encoded)


class FakeProcess:
    def __init__(self, return_code=None):
        self.return_code = return_code

    def poll(self):
        return self.return_code


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class ScriptedSocket:
    def __init__(self, response_for, *, on_send=None):
        self.response_for = response_for
        self.on_send = on_send
        self.response = b""
        self.closed = False
        self.timeouts = []
        self.sent = b""
        self.recv_calls = 0

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def sendall(self, frame):
        self.sent = frame
        request = json.loads(frame.decode("utf-8"))
        if self.on_send is not None:
            self.on_send(request)
        response = self.response_for(request)
        self.response = response if isinstance(response, bytes) else encode_response(response)

    def recv(self, size):
        self.recv_calls += 1
        chunk = self.response[:size]
        self.response = self.response[size:]
        return chunk

    def close(self):
        self.closed = True


class ScriptedSocketFactory:
    def __init__(self, *connections):
        self.pending = list(connections)
        self.connections = []
        self.calls = []

    def __call__(self, address, timeout):
        self.calls.append((address, timeout))
        connection = self.pending.pop(0)
        self.connections.append(connection)
        return connection


def write_state(store, broker, **overrides):
    values = {
        "protocol_version": PROTOCOL_VERSION,
        "build_id": "test-build",
        "instance_id": "test-instance",
        "pid": os.getpid(),
        "host": broker.host,
        "port": broker.port,
        "token": "test-token",
        "started_at": "2026-08-03T00:00:00Z",
    }
    values.update(overrides)
    state = BrokerState(**values)
    store.write(state)
    return state


class HealthyStateRequestTests(unittest.TestCase):
    def test_authenticated_health_precedes_correlated_request(self):
        sentinel = "SENSITIVE_QUERY_SENTINEL"

        def respond(request):
            if request.method == "health":
                return BrokerResponse.success(request.id, make_health_result())
            return BrokerResponse.success(request.id, {"messages": ["found"]})

        with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
            store = BrokerStateStore(Path(tmp), acl_applier=None)
            write_state(store, broker)
            client = BrokerClient(
                state_store=store,
                process_exists=lambda _pid: True,
            )

            result = client.request("gmail_search", {"query": sentinel})

        self.assertEqual(result, {"messages": ["found"]})
        self.assertEqual([item.method for item in broker.requests], ["health", "gmail_search"])
        self.assertTrue(all(item.version == PROTOCOL_VERSION for item in broker.requests))
        self.assertTrue(all(item.token == "test-token" for item in broker.requests))
        self.assertNotEqual(broker.requests[0].id, broker.requests[1].id)
        self.assertEqual(broker.requests[1].params, {"query": sentinel})


class ExistingBrokerRequestTests(unittest.TestCase):
    def test_missing_broker_is_unavailable_without_launching(self):
        launched = []

        with TemporaryDirectory() as tmp:
            client = BrokerClient(
                state_store=BrokerStateStore(Path(tmp), acl_applier=None),
                launcher=lambda *args, **kwargs: launched.append((args, kwargs)),
            )

            with self.assertRaises(BrokerUnavailable):
                client.request_existing("shutdown", {})

        self.assertEqual(launched, [])

    def test_healthy_existing_broker_receives_requested_method(self):
        launched = []

        def respond(request):
            if request.method == "health":
                return BrokerResponse.success(request.id, make_health_result())
            return BrokerResponse.success(request.id, {"stopping": True})

        with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
            store = BrokerStateStore(Path(tmp), acl_applier=None)
            write_state(store, broker)
            client = BrokerClient(
                state_store=store,
                process_exists=lambda _pid: True,
                launcher=lambda *args, **kwargs: launched.append((args, kwargs)),
            )

            result = client.request_existing("shutdown", {})

        self.assertEqual(result, {"stopping": True})
        self.assertEqual(
            [request.method for request in broker.requests],
            ["health", "shutdown"],
        )
        self.assertEqual(launched, [])


class ClientErrorContractTests(unittest.TestCase):
    def test_typed_errors_publish_stable_codes(self):
        self.assertEqual(CLIENT_TIMEOUT_SECONDS, 370)
        self.assertEqual(BrokerStartTimeout().code, "BROKER_START_TIMEOUT")
        self.assertEqual(BrokerUnavailable().code, "BROKER_UNAVAILABLE")
        self.assertEqual(BrokerProtocolMismatch().code, "BROKER_PROTOCOL_MISMATCH")

        remote = BrokerClientError("AUTH_REQUIRED", "Authentication required")
        self.assertEqual(remote.code, "AUTH_REQUIRED")
        self.assertEqual(str(remote), "Authentication required")

    def test_remote_errors_map_to_broker_client_error_codes(self):
        for code in BrokerErrorCode:
            with self.subTest(code=code.value):
                def respond(request, error_code=code):
                    if request.method == "health":
                        return BrokerResponse.success(request.id, make_health_result())
                    return BrokerResponse.failure(request.id, error_code, "Safe broker error")

                with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
                    store = BrokerStateStore(Path(tmp), acl_applier=None)
                    write_state(store, broker)
                    client = BrokerClient(
                        state_store=store,
                        process_exists=lambda _pid: True,
                    )

                    with self.assertRaises(BrokerClientError) as raised:
                        client.request("gmail_search", {"query": "case"})

                self.assertEqual(raised.exception.code, code.value)
                self.assertEqual(str(raised.exception), "Safe broker error")

    def test_mismatched_response_id_is_protocol_mismatch(self):
        def respond(request):
            if request.method == "health":
                return BrokerResponse.success(request.id, make_health_result())
            return BrokerResponse.success("different-request", {"messages": []})

        with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
            store = BrokerStateStore(Path(tmp), acl_applier=None)
            write_state(store, broker)
            client = BrokerClient(
                state_store=store,
                process_exists=lambda _pid: True,
            )

            with self.assertRaises(BrokerProtocolMismatch) as raised:
                client.request("gmail_search", {"query": "case"})

        self.assertEqual(raised.exception.code, "BROKER_PROTOCOL_MISMATCH")

    def test_state_protocol_mismatch_is_rejected_before_connecting(self):
        with TemporaryDirectory() as tmp:
            store = BrokerStateStore(Path(tmp), acl_applier=None)
            store.write(
                BrokerState(
                    protocol_version=PROTOCOL_VERSION + 1,
                    build_id="future-build",
                    instance_id="future-instance",
                    pid=os.getpid(),
                    host="127.0.0.1",
                    port=65535,
                    token="future-token",
                    started_at="2026-08-03T00:00:00Z",
                )
            )
            client = BrokerClient(
                state_store=store,
                process_exists=lambda _pid: True,
            )

            with self.assertRaises(BrokerProtocolMismatch):
                client.request("health", {})

    def test_health_protocol_version_requires_an_integer_match(self):
        def respond(request):
            return BrokerResponse.success(
                request.id,
                make_health_result(protocol_version=True),
            )

        with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
            store = BrokerStateStore(Path(tmp), acl_applier=None)
            write_state(store, broker)
            client = BrokerClient(
                state_store=store,
                process_exists=lambda _pid: True,
            )

            with self.assertRaises(BrokerProtocolMismatch):
                client.request("health", {})


class LazyStartupTests(unittest.TestCase):
    def test_default_launcher_starts_real_broker_health_then_shutdown(self):
        launched = []

        def launcher(command, **kwargs):
            process = subprocess.Popen(command, **kwargs)
            launched.append(process)
            return process

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_app_data = root / "local-app-data"
            user_home = root / "user-home"
            environment = {
                "LOCALAPPDATA": str(local_app_data),
                "USERPROFILE": str(user_home),
            }
            with patch.dict(os.environ, environment):
                store = BrokerStateStore(acl_applier=None)
                client = BrokerClient(
                    state_store=store,
                    launcher=launcher,
                    executable=sys.executable,
                    startup_lock_factory=lambda: StartupFileLock(
                        store.directory,
                        acl_applier=None,
                    ),
                    startup_timeout=10,
                    poll_interval=0.05,
                    request_timeout=10,
                )
                try:
                    health = client.request("health", {})
                    state = store.read()
                    shutdown = client.request("shutdown", {})
                    launched[0].wait(timeout=10)
                finally:
                    for process in launched:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=10)

        self.assertEqual(len(launched), 1)
        self.assertEqual(health["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(health["pid"], state.pid)
        self.assertEqual(health["edge_state"], "STARTING")
        self.assertEqual(health["browser_start_count"], 0)
        self.assertEqual(shutdown, {"stopping": True})
        self.assertEqual(launched[0].returncode, 0)
        self.assertFalse(store.state_file.exists())

    def test_broker_cli_help_works_as_direct_script_from_unrelated_directory(self):
        script = Path(__file__).resolve().parents[1] / "tools/gmail/gmail_edge_broker.py"
        with TemporaryDirectory() as tmp:
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                cwd=tmp,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("serve", completed.stdout)

    def test_launch_uses_absolute_script_injected_interpreter_and_explicit_state_cwd(self):
        sentinel = "PARAM_SENTINEL_MUST_NOT_REACH_COMMAND_LINE"
        launches = []

        def respond(request):
            if request.method == "health":
                return BrokerResponse.success(request.id, make_health_result())
            return BrokerResponse.success(request.id, {"messages": []})

        with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
            root = Path(tmp)
            state_directory = root / "state"
            unrelated_directory = root / "unrelated"
            unrelated_directory.mkdir()
            interpreter = root / "venv" / "Scripts" / "python.exe"
            store = BrokerStateStore(state_directory, acl_applier=None)

            def launcher(command, **kwargs):
                launches.append((command, kwargs))
                write_state(store, broker)
                return FakeProcess()

            previous_directory = Path.cwd()
            os.chdir(unrelated_directory)
            try:
                client = BrokerClient(
                    state_store=store,
                    process_exists=lambda _pid: True,
                    launcher=launcher,
                    executable=interpreter,
                    startup_lock_factory=lambda: StartupFileLock(
                        state_directory,
                        acl_applier=None,
                    ),
                )
                result = client.request("gmail_search", {"query": sentinel})
            finally:
                os.chdir(previous_directory)

        self.assertEqual(result, {"messages": []})
        self.assertEqual(len(launches), 1)
        command, kwargs = launches[0]
        self.assertEqual(command[0], str(interpreter.resolve()))
        self.assertTrue(Path(command[1]).is_absolute())
        self.assertEqual(Path(command[1]).name, "gmail_edge_broker.py")
        self.assertEqual(len(command), 2)
        self.assertNotIn(sentinel, repr(command))
        self.assertEqual(Path(kwargs["cwd"]), state_directory.resolve())
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        if os.name == "nt":
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
        else:
            self.assertNotIn("creationflags", kwargs)

    def test_four_racing_clients_launch_one_broker_and_all_complete(self):
        launch_count = 0
        launch_count_lock = threading.Lock()
        ready = threading.Barrier(4)

        def respond(request):
            if request.method == "health":
                return BrokerResponse.success(request.id, make_health_result())
            return BrokerResponse.success(request.id, request.params["query"])

        with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
            state_directory = Path(tmp)
            store = BrokerStateStore(state_directory, acl_applier=None)

            def launcher(_command, **_kwargs):
                nonlocal launch_count
                with launch_count_lock:
                    launch_count += 1
                time.sleep(0.05)
                write_state(store, broker)
                return FakeProcess()

            def run_client(number):
                client = BrokerClient(
                    state_store=store,
                    process_exists=lambda _pid: True,
                    launcher=launcher,
                    startup_lock_factory=lambda: StartupFileLock(
                        state_directory,
                        acl_applier=None,
                    ),
                    poll_interval=0.01,
                )
                ready.wait(timeout=2)
                return client.request("gmail_search", {"query": f"case-{number}"})

            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(run_client, range(4)))

        self.assertEqual(launch_count, 1)
        self.assertCountEqual(results, [f"case-{number}" for number in range(4)])
        self.assertEqual(
            {request.method for request in broker.requests},
            {"health", "gmail_search"},
        )

    def test_startup_polling_stops_at_fifteen_second_deadline(self):
        clock = FakeClock()
        launches = []

        with TemporaryDirectory() as tmp:
            state_directory = Path(tmp)
            store = BrokerStateStore(state_directory, acl_applier=None)

            def launcher(command, **kwargs):
                launches.append((command, kwargs))
                return FakeProcess()

            client = BrokerClient(
                state_store=store,
                process_exists=lambda _pid: False,
                launcher=launcher,
                sleep=clock.sleep,
                clock=clock,
                startup_timeout=STARTUP_TIMEOUT_SECONDS,
                poll_interval=1,
                startup_lock_factory=lambda: StartupFileLock(
                    state_directory,
                    acl_applier=None,
                ),
            )

            with self.assertRaises(BrokerStartTimeout):
                client.request("health", {})

        self.assertEqual(STARTUP_TIMEOUT_SECONDS, 15)
        self.assertEqual(len(launches), 1)
        self.assertEqual(clock.now, 15)
        self.assertEqual(clock.sleeps, [1] * 15)


class TransportSafetyTests(unittest.TestCase):
    def make_client(self, directory, *, clock=None):
        store = BrokerStateStore(directory, acl_applier=None)
        write_state(
            store,
            SimpleNamespace(host="127.0.0.1", port=43210),
        )
        return BrokerClient(
            state_store=store,
            process_exists=lambda _pid: True,
            clock=clock or time.monotonic,
        )

    @staticmethod
    def health_response(request):
        return BrokerResponse.success(request["id"], make_health_result())

    def test_one_deadline_covers_connect_send_and_receive_for_both_frames(self):
        clock = FakeClock()

        def advance_during_health_send(_request):
            clock.now = 100

        health_socket = ScriptedSocket(
            self.health_response,
            on_send=advance_during_health_send,
        )
        request_socket = ScriptedSocket(
            lambda request: BrokerResponse.success(request["id"], "ok")
        )
        factory = ScriptedSocketFactory(health_socket, request_socket)

        with TemporaryDirectory() as tmp, patch(
            "tools.gmail.gmail_broker_client.socket.create_connection",
            factory,
        ):
            client = self.make_client(Path(tmp), clock=clock)
            result = client.request("gmail_search", {"query": "case"})

        self.assertEqual(result, "ok")
        self.assertEqual(factory.calls[0], (("127.0.0.1", 43210), 370))
        self.assertEqual(factory.calls[1], (("127.0.0.1", 43210), 270))
        self.assertIn(270, health_socket.timeouts)

    def test_expired_deadline_maps_to_request_timeout_and_closes_socket(self):
        clock = FakeClock()

        def expire_during_send(_request):
            clock.now = CLIENT_TIMEOUT_SECONDS + 1

        connection = ScriptedSocket(
            self.health_response,
            on_send=expire_during_send,
        )
        factory = ScriptedSocketFactory(connection)

        with TemporaryDirectory() as tmp, patch(
            "tools.gmail.gmail_broker_client.socket.create_connection",
            factory,
        ):
            client = self.make_client(Path(tmp), clock=clock)
            with self.assertRaises(BrokerClientError) as raised:
                client.request("health", {})

        self.assertEqual(raised.exception.code, "REQUEST_TIMEOUT")
        self.assertTrue(connection.closed)
        self.assertEqual(connection.recv_calls, 0)

    def test_response_larger_than_eight_mib_is_rejected_and_socket_closes(self):
        health_socket = ScriptedSocket(self.health_response)
        oversized_socket = ScriptedSocket(
            lambda _request: b"x" * (MAX_FRAME_BYTES + 1)
        )
        factory = ScriptedSocketFactory(health_socket, oversized_socket)

        with TemporaryDirectory() as tmp, patch(
            "tools.gmail.gmail_broker_client.socket.create_connection",
            factory,
        ):
            client = self.make_client(Path(tmp))
            with self.assertRaises(BrokerClientError) as raised:
                client.request("gmail_read", {"message_id": "case"})

        self.assertEqual(raised.exception.code, "RESPONSE_TOO_LARGE")
        self.assertTrue(oversized_socket.closed)

    def test_malformed_or_noncanonical_response_is_protocol_mismatch(self):
        malformed_responses = (
            b"not-json\n",
            b'{"version":1,"id":"unused","ok":true}\n',
            b'{"version":1,"id":"unused","ok":true,"result":null,"extra":1}\n',
            b'{"version":1,"version":1,"id":"unused","ok":true,"result":null}\n',
            b'{"version":1,"id":"unused","ok":true,"result":NaN}\n',
            b"\xff\n",
        )
        for malformed in malformed_responses:
            with self.subTest(frame=malformed[:30]):
                health_socket = ScriptedSocket(self.health_response)
                malformed_socket = ScriptedSocket(lambda _request, raw=malformed: raw)
                factory = ScriptedSocketFactory(health_socket, malformed_socket)

                with TemporaryDirectory() as tmp, patch(
                    "tools.gmail.gmail_broker_client.socket.create_connection",
                    factory,
                ):
                    client = self.make_client(Path(tmp))
                    with self.assertRaises(BrokerProtocolMismatch):
                        client.request("gmail_search", {"query": "case"})

                self.assertTrue(malformed_socket.closed)

    def test_invalid_or_oversized_request_is_sanitized_without_connecting(self):
        sentinel = "SENSITIVE_PARAM_SENTINEL"
        health_socket = ScriptedSocket(self.health_response)
        factory = ScriptedSocketFactory(health_socket)

        with TemporaryDirectory() as tmp, patch(
            "tools.gmail.gmail_broker_client.socket.create_connection",
            factory,
        ):
            client = self.make_client(Path(tmp))
            with self.assertRaises(BrokerClientError) as raised:
                client.request(
                    "gmail_search",
                    {"query": sentinel + ("x" * MAX_FRAME_BYTES)},
                )

        self.assertEqual(raised.exception.code, "INVALID_REQUEST")
        self.assertNotIn(sentinel, repr(raised.exception))
        self.assertEqual(len(factory.calls), 1)
        self.assertTrue(health_socket.closed)


class DiscoveryRecoveryTests(unittest.TestCase):
    def test_stale_and_malformed_state_are_replaced_without_being_used(self):
        for initial_state in ("stale", "malformed"):
            with self.subTest(initial_state=initial_state):
                launches = []

                def respond(request):
                    if request.method == "health":
                        return BrokerResponse.success(request.id, make_health_result())
                    return BrokerResponse.success(request.id, "recovered")

                with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
                    directory = Path(tmp)
                    store = BrokerStateStore(directory, acl_applier=None)
                    if initial_state == "stale":
                        write_state(store, broker, pid=999_999)
                    else:
                        store.state_file.write_text("{not-json", encoding="utf-8")

                    def launcher(_command, **_kwargs):
                        launches.append(True)
                        write_state(store, broker)
                        return FakeProcess()

                    client = BrokerClient(
                        state_store=store,
                        process_exists=lambda pid: pid == os.getpid(),
                        launcher=launcher,
                        startup_lock_factory=lambda: StartupFileLock(
                            directory,
                            acl_applier=None,
                        ),
                    )
                    result = client.request("gmail_search", {"query": "case"})

                self.assertEqual(result, "recovered")
                self.assertEqual(len(launches), 1)

    def test_broker_process_exit_during_startup_is_unavailable(self):
        clock = FakeClock()
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            client = BrokerClient(
                state_store=BrokerStateStore(directory, acl_applier=None),
                process_exists=lambda _pid: False,
                launcher=lambda _command, **_kwargs: FakeProcess(return_code=7),
                sleep=clock.sleep,
                clock=clock,
                startup_lock_factory=lambda: StartupFileLock(
                    directory,
                    acl_applier=None,
                ),
            )

            with self.assertRaises(BrokerUnavailable) as raised:
                client.request("health", {})

        self.assertEqual(raised.exception.code, "BROKER_UNAVAILABLE")
        self.assertEqual(clock.sleeps, [])

    def test_repr_does_not_retain_token_params_or_result(self):
        token = "TOKEN_SENTINEL"
        param = "PARAM_SENTINEL"
        result_sentinel = "RESULT_SENTINEL"

        def respond(request):
            if request.method == "health":
                return BrokerResponse.success(request.id, make_health_result())
            return BrokerResponse.success(request.id, result_sentinel)

        with TemporaryDirectory() as tmp, FakeLoopbackBroker(respond) as broker:
            store = BrokerStateStore(Path(tmp), acl_applier=None)
            write_state(store, broker, token=token)
            client = BrokerClient(
                state_store=store,
                process_exists=lambda _pid: True,
            )
            self.assertEqual(client.request("gmail_search", {"query": param}), result_sentinel)
            rendered = repr(client)

        self.assertNotIn(token, rendered)
        self.assertNotIn(param, rendered)
        self.assertNotIn(result_sentinel, rendered)


if __name__ == "__main__":
    unittest.main()
