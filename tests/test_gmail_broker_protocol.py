import json
import unittest
from unittest.mock import patch

from tools.gmail.gmail_broker_protocol import (
    ALLOWED_METHODS,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    BrokerError,
    BrokerErrorCode,
    BrokerRequest,
    BrokerResponse,
    ProtocolError,
    decode_request,
    encode_response,
    validate_token,
)


class RequestDecodingTests(unittest.TestCase):
    def make_frame(self, **overrides):
        payload = {
            "version": 1,
            "id": "abc",
            "token": "secret",
            "method": "gmail_search",
            "params": {"query": "sr"},
        }
        payload.update(overrides)
        return json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"

    def assert_invalid(self, raw):
        with self.assertRaises(ProtocolError) as raised:
            decode_request(raw)
        self.assertIs(raised.exception.code, BrokerErrorCode.INVALID_REQUEST)

    def test_protocol_constants_match_wire_contract(self):
        self.assertEqual(PROTOCOL_VERSION, 1)
        self.assertEqual(MAX_FRAME_BYTES, 8 * 1024 * 1024)
        self.assertEqual(
            ALLOWED_METHODS,
            frozenset(
                {
                    "health",
                    "gmail_search",
                    "gmail_read",
                    "gmail_send",
                    "auth_login",
                    "shutdown",
                }
            ),
        )

    def test_decodes_valid_request(self):
        request = decode_request(self.make_frame())

        self.assertEqual(
            request,
            BrokerRequest(
                version=1,
                id="abc",
                token="secret",
                method="gmail_search",
                params={"query": "sr"},
            ),
        )

    def test_accepts_every_allowed_method(self):
        for method in ALLOWED_METHODS:
            with self.subTest(method=method):
                self.assertEqual(decode_request(self.make_frame(method=method)).method, method)

    def test_request_repr_redacts_token_and_params(self):
        rendered = repr(decode_request(self.make_frame()))

        self.assertNotIn("secret", rendered)
        self.assertNotIn("query", rendered)

    def test_rejects_each_missing_top_level_field(self):
        payload = json.loads(self.make_frame())
        for field in tuple(payload):
            with self.subTest(field=field):
                incomplete = dict(payload)
                incomplete.pop(field)
                self.assert_invalid(
                    json.dumps(incomplete, separators=(",", ":")).encode("utf-8") + b"\n"
                )

    def test_rejects_extra_top_level_field(self):
        self.assert_invalid(self.make_frame(debug=True))

    def test_rejects_unsupported_or_non_integer_version(self):
        for version in (2, True, "1", 1.0, None):
            with self.subTest(version=version):
                self.assert_invalid(self.make_frame(version=version))

    def test_rejects_unknown_method(self):
        self.assert_invalid(self.make_frame(method="shell"))

    def test_rejects_non_string_or_empty_id(self):
        for request_id in (None, 7, ""):
            with self.subTest(request_id=request_id):
                self.assert_invalid(self.make_frame(id=request_id))

    def test_rejects_non_string_or_empty_token(self):
        for token in (None, 7, ""):
            with self.subTest(token=token):
                self.assert_invalid(self.make_frame(token=token))

    def test_rejects_non_string_or_empty_method(self):
        for method in (None, 7, ""):
            with self.subTest(method=method):
                self.assert_invalid(self.make_frame(method=method))

    def test_rejects_non_object_params(self):
        for params in (None, [], "query=sr", 7):
            with self.subTest(params=params):
                self.assert_invalid(self.make_frame(params=params))

    def test_rejects_oversized_frame(self):
        self.assert_invalid(b"x" * (MAX_FRAME_BYTES + 1))

    def test_rejects_missing_line_terminator(self):
        self.assert_invalid(self.make_frame().removesuffix(b"\n"))

    def test_rejects_crlf_terminator(self):
        self.assert_invalid(self.make_frame().removesuffix(b"\n") + b"\r\n")

    def test_rejects_embedded_or_multiple_frames(self):
        self.assert_invalid(self.make_frame() + self.make_frame())

    def test_rejects_invalid_utf8(self):
        self.assert_invalid(b'\xff\n')

    def test_rejects_invalid_json(self):
        self.assert_invalid(b'{"version":1,}\n')

    def test_rejects_non_object_json(self):
        self.assert_invalid(b'[]\n')

    def test_rejects_duplicate_json_fields(self):
        self.assert_invalid(
            b'{"version":1,"version":1,"id":"abc","token":"secret",'
            b'"method":"health","params":{}}\n'
        )

    def test_rejects_nonstandard_json_constants(self):
        self.assert_invalid(
            b'{"version":1,"id":"abc","token":"secret",'
            b'"method":"health","params":{"value":NaN}}\n'
        )


