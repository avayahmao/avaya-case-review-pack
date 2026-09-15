import asyncio
from collections import Counter
import contextlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import tools.gmail.gmail_edge_broker as gmail_edge_broker
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
    FRAME_READ_TIMEOUT_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    LOGIN_TIMEOUT_SECONDS,
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
        self.calls = []
        self.results = {}
        self.execute_counts = Counter()
        self.current_concurrency = 0
        self.max_concurrency = 0
        self.entered = asyncio.Event()
        self.execution_finished = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.login_state = AuthState.AUTHENTICATED
        self.login_delay = 0.0
        self.slow_first_close = False
        self.last_retry_count = 0
        self.last_retry_reason = "NONE"

    async def start(self):
        self.start_count += 1

    async def close(self):
        self.close_count += 1
        if self.slow_first_close and self.close_count == 1:
            await asyncio.sleep(10)
        if self.events is not None:
            self.events.append(("browser_close", None))

    async def execute(self, method, params):
        self.last_retry_count = 0
        self.last_retry_reason = "NONE"
        mode = params.get("mode", "success")
        self.calls.append((method, dict(params)))
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
            if mode == "adapter_timeout":
                timeout_type = getattr(
                    gmail_edge_broker,
                    "BrowserOperationTimeout",
                    BrowserAdapterError,
                )
                raise timeout_type("adapter deadline exhausted")
            if mode == "retry_once" and attempt == 1:
                raise BrowserAdapterError("browser crashed once")
            if mode == "mixed_retry" and attempt == 1:
                self.last_retry_count = 1
                self.last_retry_reason = "NAVIGATION_TIMEOUT"
                raise BrowserAdapterError("browser crashed after navigation retry")
            if mode == "timeout":
                await asyncio.Event().wait()
            if mode == "adapter_retry":
                self.last_retry_count = 2
                self.last_retry_reason = "NAVIGATION_TIMEOUT"
            return self.results.get(
                method,
                params.get("result", f"{method}:{params.get('value', '')}"),
            )
        finally:
            self.current_concurrency -= 1
            self.execution_finished.set()

    async def interactive_login(self):
        if self.login_delay:
            await asyncio.sleep(self.login_delay)
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


