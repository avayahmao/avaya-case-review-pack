import unittest
from pathlib import Path

from tools.gmail.gmail_edge_poc import (
    AuthState,
    PROBE_QUERY,
    ProbeResult,
    build_probe_url,
    classify_response,
    exit_code_for,
    poll_page_auth,
    summarize_results,
    validate_profile_path,
    validate_repeat_count,
)


class AuthClassificationTests(unittest.TestCase):
    def test_classifies_microsoft_saml(self):
        state = classify_response(
            "https://login.microsoftonline.com/tenant/saml2",
            200,
            "<html>Sign in</html>",
        )
        self.assertIs(state, AuthState.AUTH_REQUIRED_MICROSOFT)

    def test_classifies_microsoft_cloud_app_security_login(self):
        state = classify_response(
            "https://avaya365-onmicrosoft-com.access.mcas.ms/aad_login",
            200,
            "",
        )
        self.assertIs(state, AuthState.AUTH_REQUIRED_MICROSOFT)

    def test_classifies_google_login(self):
        state = classify_response(
            "https://accounts.google.com/v3/signin/identifier",
            200,
            "<html>Sign in</html>",
        )
        self.assertIs(state, AuthState.AUTH_REQUIRED_GOOGLE)

    def test_classifies_apps_script_json(self):
        state = classify_response(
            "https://script.googleusercontent.com/macros/echo",
            200,
            '{"status":"success","messages":[]}',
        )
        self.assertIs(state, AuthState.AUTHENTICATED)

    def test_classifies_apps_script_error(self):
        state = classify_response(
            "https://script.googleusercontent.com/macros/echo",
            200,
            '{"status":"error","message":"request failed"}',
        )
        self.assertIs(state, AuthState.APP_ERROR)

    def test_classifies_http_error(self):
        state = classify_response(
            "https://script.googleusercontent.com/macros/echo",
            503,
            "unavailable",
        )
        self.assertIs(state, AuthState.APP_ERROR)

    def test_classifies_unknown_response(self):
        state = classify_response(
            "https://example.invalid/",
            200,
            "unexpected response",
        )
        self.assertIs(state, AuthState.UNKNOWN)

    def test_exit_code_mapping(self):
        self.assertEqual(exit_code_for(AuthState.AUTHENTICATED), 0)
        self.assertEqual(exit_code_for(AuthState.AUTH_REQUIRED_MICROSOFT), 10)
        self.assertEqual(exit_code_for(AuthState.AUTH_REQUIRED_GOOGLE), 10)
        self.assertEqual(exit_code_for(AuthState.BROWSER_ERROR), 20)
        self.assertEqual(exit_code_for(AuthState.APP_ERROR), 30)
        self.assertEqual(exit_code_for(AuthState.UNKNOWN), 30)


class ProfileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(r"C:\Users\tester")

    def test_rejects_production_chrome_profile(self):
        with self.assertRaises(ValueError):
            validate_profile_path(
                self.home / ".gemini/tools/gmail/chrome_profile",
                self.home,
            )

    def test_rejects_normal_edge_profile(self):
        with self.assertRaises(ValueError):
            validate_profile_path(
                self.home / "AppData/Local/Microsoft/Edge/User Data",
                self.home,
            )

    def test_accepts_dedicated_poc_profile(self):
        path = validate_profile_path(
            self.home / ".gemini/tools/gmail/edge_poc_profile",
            self.home,
        )
        self.assertTrue(str(path).lower().endswith("edge_poc_profile"))


class PublicOutputTests(unittest.TestCase):
    def test_public_result_contains_only_approved_fields(self):
        result = ProbeResult(
            state=AuthState.AUTHENTICATED,
            http_status=200,
            final_host="script.googleusercontent.com",
            final_path="/macros/echo",
            body_length=123,
            elapsed_ms=50,
        ).to_public_dict()
        self.assertEqual(
            set(result),
            {
                "state",
                "http_status",
                "final_host",
                "final_path",
                "body_length",
                "elapsed_ms",
            },
        )
        lowered = " ".join(result).lower()
        self.assertNotIn("body", lowered.replace("body_length", ""))
        self.assertNotIn("cookie", lowered)
        self.assertNotIn("token", lowered)
        self.assertNotIn("account", lowered)

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
        self.assertIn("action=search", url)
        self.assertIn("subject%3A__avaya_gmail_edge_poc__", url)

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