class TokenValidationTests(unittest.TestCase):
    def test_uses_constant_time_token_comparison(self):
        with patch(
            "tools.gmail.gmail_broker_protocol.secrets.compare_digest",
            return_value=True,
        ) as compare_digest:
            self.assertTrue(validate_token("presented", "expected"))

        compare_digest.assert_called_once_with("presented", "expected")

    def test_non_string_tokens_do_not_reach_comparison(self):
        for presented, expected in ((None, "token"), ("token", None), (1, "1")):
            with self.subTest(presented=presented, expected=expected):
                self.assertFalse(validate_token(presented, expected))

    def test_non_ascii_token_fails_safely(self):
        self.assertFalse(validate_token("t\u00f6ken", "token"))


class ResponseEncodingTests(unittest.TestCase):
    def test_error_code_enum_contains_broker_contract(self):
        self.assertEqual(
            {code.value for code in BrokerErrorCode},
            {
                "AUTH_REQUIRED",
                "LOGIN_IN_PROGRESS",
                "INVALID_REQUEST",
                "REQUEST_TIMEOUT",
                "RESPONSE_TOO_LARGE",
                "BROWSER_ERROR",
                "APP_ERROR",
            },
        )

    def test_encodes_success_as_one_utf8_json_line(self):
        encoded = encode_response(
            BrokerResponse.success("abc", {"subject": "R\u00e9sum\u00e9"})
        )

        self.assertTrue(encoded.endswith(b"\n"))
        self.assertNotIn(b"\n", encoded[:-1])
        self.assertEqual(
            json.loads(encoded.decode("utf-8")),
            {
                "version": 1,
                "id": "abc",
                "ok": True,
                "result": {"subject": "R\u00e9sum\u00e9"},
            },
        )

    def test_encodes_typed_error_as_one_json_line(self):
        encoded = encode_response(
            BrokerResponse.failure(
                "abc",
                BrokerErrorCode.AUTH_REQUIRED,
                "Interactive Gmail authentication is required",
            )
        )

        self.assertEqual(
            json.loads(encoded.decode("utf-8")),
            {
                "version": 1,
                "id": "abc",
                "ok": False,
                "error": {
                    "code": "AUTH_REQUIRED",
                    "message": "Interactive Gmail authentication is required",
                },
            },
        )

    def test_response_repr_redacts_result_and_error_sentinels(self):
        sentinel = "SENSITIVE_RESPONSE_SENTINEL"
        responses = (
            BrokerResponse.success("abc", {"body": sentinel}),
            BrokerResponse.failure("abc", BrokerErrorCode.APP_ERROR, sentinel),
        )

        for response in responses:
            with self.subTest(ok=response.ok):
                self.assertNotIn(sentinel, repr(response))

    def test_direct_response_rejects_non_broker_error_with_typed_failure(self):
        with self.assertRaises(ProtocolError) as raised:
            BrokerResponse(id="abc", ok=False, error={"code": "APP_ERROR"})

        self.assertIs(raised.exception.code, BrokerErrorCode.APP_ERROR)

    def test_rejects_oversized_response(self):
        response = BrokerResponse.success("abc", "x" * MAX_FRAME_BYTES)

        with self.assertRaises(ProtocolError) as raised:
            encode_response(response)

        self.assertIs(raised.exception.code, BrokerErrorCode.RESPONSE_TOO_LARGE)

    def test_response_requires_nonempty_string_id(self):
        for request_id in (None, 7, ""):
            with self.subTest(request_id=request_id):
                with self.assertRaises(ValueError):
                    BrokerResponse.success(request_id, None)

    def test_response_model_rejects_invalid_success_error_combinations(self):
        error = BrokerError(BrokerErrorCode.APP_ERROR, "failed")

        with self.assertRaises(ValueError):
            BrokerResponse(id="abc", ok=True, error=error)
        with self.assertRaises(ValueError):
            BrokerResponse(id="abc", ok=False)


if __name__ == "__main__":
    unittest.main()
