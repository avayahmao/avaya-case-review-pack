import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.gmail.gmail_broker_protocol import PROTOCOL_VERSION
from tools.gmail.gmail_broker_state import (
    AlreadyRunning,
    BrokerStateStore,
    LifetimeFileLock,
    SanitizedRotatingLogger,
)
from tools.gmail.gmail_edge_broker import (
    CLIENT_TIMEOUT_SECONDS,
    EXECUTION_TIMEOUT_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    QUEUE_WAIT_TIMEOUT_SECONDS,
    BrowserAdapterError,
    BrowserApplicationError,
    BrowserAuthRequired,
    GmailEdgeBroker,
)
from tools.gmail.gmail_edge_common import AuthState


SENTINEL = "SENTINEL_SECRET_7b91"


class NoopLockBackend:
    def acquire(self, _stream):
        return None

    def release(self, _stream):
        return None


class FakeClock:
    def __init__(self, value=0.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class FakeBrowserAdapter:
    """Stateful browser seam; assertions target broker behavior, not this fake."""

    def __init__(self, *, delay=0.0, events=None):
        self.delay = delay
        self.events = events
        self.start_count = 0
        self.close_count = 0
        self.execute_count = 0
        self.execute_counts = Counter()
        self.current_concurrency = 0
        self.max_concurrency = 0
        self.entered = asyncio.Event()
        self.execution_finished = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.login_state = AuthState.AUTHENTICATED
        self.slow_first_close = False

    async def start(self):
        self.start_count += 1

    async def close(self):
        self.close_count += 1
        if self.slow_first_close and self.close_count == 1:
            await asyncio.sleep(10)
        if self.events is not None:
            self.events.append(("browser_close", None))

    async def execute(self, method, params):
        mode = params.get("mode", "success")
        self.execute_count += 1
        self.execute_counts[mode] += 1
        attempt = self.execute_counts[mode]
        self.current_concurrency += 1
        self.max_concurrency = max(
            self.max_concurrency,
            self.current_concurrency,
        )
        self.entered.set()
        try:
            await self.release.wait()
            if self.delay:
                await asyncio.sleep(self.delay)
            if mode == "auth":
                raise BrowserAuthRequired(
                    AuthState.AUTH_REQUIRED_GOOGLE,
                    f"authentication required: {params.get('secret', '')}",
                )
            if mode == "app_error":
                raise BrowserApplicationError(
                    f"application rejected {params.get('secret', '')}"
                )
            if mode == "unexpected_error":
                raise RuntimeError(f"unexpected {params.get('secret', '')}")
            if mode == "browser_error":
                raise BrowserAdapterError(
                    f"browser crashed {params.get('secret', '')}"
                )
            if mode == "retry_once" and attempt == 1:
                raise BrowserAdapterError("browser crashed once")
            if mode == "timeout":
                await asyncio.Event().wait()
            return params.get("result", f"{method}:{params.get('value', '')}")
        finally:
            self.current_concurrency -= 1
            self.execution_finished.set()

    async def interactive_login(self):
        return self.login_state


class RecordingStateStore(BrokerStateStore):
    def __init__(self, directory, events):
        super().__init__(directory, acl_applier=None)
        self.events = events

    def cleanup(self, instance_id, *, owner_lock):
        self.events.append(("state_cleanup", owner_lock.is_acquired))
        return super().cleanup(instance_id, owner_lock=owner_lock)


class RejectingOwnerLock:
    def __init__(self, events):
        self.events = events
        self.is_acquired = False

    def acquire(self):
        self.events.append("lock")
        raise AlreadyRunning("owned")

    def release(self):
        raise AssertionError("an unacquired lock must not be released")


class NullLogger:
    def close(self):
        return None


class ImmediateWaitClosedServer:
    """Preserve the real listener but remove incidental connection draining."""

    def __init__(self, server):
        self.server = server

    @property
    def sockets(self):
        return self.server.sockets

    def close(self):
        self.server.close()

    async def wait_closed(self):
        return None


class GmailBrokerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temporary_directories = []
        self._brokers = []

    async def asyncTearDown(self):
        for broker in reversed(self._brokers):
            await broker.stop()
        for temporary_directory in self._temporary_directories:
            temporary_directory.cleanup()

    async def make_broker(self, adapter=None, *, store_factory=None, **overrides):
        temporary_directory = tempfile.TemporaryDirectory()
        self._temporary_directories.append(temporary_directory)
        directory = Path(temporary_directory.name)
        store = (
            BrokerStateStore(directory, acl_applier=None)
            if store_factory is None
            else store_factory(directory)
        )
        owner_lock = LifetimeFileLock(
            store.paths.broker_lock_file,
            backend=NoopLockBackend(),
            acl_applier=None,
        )
        logger = SanitizedRotatingLogger(
            store.paths.log_file,
            acl_applier=None,
        )
        broker = GmailEdgeBroker(
            adapter or FakeBrowserAdapter(),
            state_store=store,
            owner_lock=owner_lock,
            logger=logger,
            build_id="test-build",
            instance_id="test-instance",
            token="test-token",
            idle_check_interval=0.005,
            **overrides,
        )
        await broker.start()
        self._brokers.append(broker)
        return broker, store

    async def request(
        self,
        broker,
        request_id,
        method="gmail_search",
        params=None,
        *,
        token="test-token",
        client_timeout=1.0,
    ):
        payload = {
            "version": PROTOCOL_VERSION,
            "id": request_id,
            "token": token,
            "method": method,
            "params": {} if params is None else params,
        }
        frame = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        return await asyncio.wait_for(
            self.raw_request(broker, frame),
            timeout=client_timeout,
        )

    async def raw_request(self, broker, frame):
        host, port = broker.address
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(frame)
            await writer.drain()
            response = await reader.readline()
        finally:
            writer.close()
            await writer.wait_closed()
        return json.loads(response.decode("utf-8"))

    async def wait_for(self, predicate, *, timeout=1.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("condition was not reached before timeout")
            await asyncio.sleep(0.001)

    async def test_four_clients_receive_twenty_correlated_serialized_responses(self):
        fake = FakeBrowserAdapter(delay=0.002)
        broker, _store = await self.make_broker(fake)

        async def client(client_number):
            responses = []
            for sequence in range(5):
                request_id = f"client-{client_number}-{sequence}"
                response = await self.request(
                    broker,
                    request_id,
                    params={"value": request_id},
                )
                responses.append(response)
            return responses

        grouped = await asyncio.gather(*(client(index) for index in range(4)))
        responses = [response for group in grouped for response in group]

        self.assertEqual(len(responses), 20)
        self.assertTrue(all(response["ok"] for response in responses))
        self.assertEqual(
            {response["id"] for response in responses},
            {f"client-{client}-{sequence}" for client in range(4) for sequence in range(5)},
        )
        self.assertEqual(fake.start_count, 1)
        self.assertEqual(fake.max_concurrency, 1)

        health = await self.request(broker, "health-1", "health")
        self.assertTrue(health["ok"])
        diagnostics = health["result"]
        self.assertEqual(
            set(diagnostics),
            {
                "protocol_version",
                "pid",
                "edge_state",
                "queue_depth",
                "request_count",
                "browser_start_count",
                "browser_crash_count",
                "current_browser_concurrency",
                "max_browser_concurrency",
                "build_id",
                "instance_id",
                "uptime_seconds",
            },
        )
        self.assertEqual(diagnostics["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(diagnostics["pid"], os.getpid())
        self.assertEqual(diagnostics["edge_state"], "AUTHENTICATED")
        self.assertEqual(diagnostics["queue_depth"], 0)
        self.assertEqual(diagnostics["request_count"], 20)
        self.assertEqual(diagnostics["browser_start_count"], 1)
        self.assertEqual(diagnostics["browser_crash_count"], 0)
        self.assertEqual(diagnostics["current_browser_concurrency"], 0)
        self.assertEqual(diagnostics["max_browser_concurrency"], 1)
        self.assertEqual(diagnostics["build_id"], "test-build")
        self.assertEqual(diagnostics["instance_id"], "test-instance")
        self.assertGreaterEqual(diagnostics["uptime_seconds"], 0)

    async def test_invalid_token_and_malformed_frame_return_safe_protocol_errors(self):
        broker, _store = await self.make_broker()

        unauthorized = await self.request(
            broker,
            "bad-token-id",
            token="wrong-token",
        )
        malformed = await self.raw_request(broker, b"not-json\n")

        self.assertEqual(unauthorized["id"], "bad-token-id")
        self.assertFalse(unauthorized["ok"])
        self.assertEqual(unauthorized["error"]["code"], "INVALID_REQUEST")
        self.assertNotIn("wrong-token", json.dumps(unauthorized))
        self.assertEqual(malformed["id"], "invalid-request")
        self.assertFalse(malformed["ok"])
        self.assertEqual(malformed["error"]["code"], "INVALID_REQUEST")

    async def test_auth_and_application_errors_are_mapped_without_retry(self):
        fake = FakeBrowserAdapter()
        broker, _store = await self.make_broker(fake)

        auth = await self.request(
            broker,
            "auth-id",
            params={"mode": "auth"},
        )
        app = await self.request(
            broker,
            "app-id",
            params={"mode": "app_error"},
        )
        unexpected = await self.request(
            broker,
            "unexpected-id",
            params={"mode": "unexpected_error"},
        )

        self.assertEqual(auth["error"]["code"], "AUTH_REQUIRED")
        self.assertEqual(app["error"]["code"], "APP_ERROR")
        self.assertEqual(unexpected["error"]["code"], "APP_ERROR")
        self.assertEqual(fake.execute_counts["auth"], 1)
        self.assertEqual(fake.execute_counts["app_error"], 1)
        self.assertEqual(fake.execute_counts["unexpected_error"], 1)

    async def test_safe_read_retries_once_only_after_browser_error(self):
        fake = FakeBrowserAdapter()
        broker, _store = await self.make_broker(fake)

        response = await self.request(
            broker,
            "retry-id",
            method="gmail_read",
            params={"mode": "retry_once", "result": "recovered"},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"], "recovered")
        self.assertEqual(fake.execute_counts["retry_once"], 2)
        self.assertEqual(fake.start_count, 2)
        self.assertEqual(broker.diagnostics()["browser_crash_count"], 1)

    async def test_execution_timeout_cancellation_is_not_swallowed_by_recovery(self):
        fake = FakeBrowserAdapter()
        fake.slow_first_close = True
        broker, _store = await self.make_broker(
            fake,
            execution_timeout=0.02,
        )

        response = await self.request(
            broker,
            "cancel-recovery-id",
            method="gmail_read",
            params={"mode": "retry_once", "result": "too-late"},
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "REQUEST_TIMEOUT")
        self.assertEqual(fake.execute_counts["retry_once"], 1)

    async def test_send_is_never_retried_after_browser_error(self):
        fake = FakeBrowserAdapter()
        broker, _store = await self.make_broker(fake)

        response = await self.request(
            broker,
            "send-id",
            method="gmail_send",
            params={"mode": "browser_error"},
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "BROWSER_ERROR")
        self.assertEqual(fake.execute_counts["browser_error"], 1)

    async def test_health_reports_waiting_queue_depth_while_browser_is_busy(self):
        fake = FakeBrowserAdapter()
        fake.release.clear()
        broker, _store = await self.make_broker(fake)
        active = asyncio.create_task(self.request(broker, "active-id"))
        await fake.entered.wait()
        queued = asyncio.create_task(self.request(broker, "queued-id"))
        await self.wait_for(lambda: broker.queue_depth == 1)

        health = await self.request(broker, "health-id", "health")

        self.assertEqual(health["result"]["queue_depth"], 1)
        self.assertEqual(health["result"]["current_browser_concurrency"], 1)
        fake.release.set()
        active_response, queued_response = await asyncio.gather(active, queued)
        self.assertTrue(active_response["ok"])
        self.assertTrue(queued_response["ok"])

    async def test_queue_wait_and_browser_execution_have_separate_timeouts(self):
        fake = FakeBrowserAdapter()
        fake.release.clear()
        broker, _store = await self.make_broker(
            fake,
            queue_wait_timeout=0.02,
            execution_timeout=0.05,
        )
        active = asyncio.create_task(self.request(broker, "active-id"))
        await fake.entered.wait()

        queue_timeout = await self.request(broker, "queue-timeout-id")
        fake.release.set()
        await active
        execution_timeout = await self.request(
            broker,
            "execution-timeout-id",
            params={"mode": "timeout"},
        )

        self.assertEqual(queue_timeout["error"]["code"], "REQUEST_TIMEOUT")
        self.assertIn("queue", queue_timeout["error"]["message"].lower())
        self.assertEqual(execution_timeout["error"]["code"], "REQUEST_TIMEOUT")
        self.assertIn("execution", execution_timeout["error"]["message"].lower())

    async def test_representative_serialized_latency_stays_inside_client_deadline(self):
        self.assertEqual(QUEUE_WAIT_TIMEOUT_SECONDS, 300)
        self.assertEqual(EXECUTION_TIMEOUT_SECONDS, 60)
        self.assertEqual(CLIENT_TIMEOUT_SECONDS, 370)
        self.assertEqual(IDLE_TIMEOUT_SECONDS, 2 * 60 * 60)
        fake = FakeBrowserAdapter(delay=0.01)
        broker, _store = await self.make_broker(
            fake,
            queue_wait_timeout=0.5,
            execution_timeout=0.1,
        )

        started = time.monotonic()
        responses = await asyncio.gather(
            *(
                self.request(
                    broker,
                    f"latency-{index}",
                    params={"value": str(index)},
                    client_timeout=0.7,
                )
                for index in range(20)
            )
        )
        elapsed = time.monotonic() - started

        self.assertTrue(all(response["ok"] for response in responses))
        self.assertEqual(responses[-1]["id"], "latency-19")
        self.assertLess(elapsed, 0.7)
        self.assertEqual(fake.max_concurrency, 1)

    async def test_uptime_uses_injected_clock_when_it_starts_at_zero(self):
        clock = FakeClock(0)
        broker, _store = await self.make_broker(clock=clock)

        clock.advance(7)
        health = await self.request(broker, "uptime-health", "health")

        self.assertEqual(health["result"]["uptime_seconds"], 7)

    async def test_default_logger_is_opened_only_after_owner_lock_is_acquired(self):
        events = []
        temporary_directory = tempfile.TemporaryDirectory()
        self._temporary_directories.append(temporary_directory)
        store = BrokerStateStore(temporary_directory.name, acl_applier=None)
        owner_lock = RejectingOwnerLock(events)

        with patch(
            "tools.gmail.gmail_edge_broker.SanitizedRotatingLogger",
            side_effect=lambda *_args, **_kwargs: events.append("logger") or NullLogger(),
        ):
            broker = GmailEdgeBroker(
                FakeBrowserAdapter(),
                state_store=store,
                owner_lock=owner_lock,
            )
            with self.assertRaises(AlreadyRunning):
                await broker.start()

        self.assertEqual(events, ["lock"])

    async def test_sentinel_is_absent_from_sanitized_log_on_all_result_paths(self):
        fake = FakeBrowserAdapter()
        broker, store = await self.make_broker(
            fake,
            execution_timeout=0.02,
        )

        success = await self.request(
            broker,
            "secret-success",
            params={"result": SENTINEL},
        )
        error = await self.request(
            broker,
            "secret-error",
            params={"mode": "app_error", "secret": SENTINEL},
        )
        timeout = await self.request(
            broker,
            "secret-timeout",
            params={"mode": "timeout", "secret": SENTINEL},
        )

        self.assertEqual(success["result"], SENTINEL)
        self.assertEqual(error["error"]["code"], "APP_ERROR")
        self.assertEqual(timeout["error"]["code"], "REQUEST_TIMEOUT")
        logged = "".join(
            path.read_text(encoding="utf-8")
            for path in store.directory.glob("broker.log*")
        )
        self.assertNotIn(SENTINEL, logged)

    async def test_idle_shutdown_waits_for_active_work_then_closes_before_cleanup(self):
        events = []
        clock = FakeClock()
        fake = FakeBrowserAdapter(events=events)
        fake.release.clear()
        broker, store = await self.make_broker(
            fake,
            store_factory=lambda directory: RecordingStateStore(directory, events),
            clock=clock,
            idle_timeout=5,
        )
        active = asyncio.create_task(self.request(broker, "active-id"))
        await fake.entered.wait()

        clock.advance(10)
        await asyncio.sleep(0.03)

        self.assertTrue(broker.is_running)
        self.assertTrue(store.state_file.exists())
        self.assertEqual(fake.close_count, 0)

        fake.release.set()
        self.assertTrue((await active)["ok"])
        clock.advance(6)
        await asyncio.wait_for(broker.wait_stopped(), timeout=1.0)

        self.assertFalse(broker.is_running)
        self.assertFalse(store.state_file.exists())
        self.assertEqual(
            events,
            [("browser_close", None), ("state_cleanup", True)],
        )
        self.assertFalse(broker.owner_lock.is_acquired)

    async def test_explicit_shutdown_waits_for_active_browser_operation_before_close(self):
        fake = FakeBrowserAdapter()
        fake.release.clear()
        broker, _store = await self.make_broker(fake)
        active = asyncio.create_task(self.request(broker, "active-id"))
        await fake.entered.wait()
        real_server = broker._server
        broker._server = ImmediateWaitClosedServer(real_server)

        shutdown = await self.request(broker, "shutdown-id", "shutdown")
        self.assertTrue(shutdown["ok"])
        try:
            await asyncio.sleep(0.03)
            self.assertEqual(fake.close_count, 0)
            self.assertFalse(fake.execution_finished.is_set())
        finally:
            fake.release.set()

        active_response = await active
        await asyncio.wait_for(broker.wait_stopped(), timeout=1.0)
        await real_server.wait_closed()

        self.assertTrue(active_response["ok"])
        self.assertTrue(fake.execution_finished.is_set())
        self.assertEqual(fake.close_count, 1)


if __name__ == "__main__":
    unittest.main()
