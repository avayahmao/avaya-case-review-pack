import unittest
from pathlib import Path

from tools.gmail.gmail_edge_common import (
    AuthState,
    ProbeResult,
    build_action_url,
    classify_response,
    validate_profile_path,
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


class ActionUrlTests(unittest.TestCase):
    def test_build_action_url_encodes_action_and_params(self):
        url = build_action_url("search", {"q": "subject:1-23508794022"})

        self.assertIn("action=search", url)
        self.assertIn("q=subject%3A1-23508794022", url)


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


if __name__ == "__main__":
    unittest.main()
