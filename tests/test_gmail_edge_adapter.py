import asyncio
import logging
import os
import unittest
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

import tools.gmail.gmail_edge_broker as gmail_edge_broker
from tools.gmail.gmail_edge_broker import (
    _SAFE_READ_METHODS,
    BrowserAdapterError,
    BrowserApplicationError,
    BrowserAuthRequired,
    BrowserLoginError,
    BrowserOperationTimeout,
    GmailEdgeBroker,
    ManagedEdgeAdapter,
)
from tools.gmail.gmail_broker_protocol import (
    PROTOCOL_VERSION,
    BrokerErrorCode,
    BrokerRequest,
)
from tools.gmail.gmail_edge_common import AuthState


APP_URL = "https://script.google.com/a/macros/avaya.com/s/test/exec"
SUCCESS_URL = "https://script.googleusercontent.com/macros/echo"
CONTENT_SERVICE_URL = (
    "https://script.googleusercontent.com/macros/echo?user_content_key=transient"
)


class FakeResponse:
    def __init__(self, status=200):
        self.status = status


class FakePage:
    def __init__(
        self,
        *,
        final_url=SUCCESS_URL,
        body='{"status":"success"}',
        status=200,
        bodies=None,
        urls=None,
        goto_error=None,
        text_errors=None,
        close_after_waits=None,
        on_wait=None,
    ):
        self.url = "about:blank"
        self.final_url = final_url
        self.body = body
        self.status = status
        self.bodies = deque(bodies or [])
        self.urls = deque(urls or [])
        self.goto_error = goto_error
        self.text_errors = deque(text_errors or [])
        self.close_after_waits = close_after_waits
        self.on_wait = on_wait
        self.goto_calls = []
        self.load_state_calls = []
        self.events = []
        self.text_calls = 0
        self.wait_calls = 0
        self.close_calls = 0
        self.closed = False

    async def goto(self, url, **kwargs):
        self.events.append("goto")
        self.goto_calls.append((url, kwargs))
        if self.goto_error is not None:
            raise self.goto_error
        self.url = self.final_url
        return FakeResponse(self.status)

    async def wait_for_load_state(self, state, **kwargs):
        self.events.append(f"wait:{state}")
        self.load_state_calls.append((state, kwargs))

    async def text_content(self, selector, **kwargs):
        self.events.append("body")
        self.text_calls += 1
        if self.text_errors:
            error = self.text_errors.popleft()
            if error is not None:
                raise error
        if self.urls:
            self.url = self.urls.popleft()
        if self.bodies:
            return self.bodies.popleft()
        return self.body

    async def wait_for_timeout(self, milliseconds):
        self.events.append("poll")
        self.wait_calls += 1
        if self.on_wait is not None:
            self.on_wait(milliseconds)
        if (
            self.close_after_waits is not None
            and self.wait_calls >= self.close_after_waits
        ):
            self.closed = True
        await asyncio.sleep(0)

    def is_closed(self):
        return self.closed

    async def close(self):
        self.events.append("close")
        self.close_calls += 1
        self.closed = True


