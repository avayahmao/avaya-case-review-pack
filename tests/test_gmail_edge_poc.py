import unittest

from tools.gmail.gmail_edge_common import AuthState, ProbeResult
from tools.gmail.gmail_edge_poc import (
    PROBE_QUERY,
    build_probe_url,
    exit_code_for,
    poll_page_auth,
    summarize_results,
    validate_repeat_count,
)


class ExitCodeTests(unittest.TestCase):
    def test_exit_code_mapping(self):
        self.assertEqual(exit_code_for(AuthState.AUTHENTICATED), 0)
        self.assertEqual(exit_code_for(AuthState.AUTH_REQUIRED_MICROSOFT), 10)
        self.assertEqual(exit_code_for(AuthState.AUTH_REQUIRED_GOOGLE), 10)
        self.assertEqual(exit_code_for(AuthState.BROWSER_ERROR), 20)
        self.assertEqual(exit_code_for(AuthState.APP_ERROR), 30)
        self.assertEqual(exit_code_for(AuthState.UNKNOWN), 30)


class PublicOutputTests(unittest.TestCase):
    def test_repeat_summary_counts_states_and_marks_context_reuse(self):
        summary = summarize_results(
            [
                ProbeResult(
                    AuthState.AUTHENTICATED,
                    200,
                    "script.googleusercontent.com",
                    "/a",
                    2,
                    10,
                ),
                ProbeResult(
                    AuthState.AUTH_REQUIRED_MICROSOFT,
                    200,
                    "login.microsoftonline.com",
                    "/saml2",
                    10,
                    11,
                ),
                ProbeResult(
                    AuthState.BROWSER_ERROR,
                    None,
                    "",
                    "",
                    0,
                    1,
                ),
            ]
        )
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["authenticated"], 1)
        self.assertEqual(summary["authentication_required"], 1)
        self.assertEqual(summary["errors"], 1)
        self.assertTrue(summary["context_reused"])
        self.assertEqual(len(summary["probes"]), 3)

    def test_probe_query_cannot_match_normal_mail(self):
        self.assertEqual(PROBE_QUERY, "subject:__avaya_gmail_edge_poc__")

    def test_build_probe_url_encodes_query(self):
        url = build_probe_url("https://script.google.com/example/exec")
        self.assertEqual(
            url,
            "https://script.google.com/example/exec?"
            "action=search&q=subject%3A__avaya_gmail_edge_poc__",
        )

    def test_repeat_count_bounds(self):
        self.assertEqual(validate_repeat_count(1), 1)
        self.assertEqual(validate_repeat_count(20), 20)
        with self.assertRaises(ValueError):
            validate_repeat_count(0)
        with self.assertRaises(ValueError):
            validate_repeat_count(21)


class LoginPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_navigation_error_does_not_abort_login(self):
        class FakePage:
            def __init__(self):
                self.url = (
                    "https://avaya365-onmicrosoft-com.access.mcas.ms/aad_login"
                )
                self.calls = 0

            def is_closed(self):
                return False

            async def text_content(self, selector):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("Execution context was destroyed")
                return '{"status":"success","messages":[]}'

            async def wait_for_timeout(self, milliseconds):
                self.url = "https://script.googleusercontent.com/macros/echo"

        result = await poll_page_auth(FakePage(), 200, timeout_seconds=2)
        self.assertIs(result.state, AuthState.AUTHENTICATED)


if __name__ == "__main__":
    unittest.main()