class FailingLogger(NullLogger):
    def __init__(self):
        self.fail = False

    def info(self, *_args, **_kwargs):
        if self.fail:
            raise OSError("log write failed")

    def warning(self, *_args, **_kwargs):
        if self.fail:
            raise OSError("log write failed")


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
        logger = overrides.pop("logger", None)
        if logger is None:
            logger = SanitizedRotatingLogger(
                store.paths.log_file,
                acl_applier=None,
            )
        token = overrides.pop("token", "test-token")
        broker = GmailEdgeBroker(
            adapter or FakeBrowserAdapter(),
            state_store=store,
            owner_lock=owner_lock,
            logger=logger,
            build_id="test-build",
            instance_id="test-instance",
            token=token,
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

    async def test_context_methods_use_framing_in_order_without_logging_payload(self):
        sentinels = {
            "record": "RECORD_ID_SENTINEL_7b91",
            "snapshot": "SNAPSHOT_SENTINEL_7b91",
            "page_token": "PAGE_TOKEN_SENTINEL_7b91",
            "thread": "THREAD_ID_SENTINEL_7b91",
            "message": "MESSAGE_ID_SENTINEL_7b91",
            "cursor": "CURSOR_SENTINEL_7b91",
            "body": "RESULT_BODY_SENTINEL_7b91",
            "token": "BROKER_TOKEN_SENTINEL_7b91",
        }
        list_params = {
            "query": sentinels["record"],
            "snapshot_before": sentinels["snapshot"],
            "page_token": sentinels["page_token"],
            "max_results": 1,
        }
        page_params = {
            "thread_id": sentinels["thread"],
            "snapshot_before": sentinels["snapshot"],
            "cursor": sentinels["cursor"],
            "message_id": sentinels["message"],
        }
        list_result = {
            "thread_id": sentinels["thread"],
            "next_page_token": sentinels["page_token"],
        }
        page_result = {
            "message_id": sentinels["message"],
            "body": sentinels["body"],
        }
        fake = FakeBrowserAdapter()
        fake.results = {
            "gmail_list_threads": list_result,
            "gmail_read_thread_page": page_result,
        }
        broker, store = await self.make_broker(fake, token=sentinels["token"])

        listed = await self.request(
            broker,
            "context-list",
            method="gmail_list_threads",
            params=list_params,
            token=sentinels["token"],
        )
        paged = await self.request(
            broker,
            "context-page",
            method="gmail_read_thread_page",
            params=page_params,
            token=sentinels["token"],
        )

        self.assertEqual(listed["result"], list_result)
        self.assertEqual(paged["result"], page_result)
        self.assertEqual(
            fake.calls,
            [
                ("gmail_list_threads", list_params),
                ("gmail_read_thread_page", page_params),
            ],
        )
        logged = "".join(
            path.read_text(encoding="utf-8")
            for path in store.directory.glob("broker.log*")
        )
        for name, sentinel in sentinels.items():
            with self.subTest(sentinel=name):
                self.assertNotIn(sentinel, logged)

    async def test_context_logs_aggregate_only_safe_page_metrics(self):
        fake = FakeBrowserAdapter()
        fake.results = {
            "gmail_list_threads": json.dumps(
                {
                    "thread_ids": ["thread-secret-a", "thread-secret-b"],
                    "next_page_token": "page-token-secret",
                    "complete": False,
                }
            ),
            "gmail_read_thread_page": json.dumps(
                {
                    "message_count": 5,
                    "messages_completed": 2,
                    "segments": [
                        {
                            "message_id": "message-secret-a",
                            "body_chunk": "body-secret-a",
                            "chunk_index": 0,
                            "chunk_count": 1,
                        },
                        {
                            "message_id": "message-secret-b",
                            "body_chunk": "body-secret-b",
                            "chunk_index": 0,
                            "chunk_count": 1,
                        },
                    ],
                    "next_cursor": "cursor-secret",
                    "manifest_sha256": "hash-secret",
                    "complete": False,
                }
            ),
        }
        broker, store = await self.make_broker(fake, session_sequence=918273)

        await self.request(
            broker,
            "INC7445969",
            method="gmail_list_threads",
            params={
                "query": "INC7445969",
                "snapshot_before": "snapshot-secret",
                "max_results": 100,
            },
        )
        await self.request(
            broker,
            "second-secret-request-id",
            method="gmail_read_thread_page",
            params={
                "thread_id": "thread-secret-a",
                "snapshot_before": "snapshot-secret",
                "cursor": "cursor-secret",
            },
        )

        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "request_finished"
        ]
        list_record, page_record = records
        self.assertEqual(
            {
                key: list_record[key]
                for key in (
                    "session_sequence",
                    "run_sequence",
                    "session_state",
                    "page_phase",
                    "requested_count",
                    "result_count",
                    "response_bytes",
                    "thread_count",
                    "retry_count",
                    "retry_reason",
                    "timeout_reason",
                )
            },
            {
                "session_sequence": 918273,
                "run_sequence": 1,
                "session_state": "COLD",
                "page_phase": "FIRST_PAGE",
                "requested_count": 100,
                "result_count": 2,
                "response_bytes": len(fake.results["gmail_list_threads"].encode("utf-8")),
                "thread_count": 2,
                "retry_count": 0,
                "retry_reason": "NONE",
                "timeout_reason": "NONE",
            },
        )
        self.assertEqual(
            {
                key: page_record[key]
                for key in (
                    "session_sequence",
                    "run_sequence",
                    "session_state",
                    "page_phase",
                    "result_count",
                    "response_bytes",
                    "segment_count",
                    "message_count",
                    "messages_completed",
                    "chunk_count",
                    "retry_count",
                    "retry_reason",
                    "timeout_reason",
                )
            },
            {
                "session_sequence": 918273,
                "run_sequence": 2,
                "session_state": "WARM",
                "page_phase": "CONTINUATION",
                "result_count": 2,
                "response_bytes": len(
                    fake.results["gmail_read_thread_page"].encode("utf-8")
                ),
                "segment_count": 2,
                "message_count": 5,
                "messages_completed": 2,
                "chunk_count": 2,
                "retry_count": 0,
                "retry_reason": "NONE",
                "timeout_reason": "NONE",
            },
        )
        self.assertGreaterEqual(list_record["service_ms"], 0)
        self.assertGreaterEqual(page_record["service_ms"], 0)
        logged = store.paths.log_file.read_text(encoding="utf-8")
        for secret in (
            "INC7445969",
            "second-secret-request-id",
            "thread-secret",
            "message-secret",
            "body-secret",
            "page-token-secret",
            "cursor-secret",
            "snapshot-secret",
            "hash-secret",
        ):
            self.assertNotIn(secret, logged)

    async def test_retry_and_timeout_reasons_are_safe_aggregates(self):
        fake = FakeBrowserAdapter()
        broker, store = await self.make_broker(
            fake,
            session_sequence=777,
            execution_timeout=0.02,
        )

        recovered = await self.request(
            broker,
            "retry-secret-id",
            method="gmail_read_thread_page",
            params={"mode": "retry_once", "result": "{}", "cursor": ""},
        )
        timed_out = await self.request(
            broker,
            "timeout-secret-id",
            method="gmail_read_thread_page",
            params={"mode": "timeout", "cursor": "continued-secret"},
        )

        self.assertTrue(recovered["ok"])
        self.assertEqual(timed_out["error"]["code"], "REQUEST_TIMEOUT")
        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "request_finished"
        ]
        recovered_record, timeout_record = records
        self.assertEqual(recovered_record["retry_count"], 1)
        self.assertEqual(recovered_record["retry_reason"], "BROWSER_ERROR")
        self.assertEqual(recovered_record["timeout_reason"], "NONE")
        self.assertEqual(timeout_record["retry_count"], 0)
        self.assertEqual(timeout_record["retry_reason"], "NONE")
        self.assertEqual(timeout_record["timeout_reason"], "EXECUTION")
        self.assertNotIn("continued-secret", json.dumps(records))

    async def test_telemetry_extraction_failure_never_changes_delivery(self):
        broker, _store = await self.make_broker(FakeBrowserAdapter())

        with patch.object(
            broker,
            "_safe_result_metrics",
            side_effect=RuntimeError("telemetry failed"),
        ):
            response = await self.request(
                broker,
                "delivery-survives-telemetry-failure",
                params={"result": "delivered"},
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"], "delivered")

    async def test_adapter_retry_metrics_are_included_in_request_aggregate(self):
        broker, store = await self.make_broker(
            FakeBrowserAdapter(),
            session_sequence=86420,
        )

        response = await self.request(
            broker,
            "adapter-retry-secret",
            method="gmail_list_threads",
            params={"mode": "adapter_retry", "result": "{}", "page_token": ""},
        )

        self.assertTrue(response["ok"])
        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "request_finished"
        ]
        self.assertEqual(records[0]["retry_count"], 2)
        self.assertEqual(records[0]["retry_reason"], "NAVIGATION_TIMEOUT")

    async def test_session_sequence_correlates_lifecycle_and_request_records(self):
        broker, store = await self.make_broker(
            FakeBrowserAdapter(),
            session_sequence=24680,
        )

        response = await self.request(broker, "opaque-request")
        await broker.stop()

        self.assertTrue(response["ok"])
        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [record["event"] for record in records],
            ["broker_started", "request_finished", "broker_stopped"],
        )
        self.assertEqual(
            [record["session_sequence"] for record in records],
            [24680, 24680, 24680],
        )

    async def test_queue_and_adapter_timeout_reasons_are_distinct(self):
        fake = FakeBrowserAdapter()
        fake.release.clear()
        broker, store = await self.make_broker(
            fake,
            session_sequence=13579,
            queue_wait_timeout=0.02,
            execution_timeout=2.0,
        )
        active = asyncio.create_task(
            self.request(broker, "active-secret", client_timeout=5.0)
        )
        await fake.entered.wait()

        queue_timeout = await self.request(
            broker,
            "queue-secret",
            client_timeout=5.0,
        )
        fake.release.set()
        await active
        adapter_timeout = await self.request(
            broker,
            "adapter-secret",
            params={"mode": "adapter_timeout"},
            client_timeout=5.0,
        )

        self.assertEqual(queue_timeout["error"]["code"], "REQUEST_TIMEOUT")
        self.assertEqual(adapter_timeout["error"]["code"], "REQUEST_TIMEOUT")
        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "request_finished"
        ]
        self.assertEqual(
            [record["timeout_reason"] for record in records],
            ["QUEUE_WAIT", "NONE", "ADAPTER"],
        )

    async def test_queued_request_records_warm_state_at_service_start(self):
        fake = FakeBrowserAdapter()
        fake.release.clear()
        broker, store = await self.make_broker(
            fake,
            session_sequence=97531,
            execution_timeout=2.0,
        )
        first = asyncio.create_task(
            self.request(broker, "first-secret", client_timeout=5.0)
        )
        await fake.entered.wait()
        second = asyncio.create_task(
            self.request(broker, "second-secret", client_timeout=5.0)
        )
        await self.wait_for(lambda: broker.queue_depth == 1)

        fake.release.set()
        await asyncio.gather(first, second)

        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "request_finished"
        ]
        self.assertEqual(
            [record["session_state"] for record in records],
            ["COLD", "WARM"],
        )

    async def test_request_queued_during_browser_start_records_warm_service(self):
        class StartupBlockingAdapter(FakeBrowserAdapter):
            def __init__(self):
                super().__init__()
                self.start_entered = asyncio.Event()
                self.start_release = asyncio.Event()

            async def start(self):
                self.start_count += 1
                self.start_entered.set()
                await self.start_release.wait()

        fake = StartupBlockingAdapter()
        broker, store = await self.make_broker(
            fake,
            session_sequence=11223,
            execution_timeout=2.0,
        )
        first = asyncio.create_task(
            self.request(broker, "first-during-start", client_timeout=5.0)
        )
        await fake.start_entered.wait()
        second = asyncio.create_task(
            self.request(broker, "second-during-start", client_timeout=5.0)
        )
        await self.wait_for(lambda: broker.queue_depth == 1)

        fake.start_release.set()
        await asyncio.gather(first, second)

        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "request_finished"
        ]
        self.assertEqual(
            [record["session_state"] for record in records],
            ["COLD", "WARM"],
        )

    async def test_distinct_adapter_and_broker_retry_reasons_log_multiple(self):
        broker, store = await self.make_broker(
            FakeBrowserAdapter(),
            session_sequence=44556,
        )

        response = await self.request(
            broker,
            "mixed-retry-secret",
            method="gmail_read_thread_page",
            params={"mode": "mixed_retry", "result": "{}"},
        )

        self.assertTrue(response["ok"])
        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "request_finished"
        ]
        self.assertEqual(records[0]["retry_count"], 2)
        self.assertEqual(records[0]["retry_reason"], "MULTIPLE")

    async def test_immediate_dispatch_paths_log_zero_service_time(self):
        broker, store = await self.make_broker(
            FakeBrowserAdapter(),
            session_sequence=77889,
        )

        health = await self.request(broker, "health-secret", method="health")
        broker._login_in_progress = True
        login_busy = await self.request(
            broker,
            "login-busy-secret",
            method="gmail_search",
        )
        broker._login_in_progress = False
        broker._stopping = True
        stopping = await self.request(
            broker,
            "stopping-secret",
            method="gmail_read",
        )
        broker._stopping = False
        shutdown = await self.request(broker, "shutdown-secret", method="shutdown")
        await broker.wait_stopped()

        self.assertTrue(health["ok"])
        self.assertEqual(login_busy["error"]["code"], "LOGIN_IN_PROGRESS")
        self.assertEqual(stopping["error"]["code"], "APP_ERROR")
        self.assertTrue(shutdown["ok"])
        records = [
            json.loads(line)
            for line in store.paths.log_file.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "request_finished"
        ]
        self.assertEqual(len(records), 4)
        self.assertEqual([record["service_ms"] for record in records], [0, 0, 0, 0])

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

    async def test_adapter_deadline_is_terminal_request_timeout_without_retry(self):
        fake = FakeBrowserAdapter()
        broker, _store = await self.make_broker(fake)

        response = await self.request(
            broker,
            "adapter-timeout-id",
            params={"mode": "adapter_timeout"},
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "REQUEST_TIMEOUT")
        self.assertEqual(fake.execute_counts["adapter_timeout"], 1)

    async def test_new_safe_read_methods_retry_once_after_browser_error(self):
        for method in (
            "gmail_list_threads",
            "gmail_read_thread_page",
            "bridge_capabilities",
        ):
            with self.subTest(method=method):
                fake = FakeBrowserAdapter()
                broker, _store = await self.make_broker(fake)

                response = await self.request(
                    broker,
                    f"retry-{method}",
                    method=method,
                    params={"mode": "retry_once", "result": method},
                )

                self.assertTrue(response["ok"])
                self.assertEqual(response["result"], method)
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
        self.assertEqual(FRAME_READ_TIMEOUT_SECONDS, 5)
        self.assertEqual(LOGIN_TIMEOUT_SECONDS, 330)
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

    async def test_silent_connected_client_cannot_wedge_stop(self):
        broker, _store = await self.make_broker(
            frame_read_timeout=0.02,
            connection_drain_timeout=0.2,
        )
        host, port = broker.address
        _reader, writer = await asyncio.open_connection(host, port)

        await asyncio.wait_for(broker.stop(), timeout=1.0)

        self.assertFalse(broker.is_running)
        writer.close()
        await writer.wait_closed()

    async def test_delayed_frame_after_stop_never_reaches_adapter(self):
        fake = FakeBrowserAdapter()
        broker, _store = await self.make_broker(
            fake,
            frame_read_timeout=0.2,
            connection_drain_timeout=0.2,
        )
        host, port = broker.address
        _reader, writer = await asyncio.open_connection(host, port)
        stop_task = asyncio.create_task(broker.stop())
        await self.wait_for(lambda: broker._stopping)
        payload = {
            "version": PROTOCOL_VERSION,
            "id": "late-id",
            "token": "test-token",
            "method": "gmail_search",
            "params": {},
        }
        with contextlib.suppress(ConnectionError, OSError):
            writer.write(
                json.dumps(payload, separators=(",", ":")).encode("utf-8")
                + b"\n"
            )
            await writer.drain()
        await asyncio.wait_for(stop_task, timeout=1.0)

        self.assertEqual(fake.execute_count, 0)
        writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await writer.wait_closed()

    async def test_auth_login_uses_dedicated_long_timeout(self):
        fake = FakeBrowserAdapter()
        fake.login_delay = 0.03
        broker, _store = await self.make_broker(
            fake,
            execution_timeout=0.01,
            login_timeout=0.1,
        )

        response = await self.request(
            broker,
            "login-id",
            method="auth_login",
        )

        self.assertTrue(response["ok"], response)

    async def test_logger_failure_does_not_override_successful_send(self):
        fake = FakeBrowserAdapter()
        logger = FailingLogger()
        broker, _store = await self.make_broker(fake, logger=logger)
        logger.fail = True

        response = await self.request(
            broker,
            "send-log-failure",
            method="gmail_send",
            params={"result": "sent"},
        )

        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"], "sent")


if __name__ == "__main__":
    unittest.main()