class FakeContext:
    def __init__(self, *pages, close_error=None):
        self._pages = deque(pages)
        self.created_pages = []
        self.close_calls = 0
        self.close_error = close_error

    @property
    def pages(self):
        return list(self.created_pages)

    async def new_page(self):
        if not self._pages:
            raise RuntimeError("no fake page configured")
        page = self._pages.popleft()
        if isinstance(page, BaseException):
            raise page
        self.created_pages.append(page)
        return page

    async def close(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeChromium:
    def __init__(self, *contexts):
        self._contexts = deque(contexts)
        self.launches = []

    async def launch_persistent_context(self, **kwargs):
        self.launches.append(kwargs)
        if not self._contexts:
            raise RuntimeError("no fake context configured")
        context = self._contexts.popleft()
        if isinstance(context, BaseException):
            raise context
        return context


class FakePlaywright:
    def __init__(self, *contexts):
        self.chromium = FakeChromium(*contexts)
        self.stop_calls = 0

    async def stop(self):
        self.stop_calls += 1


class FakePlaywrightStarter:
    def __init__(self, playwright):
        self.playwright = playwright
        self.start_calls = 0

    async def start(self):
        self.start_calls += 1
        return self.playwright


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance_ms(self, milliseconds):
        self.value += milliseconds / 1000


class ManagedEdgeAdapterExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.profile = self.root / "edge_broker_profile"

    def make_adapter(self, *contexts, **overrides):
        playwright = FakePlaywright(*contexts)
        starter = FakePlaywrightStarter(playwright)
        adapter = ManagedEdgeAdapter(
            profile_dir=self.profile,
            user_home=self.root,
            playwright_factory=lambda: starter,
            app_script_url=APP_URL,
            **overrides,
        )
        return adapter, starter, playwright

    async def test_starts_one_headless_managed_edge_context_and_closes_safely(self):
        context = FakeContext(close_error=RuntimeError("already closed"))
        adapter, starter, playwright = self.make_adapter(context)

        await adapter.start()
        await adapter.start()
        await adapter.close()
        await adapter.close()

        self.assertEqual(starter.start_calls, 1)
        self.assertEqual(len(playwright.chromium.launches), 1)
        launch = playwright.chromium.launches[0]
        self.assertEqual(launch["channel"], "msedge")
        self.assertEqual(Path(launch["user_data_dir"]), self.profile.resolve())
        self.assertIs(launch["headless"], True)
        self.assertEqual(context.close_calls, 1)
        self.assertEqual(playwright.stop_calls, 1)

    async def test_maps_all_gmail_methods_and_creates_one_page_per_execute(self):
        pages = [FakePage(body=f'{{"response":{index}}}') for index in range(6)]
        context = FakeContext(*pages)
        adapter, _starter, playwright = self.make_adapter(context)
        await adapter.start()

        results = [
            await adapter.execute("gmail_search", {"query": "subject:1-2 & owner"}),
            await adapter.execute("gmail_read", {"message_id": "message/123"}),
            await adapter.execute(
                "gmail_send",
                {"to": "user+tag@example.com", "subject": "A & B", "body": "line 1\nline 2"},
            ),
            await adapter.execute(
                "gmail_list_threads",
                {
                    "query": "subject:1-2 & owner",
                    "snapshot_before": "2026-08-05T00:00:00Z",
                    "page_token": "page-2",
                    "max_results": 25,
                },
            ),
            await adapter.execute(
                "gmail_read_thread_page",
                {
                    "thread_id": "thread/123",
                    "snapshot_before": "2026-08-05T00:00:00Z",
                    "cursor": "cursor-2",
                },
            ),
            await adapter.execute("bridge_capabilities", {}),
        ]

        self.assertEqual(
            results,
            [
                '{"response":0}',
                '{"response":1}',
                '{"response":2}',
                '{"response":3}',
                '{"response":4}',
                '{"response":5}',
            ],
        )
        self.assertEqual(len(context.created_pages), 6)
        self.assertEqual(len(playwright.chromium.launches), 1)
        expected = [
            ("search", {"q": ["subject:1-2 & owner"]}),
            ("read", {"id": ["message/123"]}),
            (
                "send",
                {
                    "to": ["user+tag@example.com"],
                    "subject": ["A & B"],
                    "body": ["line 1\nline 2"],
                },
            ),
            (
                "list_threads",
                {
                    "q": ["subject:1-2 & owner"],
                    "snapshot_before": ["2026-08-05T00:00:00Z"],
                    "page_token": ["page-2"],
                    "max_results": ["25"],
                },
            ),
            (
                "read_thread_page",
                {
                    "thread_id": ["thread/123"],
                    "snapshot_before": ["2026-08-05T00:00:00Z"],
                    "cursor": ["cursor-2"],
                },
            ),
            ("capabilities", {}),
        ]
        for page, (action, params) in zip(pages, expected):
            url = page.goto_calls[0][0]
            query = parse_qs(urlparse(url).query)
            self.assertEqual(len(query.pop("cache_bust")), 1)
            self.assertEqual(query.pop("action"), [action])
            self.assertEqual(query, params)
            self.assertEqual(page.load_state_calls, [])
            self.assertLess(page.events.index("goto"), page.events.index("body"))
            self.assertEqual(page.close_calls, 1)

        await adapter.close()

    async def test_execute_uses_unique_url_encoded_cache_busters_without_mutating_params(self):
        pages = [FakePage(), FakePage()]
        context = FakeContext(*pages)
        nonces = iter(("navigation 1/2", "navigation 3/4"))
        adapter, _starter, _playwright = self.make_adapter(
            context,
            nonce_factory=nonces.__next__,
        )
        params = {}
        await adapter.start()

        await adapter.execute("bridge_capabilities", params)
        await adapter.execute("bridge_capabilities", params)

        first_url, second_url = (page.goto_calls[0][0] for page in pages)
        self.assertNotEqual(first_url, second_url)
        self.assertIn("cache_bust=navigation+1%2F2", first_url)
        self.assertEqual(params, {})
        logical_queries = []
        for url in (first_url, second_url):
            query = parse_qs(urlparse(url).query)
            self.assertEqual(len(query.pop("cache_bust")), 1)
            logical_queries.append(query)
        self.assertEqual(
            logical_queries,
            [
                {"action": ["capabilities"]},
                {"action": ["capabilities"]},
            ],
        )
        self.assertEqual(
            adapter._build_method_url("bridge_capabilities", params),
            adapter._build_method_url("bridge_capabilities", params),
        )
        await adapter.close()

    async def test_rejects_invalid_generated_cache_buster_before_navigation(self):
        context = FakeContext(FakePage())
        adapter, _starter, _playwright = self.make_adapter(
            context,
            nonce_factory=lambda: "   ",
        )
        await adapter.start()

        with self.assertRaises(BrowserApplicationError) as raised:
            await adapter.execute("gmail_search", {"query": "case"})

        self.assertNotIn("cache_bust", str(raised.exception))
        self.assertEqual(context.created_pages, [])
        await adapter.close()

    async def test_retries_transient_content_delivery_until_third_response_is_json(self):
        pages = [
            FakePage(final_url=CONTENT_SERVICE_URL, body="<html>Page Not Found</html>"),
            FakePage(final_url=CONTENT_SERVICE_URL, body="<html>Page Not Found</html>"),
            FakePage(
                final_url=CONTENT_SERVICE_URL,
                body='{"status":"success","messages":[]}',
            ),
        ]
        context = FakeContext(*pages)
        nonces = iter(("attempt-1", "attempt-2", "attempt-3"))
        adapter, _starter, _playwright = self.make_adapter(
            context,
            nonce_factory=nonces.__next__,
        )
        await adapter.start()

        try:
            result = await adapter.execute("gmail_search", {"query": "case"})
        except BrowserApplicationError:
            result = None

        self.assertEqual(result, '{"status":"success","messages":[]}')
        self.assertEqual(context.created_pages, pages)
        self.assertTrue(all(page.load_state_calls == [] for page in pages))
        urls = [page.goto_calls[0][0] for page in pages]
        self.assertEqual(len(set(urls)), 3)
        self.assertEqual(
            [parse_qs(urlparse(url).query)["cache_bust"] for url in urls],
            [["attempt-1"], ["attempt-2"], ["attempt-3"]],
        )
        self.assertTrue(all(page.close_calls == 1 for page in pages))
        await adapter.close()

    async def test_retries_404_content_delivery_until_200_json_response(self):
        pages = [
            FakePage(
                final_url=CONTENT_SERVICE_URL,
                status=404,
                body="<html>Page Not Found</html>",
            ),
            FakePage(
                final_url=CONTENT_SERVICE_URL,
                status=200,
                body='{"status":"success","messages":[]}',
            ),
        ]
        context = FakeContext(*pages)
        adapter, _starter, _playwright = self.make_adapter(
            context,
            nonce_factory=iter(("attempt-1", "attempt-2")).__next__,
        )
        await adapter.start()

        try:
            result = await adapter.execute("gmail_search", {"query": "case"})
        except BrowserApplicationError:
            result = None

        self.assertEqual(result, '{"status":"success","messages":[]}')
        self.assertEqual(len(context.created_pages), 2)
        urls = [page.goto_calls[0][0] for page in pages]
        self.assertEqual(len(set(urls)), 2)
        self.assertEqual(
            [parse_qs(urlparse(url).query)["cache_bust"] for url in urls],
            [["attempt-1"], ["attempt-2"]],
        )
        await adapter.close()

    async def test_404_content_delivery_exhaustion_stops_after_three_attempts(self):
        pages = [
            FakePage(
                final_url=CONTENT_SERVICE_URL,
                status=404,
                body="<html>Page Not Found</html>",
            )
            for _ in range(4)
        ]
        context = FakeContext(*pages)
        adapter, _starter, _playwright = self.make_adapter(context)
        await adapter.start()

        with self.assertRaises(BrowserApplicationError) as raised:
            await adapter.execute("gmail_search", {"query": "case"})

        self.assertEqual(str(raised.exception), "Apps Script content delivery failed")
        self.assertEqual(len(context.created_pages), 3)
        self.assertEqual(pages[3].goto_calls, [])
        await adapter.close()

    async def test_transient_content_delivery_exhaustion_stops_after_three_attempts(self):
        pages = [
            FakePage(final_url=CONTENT_SERVICE_URL, body="<html>Page Not Found</html>")
            for _ in range(4)
        ]
        context = FakeContext(*pages)
        adapter, _starter, _playwright = self.make_adapter(
            context,
            nonce_factory=iter(("attempt-1", "attempt-2", "attempt-3", "attempt-4")).__next__,
        )
        await adapter.start()

        with self.assertRaises(BrowserApplicationError) as raised:
            await adapter.execute("gmail_search", {"query": "case"})

        self.assertEqual(str(raised.exception), "Apps Script content delivery failed")
        self.assertEqual(len(context.created_pages), 3)
        self.assertEqual(pages[3].goto_calls, [])
        self.assertTrue(all(page.close_calls == 1 for page in pages[:3]))
        await adapter.close()

    async def test_gmail_send_does_not_retry_transient_content_delivery_failure(self):
        pages = [
            FakePage(final_url=CONTENT_SERVICE_URL, body="<html>Page Not Found</html>")
            for _ in range(3)
        ]
        context = FakeContext(*pages)
        adapter, _starter, _playwright = self.make_adapter(
            context,
            nonce_factory=iter(("attempt-1", "attempt-2", "attempt-3")).__next__,
        )
        await adapter.start()

        with self.assertRaises(BrowserApplicationError) as raised:
            await adapter.execute(
                "gmail_send",
                {"to": "user@example.com", "subject": "subject", "body": "body"},
            )

        self.assertEqual(str(raised.exception), "Apps Script content delivery failed")
        self.assertEqual(len(context.created_pages), 1)
        self.assertEqual(pages[1].goto_calls, [])
        self.assertEqual(pages[2].goto_calls, [])
        await adapter.close()

    async def test_does_not_retry_non_200_content_service_response(self):
        pages = [
            FakePage(
                final_url=CONTENT_SERVICE_URL,
                status=503,
                body="<html>Service Unavailable</html>",
            )
            for _ in range(3)
        ]
        context = FakeContext(*pages)
        adapter, _starter, _playwright = self.make_adapter(context)
        await adapter.start()

        with self.assertRaises(BrowserApplicationError):
            await adapter.execute("gmail_search", {"query": "case"})

        self.assertEqual(len(context.created_pages), 1)
        self.assertEqual(pages[1].goto_calls, [])
        self.assertEqual(pages[2].goto_calls, [])
        await adapter.close()

    async def test_execute_remains_compatible_without_asyncio_timeout(self):
        page = FakePage(body='{"status":"success"}')
        adapter, _starter, _playwright = self.make_adapter(FakeContext(page))
        await adapter.start()

        with patch.object(asyncio, "timeout", None, create=True):
            try:
                result = await adapter.execute("gmail_search", {"query": "case"})
            except TypeError:
                result = None

        self.assertEqual(result, '{"status":"success"}')
        await adapter.close()

    async def test_internal_deadline_uses_distinct_terminal_timeout_error(self):
        entered = asyncio.Event()

        class BlockingPage(FakePage):
            async def text_content(self, selector, **kwargs):
                entered.set()
                await asyncio.Event().wait()

        page = BlockingPage(final_url=CONTENT_SERVICE_URL)
        adapter, _starter, _playwright = self.make_adapter(FakeContext(page))
        timeout_type = getattr(
            gmail_edge_broker,
            "BrowserOperationTimeout",
            BrowserAdapterError,
        )
        await adapter.start()

        with patch.object(gmail_edge_broker, "_ADAPTER_EXECUTION_DEADLINE_SECONDS", 0.01):
            with self.assertRaises(timeout_type) as raised:
                await adapter.execute("gmail_search", {"query": "case"})

        self.assertTrue(entered.is_set())
        self.assertIsNot(timeout_type, BrowserAdapterError)
        self.assertNotIn("case", str(raised.exception))
        await adapter.close()

    async def test_internal_deadline_bounds_page_close_cleanup(self):
        class BlockingPage(FakePage):
            async def text_content(self, selector, **kwargs):
                await asyncio.Event().wait()

            async def close(self):
                self.close_calls += 1
                await asyncio.sleep(0.2)

        page = BlockingPage(final_url=CONTENT_SERVICE_URL)
        adapter, _starter, _playwright = self.make_adapter(FakeContext(page))
        timeout_type = getattr(
            gmail_edge_broker,
            "BrowserOperationTimeout",
            BrowserAdapterError,
        )
        await adapter.start()
        started = asyncio.get_running_loop().time()

        with patch.object(gmail_edge_broker, "_ADAPTER_EXECUTION_DEADLINE_SECONDS", 0.01), patch.object(
            gmail_edge_broker,
            "_PAGE_CLOSE_TIMEOUT_SECONDS",
            0.01,
        ):
            with self.assertRaises(timeout_type):
                await adapter.execute("gmail_search", {"query": "case"})

        self.assertLess(asyncio.get_running_loop().time() - started, 0.1)
        self.assertEqual(page.close_calls, 1)
        await adapter.close()

    async def test_navigation_timeout_retries_within_total_adapter_budget(self):
        class ScaledNavigationTimeoutPage(FakePage):
            async def goto(self, url, **kwargs):
                self.events.append("goto")
                self.goto_calls.append((url, kwargs))
                if kwargs["timeout"] * 3 + 15_000 >= 54_000:
                    await asyncio.Event().wait()
                raise PlaywrightTimeoutError("navigation timed out")

            async def close(self):
                await super().close()

        first = ScaledNavigationTimeoutPage()
        second = FakePage(body='{"status":"success"}')
        adapter, _starter, _playwright = self.make_adapter(
            FakeContext(first, second),
            nonce_factory=iter(("attempt-1", "attempt-2")).__next__,
        )
        await adapter.start()

        with patch.object(
            gmail_edge_broker,
            "_ADAPTER_EXECUTION_DEADLINE_SECONDS",
            0.5,
        ):
            result = await adapter.execute("gmail_search", {"query": "case"})

        self.assertEqual(result, '{"status":"success"}')
        self.assertEqual(len(first.goto_calls), 1)
        self.assertEqual(len(second.goto_calls), 1)
        self.assertNotEqual(first.goto_calls[0][0], second.goto_calls[0][0])
        self.assertEqual(first.close_calls, 1)
        self.assertEqual(second.close_calls, 1)
        await adapter.close()

    async def test_three_navigation_timeouts_exhaust_without_fourth_attempt(self):
        class ScaledNavigationTimeoutPage(FakePage):
            async def goto(self, url, **kwargs):
                self.events.append("goto")
                self.goto_calls.append((url, kwargs))
                if kwargs["timeout"] * 3 + 15_000 >= 54_000:
                    await asyncio.Event().wait()
                raise PlaywrightTimeoutError("navigation timed out")

            async def close(self):
                await super().close()

        pages = [ScaledNavigationTimeoutPage() for _ in range(4)]
        adapter, _starter, _playwright = self.make_adapter(FakeContext(*pages))
        await adapter.start()

        with patch.object(
            gmail_edge_broker,
            "_ADAPTER_EXECUTION_DEADLINE_SECONDS",
            0.5,
        ):
            with self.assertRaises(BrowserOperationTimeout):
                await adapter.execute("gmail_search", {"query": "case"})

        self.assertTrue(all(len(page.goto_calls) == 1 for page in pages[:3]))
        self.assertEqual(pages[3].goto_calls, [])
        self.assertTrue(all(page.close_calls == 1 for page in pages[:3]))
        await adapter.close()

    async def test_timed_out_navigation_is_drained_before_page_cleanup(self):
        loop = asyncio.get_running_loop()
        loop_errors = []
        previous_handler = loop.get_exception_handler()

        class ShieldedNavigationPage(FakePage):
            def __init__(self):
                super().__init__()
                self.navigation_cancelled = False

            async def goto(self, url, **kwargs):
                self.events.append("goto")
                self.goto_calls.append((url, kwargs))

                async def delayed_timeout():
                    delay = 0.005 if kwargs["timeout"] <= 10_000 else 0.6
                    await asyncio.sleep(delay)
                    raise PlaywrightTimeoutError("navigation timed out")

                navigation = asyncio.create_task(delayed_timeout())
                try:
                    return await asyncio.shield(navigation)
                except asyncio.CancelledError:
                    self.navigation_cancelled = True
                    raise

            async def close(self):
                self.events.append("close-start")
                await asyncio.sleep(0.002)
                await super().close()

        first = ShieldedNavigationPage()
        second = FakePage(body='{"status":"success"}')
        adapter, _starter, _playwright = self.make_adapter(
            FakeContext(first, second)
        )
        await adapter.start()
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        try:
            with patch.object(
                gmail_edge_broker,
                "_ADAPTER_EXECUTION_DEADLINE_SECONDS",
                0.5,
            ):
                result = await adapter.execute("gmail_search", {"query": "case"})
            await asyncio.sleep(0.2)
        finally:
            loop.set_exception_handler(previous_handler)

        self.assertEqual(result, '{"status":"success"}')
        self.assertFalse(first.navigation_cancelled)
        self.assertEqual(first.close_calls, 1)
        self.assertEqual(loop_errors, [])
        await adapter.close()

    async def test_gmail_send_navigation_timeout_is_not_retried(self):
        page = FakePage(goto_error=PlaywrightTimeoutError("navigation timed out"))
        unused = FakePage(body='{"status":"success"}')
        adapter, _starter, _playwright = self.make_adapter(
            FakeContext(page, unused)
        )
        await adapter.start()

        with self.assertRaises(BrowserOperationTimeout):
            await adapter.execute(
                "gmail_send",
                {"to": "user@example.com", "subject": "subject", "body": "body"},
            )

        self.assertEqual(len(page.goto_calls), 1)
        self.assertEqual(unused.goto_calls, [])
        await adapter.close()

    async def test_does_not_retry_json_errors_or_non_content_html(self):
        cases = (
            (
                CONTENT_SERVICE_URL,
                '{"status":"error","message":"semantic failure"}',
            ),
            ("https://script.google.com/macros/s/bridge/exec", "<html>Page Not Found</html>"),
            ("https://example.invalid/error", "<html>Page Not Found</html>"),
        )
        for final_url, body in cases:
            with self.subTest(final_url=final_url):
                page = FakePage(final_url=final_url, body=body)
                adapter, _starter, _playwright = self.make_adapter(FakeContext(page))
                await adapter.start()

                with self.assertRaises(BrowserApplicationError):
                    await adapter.execute("gmail_search", {"query": "case"})

                self.assertEqual(page.close_calls, 1)
                await adapter.close()

    def test_default_nonce_factory_generates_distinct_navigation_urls(self):
        adapter, _starter, _playwright = self.make_adapter(FakeContext())
        logical_url = adapter._build_method_url("bridge_capabilities", {})

        first = adapter._navigation_url(logical_url)
        second = adapter._navigation_url(logical_url)

        self.assertNotEqual(first, second)
        self.assertEqual(
            parse_qs(urlparse(first).query).keys(),
            parse_qs(urlparse(second).query).keys(),
        )

    def test_bridge_capabilities_maps_to_parameter_free_cloud_action(self):
        context = FakeContext()
        adapter, _starter, _playwright = self.make_adapter(context)

        url = adapter._build_method_url("bridge_capabilities", {})

        self.assertEqual({"action": ["capabilities"]}, parse_qs(urlparse(url).query))
        with self.assertRaisesRegex(BrowserApplicationError, "parameters"):
            adapter._build_method_url("bridge_capabilities", {"q": "INC1"})

    async def test_omits_empty_optional_thread_context_parameters(self):
        pages = [FakePage(), FakePage()]
        adapter, _starter, _playwright = self.make_adapter(FakeContext(*pages))
        await adapter.start()

        await adapter.execute(
            "gmail_list_threads",
            {"query": "case", "max_results": 1},
        )
        await adapter.execute(
            "gmail_read_thread_page",
            {"thread_id": "thread-1", "snapshot_before": "snapshot", "cursor": ""},
        )

        first_query = parse_qs(urlparse(pages[0].goto_calls[0][0]).query)
        self.assertEqual(len(first_query.pop("cache_bust")), 1)
        self.assertEqual(
            first_query,
            {"action": ["list_threads"], "q": ["case"], "max_results": ["1"]},
        )
        second_query = parse_qs(urlparse(pages[1].goto_calls[0][0]).query)
        self.assertEqual(len(second_query.pop("cache_bust")), 1)
        self.assertEqual(
            second_query,
            {
                "action": ["read_thread_page"],
                "thread_id": ["thread-1"],
                "snapshot_before": ["snapshot"],
            },
        )
        await adapter.close()

    async def test_preserves_empty_legacy_method_parameters(self):
        pages = [FakePage(), FakePage(), FakePage()]
        adapter, _starter, _playwright = self.make_adapter(FakeContext(*pages))
        await adapter.start()

        await adapter.execute("gmail_search", {"query": ""})
        await adapter.execute("gmail_read", {"message_id": ""})
        await adapter.execute("gmail_send", {"to": "", "subject": "", "body": ""})

        first_query = parse_qs(
            urlparse(pages[0].goto_calls[0][0]).query, keep_blank_values=True
        )
        self.assertEqual(len(first_query.pop("cache_bust")), 1)
        self.assertEqual(
            first_query,
            {"action": ["search"], "q": [""]},
        )
        second_query = parse_qs(
            urlparse(pages[1].goto_calls[0][0]).query, keep_blank_values=True
        )
        self.assertEqual(len(second_query.pop("cache_bust")), 1)
        self.assertEqual(
            second_query,
            {"action": ["read"], "id": [""]},
        )
        third_query = parse_qs(
            urlparse(pages[2].goto_calls[0][0]).query, keep_blank_values=True
        )
        self.assertEqual(len(third_query.pop("cache_bust")), 1)
        self.assertEqual(
            third_query,
            {"action": ["send"], "to": [""], "subject": [""], "body": [""]},
        )
        await adapter.close()

    async def test_classifies_microsoft_redirect_before_reading_response_body(self):
        sentinel = "BODY_MUST_NOT_BE_READ_OR_LOGGED"
        page = FakePage(
            final_url="https://tenant.access.mcas.ms/aad_login",
            body=sentinel,
        )
        adapter, _starter, _playwright = self.make_adapter(FakeContext(page))
        await adapter.start()

        with patch.object(logging.Logger, "_log") as log_call:
            with self.assertRaises(BrowserAuthRequired) as raised:
                await adapter.execute("gmail_search", {"query": "case"})

        self.assertIs(raised.exception.state, AuthState.AUTH_REQUIRED_MICROSOFT)
        self.assertEqual(page.text_calls, 0)
        self.assertEqual(page.load_state_calls, [])
        self.assertEqual(page.close_calls, 1)
        self.assertNotIn(sentinel, repr(log_call.call_args_list))
        await adapter.close()

    async def test_returns_body_without_logging_it(self):
        sentinel = "PRIVATE_APPS_SCRIPT_RESPONSE_BODY"
        page = FakePage(body='{"payload":"' + sentinel + '"}')
        adapter, _starter, _playwright = self.make_adapter(FakeContext(page))
        await adapter.start()

        with patch.object(logging.Logger, "_log") as log_call:
            result = await adapter.execute("gmail_search", {"query": "case"})

        self.assertEqual(result, '{"payload":"' + sentinel + '"}')
        self.assertNotIn(sentinel, repr(log_call.call_args_list))
        await adapter.close()

    async def test_maps_application_and_browser_failures_to_adapter_errors(self):
        app_page = FakePage(
            final_url=APP_URL,
            status=503,
            body="PRIVATE_ERROR_BODY",
        )
        browser_page = FakePage(goto_error=RuntimeError("target crashed"))
        context = FakeContext(app_page, browser_page)
        adapter, _starter, _playwright = self.make_adapter(context)
        await adapter.start()

        with self.assertRaises(BrowserApplicationError) as app_error:
            await adapter.execute("gmail_read", {"message_id": "one"})
        with self.assertRaises(BrowserAdapterError):
            await adapter.execute("gmail_read", {"message_id": "two"})

        self.assertNotIn("PRIVATE_ERROR_BODY", str(app_error.exception))
        self.assertEqual(app_page.close_calls, 1)
        self.assertEqual(browser_page.close_calls, 1)
        await adapter.close()

    async def test_rejects_invalid_method_parameters_before_opening_page(self):
        context = FakeContext(FakePage())
        adapter, _starter, _playwright = self.make_adapter(context)
        await adapter.start()

        for method, params in (
            ("gmail_search", {}),
            ("gmail_read", {"message_id": 123}),
            ("gmail_send", {"to": "a", "subject": "b"}),
            ("gmail_list_threads", {"query": "case", "max_results": True}),
            ("gmail_list_threads", {"query": "case"}),
            ("gmail_list_threads", {"query": "case", "max_results": 0}),
            ("gmail_list_threads", {"query": "case", "max_results": 101}),
            ("gmail_list_threads", {"max_results": 1}),
            ("gmail_list_threads", {"query": "", "max_results": 1}),
            ("gmail_list_threads", {"query": "case", "snapshot_before": 1, "max_results": 1}),
            ("gmail_list_threads", {"query": "case", "page_token": 1, "max_results": 1}),
            ("gmail_read_thread_page", {"snapshot_before": "snapshot"}),
            ("gmail_read_thread_page", {"thread_id": "thread"}),
            ("gmail_read_thread_page", {"thread_id": "", "snapshot_before": "snapshot"}),
            ("gmail_read_thread_page", {"thread_id": "thread", "snapshot_before": ""}),
            ("gmail_read_thread_page", {"thread_id": "thread", "snapshot_before": "snapshot", "cursor": 1}),
            ("bridge_capabilities", {"q": "INC1"}),
            ("health", {}),
        ):
            with self.subTest(method=method, params=params):
                with self.assertRaises(BrowserApplicationError):
                    await adapter.execute(method, params)

        self.assertEqual(context.created_pages, [])
        await adapter.close()

    def test_marks_thread_context_operations_safe_to_retry(self):
        self.assertEqual(
            _SAFE_READ_METHODS,
            frozenset(
                {
                    "gmail_search",
                    "gmail_read",
                    "gmail_list_threads",
                    "gmail_read_thread_page",
                    "bridge_capabilities",
                }
            ),
        )

    def test_default_profile_is_dedicated_and_common_guard_is_applied(self):
        home = self.root / "home"
        with patch.dict(os.environ, {"USERPROFILE": str(home)}):
            adapter = ManagedEdgeAdapter(playwright_factory=lambda: None)
            self.assertEqual(
                adapter.profile_dir,
                (home / ".gemini/tools/gmail/edge_broker_profile").resolve(),
            )
            with self.assertRaises(ValueError):
                ManagedEdgeAdapter(
                    profile_dir=home / ".gemini/tools/gmail/chrome_profile",
                    playwright_factory=lambda: None,
                )


class ManagedEdgeAdapterLoginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.profile = self.root / "edge_broker_profile"

    def make_adapter(self, *contexts, timeout=5.0, clock=None, **overrides):
        playwright = FakePlaywright(*contexts)
        starter = FakePlaywrightStarter(playwright)
        adapter = ManagedEdgeAdapter(
            profile_dir=self.profile,
            user_home=self.root,
            playwright_factory=lambda: starter,
            app_script_url=APP_URL,
            login_timeout_seconds=timeout,
            login_poll_interval_ms=100,
            clock=clock or FakeClock(),
            **overrides,
        )
        return adapter, playwright

    async def test_login_switches_headless_to_headful_and_always_restores_headless(self):
        headless_before = FakeContext()
        login_page = FakePage(
            final_url="https://login.microsoftonline.com/tenant/saml2",
            bodies=["Sign in", '{"status":"success"}'],
            urls=[
                "https://login.microsoftonline.com/tenant/saml2",
                SUCCESS_URL,
            ],
        )
        headful = FakeContext(login_page)
        headless_after = FakeContext()
        adapter, playwright = self.make_adapter(
            headless_before,
            headful,
            headless_after,
        )
        await adapter.start()

        state = await adapter.interactive_login()

        self.assertIs(state, AuthState.AUTHENTICATED)
        self.assertEqual(
            [launch["headless"] for launch in playwright.chromium.launches],
            [True, False, True],
        )
        self.assertTrue(
            all(
                Path(launch["user_data_dir"]) == self.profile.resolve()
                for launch in playwright.chromium.launches
            )
        )
        self.assertEqual(headless_before.close_calls, 1)
        self.assertEqual(headful.close_calls, 1)
        await adapter.close()
        self.assertEqual(headless_after.close_calls, 1)

    async def test_login_verification_navigation_uses_url_encoded_cache_buster(self):
        login_page = FakePage(body='{"status":"success"}')
        adapter, _playwright = self.make_adapter(
            FakeContext(),
            FakeContext(login_page),
            FakeContext(),
            nonce_factory=lambda: "login verification/1",
        )
        await adapter.start()

        state = await adapter.interactive_login()

        self.assertIs(state, AuthState.AUTHENTICATED)
        url = login_page.goto_calls[0][0]
        self.assertIn("cache_bust=login+verification%2F1", url)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query.pop("cache_bust"), ["login verification/1"])
        self.assertEqual(
            query,
            {
                "action": ["search"],
                "q": ["subject:__avaya_gmail_edge_broker_verify__"],
            },
        )
        await adapter.close()

    async def test_two_login_verifications_use_distinct_navigation_urls(self):
        first_login = FakePage(body='{"status":"success"}')
        second_login = FakePage(body='{"status":"success"}')
        adapter, _playwright = self.make_adapter(
            FakeContext(),
            FakeContext(first_login),
            FakeContext(),
            FakeContext(second_login),
            FakeContext(),
        )
        await adapter.start()

        self.assertIs(await adapter.interactive_login(), AuthState.AUTHENTICATED)
        self.assertIs(await adapter.interactive_login(), AuthState.AUTHENTICATED)

        first_url = first_login.goto_calls[0][0]
        second_url = second_login.goto_calls[0][0]
        self.assertNotEqual(first_url, second_url)
        first_query = parse_qs(urlparse(first_url).query)
        second_query = parse_qs(urlparse(second_url).query)
        first_query.pop("cache_bust")
        second_query.pop("cache_bust")
        self.assertEqual(first_query, second_query)
        await adapter.close()

    async def test_login_timeout_raises_auth_required_and_restores_headless(self):
        clock = FakeClock()
        page = FakePage(
            final_url="https://accounts.google.com/v3/signin/identifier",
            body="Sign in",
            on_wait=clock.advance_ms,
        )
        before = FakeContext()
        headful = FakeContext(page)
        after = FakeContext()
        adapter, playwright = self.make_adapter(
            before,
            headful,
            after,
            timeout=0.2,
            clock=clock,
        )
        await adapter.start()

        with self.assertRaises(BrowserAuthRequired) as raised:
            await adapter.interactive_login()

        self.assertIs(raised.exception.state, AuthState.AUTH_REQUIRED_GOOGLE)
        self.assertEqual(
            [launch["headless"] for launch in playwright.chromium.launches],
            [True, False, True],
        )
        await adapter.close()

    async def test_login_early_window_close_is_browser_error_and_restores_headless(self):
        clock = FakeClock()
        page = FakePage(
            final_url="https://login.microsoftonline.com/tenant/saml2",
            body="Sign in",
            close_after_waits=1,
            on_wait=clock.advance_ms,
        )
        adapter, playwright = self.make_adapter(
            FakeContext(),
            FakeContext(page),
            FakeContext(),
            clock=clock,
        )
        await adapter.start()

        with self.assertRaises(BrowserAdapterError):
            await adapter.interactive_login()

        self.assertEqual(
            [launch["headless"] for launch in playwright.chromium.launches],
            [True, False, True],
        )
        await adapter.close()

    async def test_login_browser_crash_is_browser_error_and_restores_headless(self):
        page = FakePage(goto_error=RuntimeError("browser crashed"))
        adapter, playwright = self.make_adapter(
            FakeContext(),
            FakeContext(page),
            FakeContext(),
        )
        await adapter.start()

        with self.assertRaises(BrowserAdapterError):
            await adapter.interactive_login()

        self.assertEqual(
            [launch["headless"] for launch in playwright.chromium.launches],
            [True, False, True],
        )
        await adapter.close()

    async def test_login_cancellation_propagates_after_restoring_headless(self):
        entered = asyncio.Event()

        class BlockingPage(FakePage):
            async def text_content(self, selector):
                entered.set()
                await asyncio.Event().wait()

        page = BlockingPage(
            final_url="https://login.microsoftonline.com/tenant/saml2"
        )
        restored = FakeContext()
        adapter, playwright = self.make_adapter(
            FakeContext(),
            FakeContext(page),
            restored,
        )
        await adapter.start()
        task = asyncio.create_task(adapter.interactive_login())
        await entered.wait()

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertEqual(
            [launch["headless"] for launch in playwright.chromium.launches],
            [True, False, True],
        )
        await adapter.close()
        self.assertEqual(restored.close_calls, 1)


class LoginVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_broker_verifies_authenticated_login_through_restored_headless_adapter(self):
        events = []

        class RecordingAdapter:
            async def start(self):
                events.append("start")

            async def close(self):
                events.append("close")

            async def interactive_login(self):
                events.append("login")
                return AuthState.AUTHENTICATED

            async def execute(self, method, params):
                events.append(("verify", method, params))
                return '{"status":"success"}'

        broker = GmailEdgeBroker(RecordingAdapter())

        result = await broker._perform_login()

        self.assertEqual(result, {"state": "AUTHENTICATED"})
        self.assertEqual(events[0:2], ["start", "login"])
        self.assertEqual(events[2][0:2], ("verify", "gmail_search"))
        self.assertEqual(set(events[2][2]), {"query"})

    async def test_recoverable_login_window_close_verifies_restored_headless_context(self):
        events = []

        class RecoverableAdapter:
            async def start(self):
                events.append("start")

            async def close(self):
                events.append("close")

            async def interactive_login(self):
                events.append("login")
                raise BrowserLoginError(
                    "Managed Edge interactive login window was closed",
                    can_verify=True,
                )

            async def execute(self, method, params):
                events.append(("verify", method, params))
                return '{"status":"success"}'

        broker = GmailEdgeBroker(RecoverableAdapter())

        result = await broker._perform_login()

        self.assertEqual(result, {"state": "AUTHENTICATED"})
        self.assertEqual(events[0:2], ["start", "login"])
        self.assertEqual(events[2][0:2], ("verify", "gmail_search"))
        self.assertEqual(set(events[2][2]), {"query"})

    async def test_login_verification_timeout_maps_to_terminal_request_timeout(self):
        events = []

        class TimeoutAdapter:
            async def start(self):
                events.append("start")

            async def close(self):
                events.append("close")

            async def interactive_login(self):
                events.append("login")
                return AuthState.AUTHENTICATED

            async def execute(self, method, params):
                events.append(("verify", method, params))
                raise BrowserOperationTimeout("verification timed out")

        broker = GmailEdgeBroker(TimeoutAdapter())
        response = await broker._dispatch(
            BrokerRequest(
                version=PROTOCOL_VERSION,
                id="login-timeout-id",
                token="test-token",
                method="auth_login",
                params={},
            )
        )

        self.assertFalse(response.ok)
        self.assertIs(response.error.code, BrokerErrorCode.REQUEST_TIMEOUT)
        self.assertEqual(events[0:2], ["start", "login"])
        self.assertEqual(events[2][0:2], ("verify", "gmail_search"))
        self.assertNotIn("close", events)


class BrokerLoginRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.profile = self.root / "edge_broker_profile"

    def make_broker(self, *contexts, clock=None):
        playwright = FakePlaywright(*contexts)
        starter = FakePlaywrightStarter(playwright)
        adapter = ManagedEdgeAdapter(
            profile_dir=self.profile,
            user_home=self.root,
            playwright_factory=lambda: starter,
            app_script_url=APP_URL,
            login_timeout_seconds=1,
            login_poll_interval_ms=100,
            clock=clock or FakeClock(),
        )
        return GmailEdgeBroker(adapter), adapter, starter, playwright

    @staticmethod
    def request(method, request_id):
        params = {"query": "case"} if method == "gmail_search" else {}
        return BrokerRequest(
            version=PROTOCOL_VERSION,
            id=request_id,
            token="test-token",
            method=method,
            params=params,
        )

    async def assert_restored_headless_survives_login_error(
        self,
        login_page,
        *,
        expect_login_success=False,
    ):
        restored_page = FakePage(body='{"status":"success","messages":[]}')
        restored_pages = [restored_page]
        if expect_login_success:
            restored_pages.append(FakePage(body='{"status":"success","messages":[]}'))
        restored = FakeContext(*restored_pages)
        broker, adapter, starter, playwright = self.make_broker(
            FakeContext(),
            FakeContext(login_page),
            restored,
        )
        try:
            login = await broker._dispatch(self.request("auth_login", "login-id"))

            if expect_login_success:
                self.assertTrue(login.ok)
                self.assertEqual(login.result, {"state": "AUTHENTICATED"})
            else:
                self.assertFalse(login.ok)
                self.assertIs(login.error.code, BrokerErrorCode.BROWSER_ERROR)
            self.assertTrue(broker._browser_started)
            self.assertEqual(restored.close_calls, 0)

            search = await broker._dispatch(
                self.request("gmail_search", "search-id")
            )

            self.assertTrue(search.ok)
            self.assertEqual(
                search.result,
                '{"status":"success","messages":[]}',
            )
            self.assertEqual(starter.start_calls, 1)
            self.assertEqual(
                [launch["headless"] for launch in playwright.chromium.launches],
                [True, False, True],
            )
            self.assertEqual(restored.close_calls, 0)
        finally:
            await broker._discard_browser()
            await adapter.close()

    async def test_early_login_window_close_keeps_restored_headless_owned(self):
        clock = FakeClock()
        page = FakePage(
            final_url="https://login.microsoftonline.com/tenant/saml2",
            body="Sign in",
            close_after_waits=1,
            on_wait=clock.advance_ms,
        )
        await self.assert_restored_headless_survives_login_error(
            page,
            expect_login_success=True,
        )

    async def test_headful_browser_error_keeps_restored_headless_owned(self):
        page = FakePage(goto_error=RuntimeError("headful browser crashed"))
        await self.assert_restored_headless_survives_login_error(page)

    async def test_broker_never_returns_html_bridge_error_as_success(self):
        error_pages = [
            FakePage(body="<html>Page Not Found</html>") for _ in range(3)
        ]
        broker, adapter, _starter, _playwright = self.make_broker(
            FakeContext(*error_pages),
        )
        try:
            response = await broker._dispatch(
                self.request("gmail_search", "html-error-id")
            )

            self.assertFalse(response.ok)
            self.assertIs(response.error.code, BrokerErrorCode.APP_ERROR)
            self.assertIsNone(response.result)
            self.assertTrue(all(page.close_calls == 1 for page in error_pages))
        finally:
            await broker._discard_browser()
            await adapter.close()

    async def test_failed_headless_restore_is_discarded_and_next_read_restarts(self):
        restored_page = FakePage(body='{"status":"success","messages":[]}')
        restarted = FakeContext(restored_page)
        page = FakePage(goto_error=RuntimeError("headful browser crashed"))
        broker, adapter, starter, playwright = self.make_broker(
            FakeContext(),
            FakeContext(page),
            RuntimeError("headless restore failed"),
            restarted,
        )
        try:
            login = await broker._dispatch(self.request("auth_login", "login-id"))

            self.assertFalse(login.ok)
            self.assertIs(login.error.code, BrokerErrorCode.BROWSER_ERROR)
            self.assertFalse(broker._browser_started)

            search = await broker._dispatch(
                self.request("gmail_search", "search-id")
            )

            self.assertTrue(search.ok)
            self.assertEqual(starter.start_calls, 2)
            self.assertEqual(
                [launch["headless"] for launch in playwright.chromium.launches],
                [True, False, True, True],
            )
            self.assertTrue(broker._browser_started)
            self.assertEqual(restarted.close_calls, 0)
        finally:
            await broker._discard_browser()
            await adapter.close()


if __name__ == "__main__":
    unittest.main()
