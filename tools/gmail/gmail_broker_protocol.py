"""Authenticated NDJSON wire protocol for the Gmail Edge broker."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_REQUEST_ID_BYTES = 128
ALLOWED_METHODS = frozenset(
    {
        "health",
        "gmail_search",
        "gmail_read",
        "gmail_send",
        "auth_login",
        "shutdown",
    }
)

_REQUEST_FIELDS = frozenset({"version", "id", "token", "method", "params"})


class BrokerErrorCode(str, Enum):
    """Errors that can cross the broker wire boundary."""

    AUTH_REQUIRED = "AUTH_REQUIRED"
    LOGIN_IN_PROGRESS = "LOGIN_IN_PROGRESS"
    INVALID_REQUEST = "INVALID_REQUEST"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    BROWSER_ERROR = "BROWSER_ERROR"
    APP_ERROR = "APP_ERROR"


class ProtocolError(ValueError):
    """A safe, typed wire-protocol failure."""

    def __init__(self, code: BrokerErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _is_valid_wire_string(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and value.isprintable()
    )


def _is_valid_request_id(value: object) -> bool:
    return _is_valid_wire_string(value) and len(value.encode("utf-8")) <= MAX_REQUEST_ID_BYTES


@dataclass(frozen=True)
class BrokerRequest:
    """A validated broker request; sensitive fields are omitted from ``repr``."""

    version: int
    id: str
    token: str = field(repr=False)
    method: str
    params: dict[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != PROTOCOL_VERSION:
            raise ValueError("Unsupported broker protocol version")
        if not _is_valid_request_id(self.id):
            raise ValueError(
                "Request id must be a printable string no larger than "
                f"{MAX_REQUEST_ID_BYTES} UTF-8 bytes"
            )
        if not _is_valid_wire_string(self.token):
            raise ValueError("Request token must be a non-empty printable string")
        if not isinstance(self.method, str) or self.method not in ALLOWED_METHODS:
            raise ValueError("Unsupported broker method")
        if not isinstance(self.params, dict):
            raise ValueError("Request params must be a JSON object")


@dataclass(frozen=True)
class BrokerError:
    """Typed error payload for an unsuccessful broker response."""

    code: BrokerErrorCode
    message: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.code, BrokerErrorCode):
            raise ValueError("Broker error code must be a BrokerErrorCode")
        if not _is_valid_wire_string(self.message):
            raise ValueError("Broker error message must be a non-empty printable string")

    def to_wire_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


@dataclass(frozen=True)
class BrokerResponse:
    """Success or error response with mutually exclusive payload fields."""

    id: str
    ok: bool
    result: Any = field(default=None, repr=False)
    error: BrokerError | None = field(default=None, repr=False)
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != PROTOCOL_VERSION:
            raise ValueError("Unsupported broker protocol version")
        if not _is_valid_request_id(self.id):
            raise ValueError(
                "Response id must be a printable string no larger than "
                f"{MAX_REQUEST_ID_BYTES} UTF-8 bytes"
            )
        if type(self.ok) is not bool:
            raise ValueError("Response ok must be a boolean")
        if self.error is not None and not isinstance(self.error, BrokerError):
            raise ProtocolError(
                BrokerErrorCode.APP_ERROR,
                "Response error payload must be a BrokerError",
            )
        if self.ok and self.error is not None:
            raise ValueError("Successful response cannot contain an error")
        if not self.ok and self.error is None:
            raise ValueError("Error response requires an error payload")
        if not self.ok and self.result is not None:
            raise ValueError("Error response cannot contain a result")

    @classmethod
    def success(cls, request_id: str, result: Any) -> "BrokerResponse":
        return cls(id=request_id, ok=True, result=result)

    @classmethod
    def failure(
        cls,
        request_id: str,
        code: BrokerErrorCode,
        message: str,
    ) -> "BrokerResponse":
        return cls(id=request_id, ok=False, error=BrokerError(code, message))

    def to_wire_dict(self) -> dict[str, Any]:
        common: dict[str, Any] = {
            "version": self.version,
            "id": self.id,
            "ok": self.ok,
        }
        if self.ok:
            common["result"] = self.result
        else:
            assert self.error is not None
            common["error"] = self.error.to_wire_dict()
        return common


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise ValueError("Non-standard JSON constant")


def _invalid_request(message: str) -> ProtocolError:
    return ProtocolError(BrokerErrorCode.INVALID_REQUEST, message)


def decode_request(frame: bytes) -> BrokerRequest:
    """Decode and strictly validate one newline-terminated request frame."""

    if not isinstance(frame, bytes):
        raise _invalid_request("Request frame must be bytes")
    if len(frame) > MAX_FRAME_BYTES:
        raise _invalid_request("Request frame exceeds the size limit")
    if not frame.endswith(b"\n"):
        raise _invalid_request("Request frame must end with one newline")

    body = frame[:-1]
    if b"\n" in body or b"\r" in body:
        raise _invalid_request("Request frame must contain exactly one JSON line")

    try:
        text = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _invalid_request("Request frame is not valid UTF-8") from exc

    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_fields,
            parse_constant=_reject_nonstandard_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise _invalid_request("Request frame is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise _invalid_request("Request payload must be a JSON object")
    if frozenset(payload) != _REQUEST_FIELDS:
        raise _invalid_request("Request payload fields do not match the protocol")

    version = payload["version"]
    request_id = payload["id"]
    token = payload["token"]
    method = payload["method"]
    params = payload["params"]

    if type(version) is not int or version != PROTOCOL_VERSION:
        raise _invalid_request("Unsupported broker protocol version")
    if not _is_valid_request_id(request_id):
        raise _invalid_request(
            "Request id must be a printable string no larger than "
            f"{MAX_REQUEST_ID_BYTES} UTF-8 bytes"
        )
    if not _is_valid_wire_string(token):
        raise _invalid_request("Request token must be a non-empty printable string")
    if not isinstance(method, str) or method not in ALLOWED_METHODS:
        raise _invalid_request("Unsupported broker method")
    if not isinstance(params, dict):
        raise _invalid_request("Request params must be a JSON object")

    return BrokerRequest(
        version=version,
        id=request_id,
        token=token,
        method=method,
        params=params,
    )


def validate_token(presented: object, expected: object) -> bool:
    """Compare two string tokens without data-dependent early exit."""

    if not isinstance(presented, str) or not isinstance(expected, str):
        return False
    try:
        return secrets.compare_digest(presented, expected)
    except TypeError:
        return False


def encode_response(response: BrokerResponse) -> bytes:
    """Encode a response as one UTF-8 JSON line within the frame limit."""

    if not isinstance(response, BrokerResponse):
        raise TypeError("response must be a BrokerResponse")
    try:
        encoded = (
            json.dumps(
                response.to_wire_dict(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError(
            BrokerErrorCode.APP_ERROR,
            "Broker response is not JSON serializable",
        ) from exc

    if len(encoded) > MAX_FRAME_BYTES:
        raise ProtocolError(
            BrokerErrorCode.RESPONSE_TOO_LARGE,
            "Broker response exceeds the size limit",
        )
    return encoded


__all__ = [
    "ALLOWED_METHODS",
    "MAX_FRAME_BYTES",
    "MAX_REQUEST_ID_BYTES",
    "PROTOCOL_VERSION",
    "BrokerError",
    "BrokerErrorCode",
    "BrokerRequest",
    "BrokerResponse",
    "ProtocolError",
    "decode_request",
    "encode_response",
    "validate_token",
]
