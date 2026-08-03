import asyncio
import logging
import os
import unittest
from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from tools.gmail.gmail_edge_broker import (
    BrowserAdapterError,
    BrowserApplicationError,
    BrowserAuthRequired,
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

    async def text_content(self, selector):
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
        pages = [FakePage(body=f"response-{index}") for index in range(3)]
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
        ]

        self.assertEqual(results, ["response-0", "response-1", "response-2"])
        self.assertEqual(len(context.created_pages), 3)
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
        ]
        for page, (action, params) in zip(pages, expected):
            url = page.goto_calls[0][0]
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query.pop("action"), [action])
            self.assertEqual(query, params)
            self.assertEqual(page.load_state_calls[0][0], "networkidle")
            self.assertLess(page.events.index("wait:networkidle"), page.events.index("body"))
            self.assertEqual(page.close_calls, 1)

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
        page = FakePage(body=sentinel)
        adapter, _starter, _playwright = self.make_adapter(FakeContext(page))
        await adapter.start()

        with patch.object(logging.Logger, "_log") as log_call:
            result = await adapter.execute("gmail_search", {"query": "case"})

        self.assertEqual(result, sentinel)
        self.assertNotIn(sentinel, repr(log_call.call_args_list))
        await adapter.close()

    async def test_maps_application_and_browser_failures_to_adapter_errors(self):
        app_page = FakePage(status=503, body="PRIVATE_ERROR_BODY")
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
            ("health", {}),
        ):
            with self.subTest(method=method, params=params):
                with self.assertRaises(BrowserApplicationError):
                    await adapter.execute(method, params)

        self.assertEqual(context.created_pages, [])
        await adapter.close()

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

    def make_adapter(self, *contexts, timeout=5.0, clock=None):
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

    async def assert_restored_headless_survives_login_error(self, login_page):
        restored_page = FakePage(body='{"status":"success","messages":[]}')
        restored = FakeContext(restored_page)
        broker, adapter, starter, playwright = self.make_broker(
            FakeContext(),
            FakeContext(login_page),
            restored,
        )
        try:
            login = await broker._dispatch(self.request("auth_login", "login-id"))

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
        await self.assert_restored_headless_survives_login_error(page)

    async def test_headful_browser_error_keeps_restored_headless_owned(self):
        page = FakePage(goto_error=RuntimeError("headful browser crashed"))
        await self.assert_restored_headless_survives_login_error(page)

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
