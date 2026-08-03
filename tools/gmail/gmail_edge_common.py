"""Browser-independent authentication primitives for Managed Edge Gmail."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlencode, urlparse


APP_SCRIPT_URL = (
    "https://script.google.com/a/macros/avaya.com/s/"
    "AKfycbwfqUGLMBppaPEtdzAC74_TeT34shpYkIVv5FMY1JjhqPDH0MXEp-"
    "WdeTOp8zmCDL0F/exec"
)


class AuthState(str, Enum):
    AUTHENTICATED = "AUTHENTICATED"
    AUTH_REQUIRED_MICROSOFT = "AUTH_REQUIRED_MICROSOFT"
    AUTH_REQUIRED_GOOGLE = "AUTH_REQUIRED_GOOGLE"
    APP_ERROR = "APP_ERROR"
    BROWSER_ERROR = "BROWSER_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProbeResult:
    state: AuthState
    http_status: int | None
    final_host: str
    final_path: str
    body_length: int
    elapsed_ms: int

    def to_public_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "http_status": self.http_status,
            "final_host": self.final_host,
            "final_path": self.final_path,
            "body_length": self.body_length,
            "elapsed_ms": self.elapsed_ms,
        }


def build_action_url(
    action: str,
    params: dict[str, str],
    *,
    base_url: str = APP_SCRIPT_URL,
) -> str:
    query = {"action": action}
    query.update(
        (key, value)
        for key, value in params.items()
        if key != "action"
    )
    return f"{base_url}?{urlencode(query)}"


def classify_response(
    final_url: str,
    http_status: int | None,
    body: str,
) -> AuthState:
    parsed = urlparse(final_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    body_prefix = body[:1000].lower()
    url_lower = final_url.lower()

    if (
        host == "login.microsoftonline.com"
        or host.endswith(".access.mcas.ms")
        or "/saml2" in path
        or path == "/aad_login"
    ):
        return AuthState.AUTH_REQUIRED_MICROSOFT
    if host == "accounts.google.com" or "servicelogin" in url_lower:
        return AuthState.AUTH_REQUIRED_GOOGLE
    if http_status is not None and http_status >= 400:
        return AuthState.APP_ERROR

    compact_body = "".join(body_prefix.split())
    is_script_response = host.endswith("script.googleusercontent.com") or (
        host.endswith("script.google.com")
        and body.lstrip().startswith(("{", "["))
    )
    if is_script_response:
        if '"status":"error"' in compact_body:
            return AuthState.APP_ERROR
        return AuthState.AUTHENTICATED

    if "sign in" in body_prefix:
        return AuthState.AUTH_REQUIRED_GOOGLE
    return AuthState.UNKNOWN


def validate_profile_path(profile: Path, user_home: Path) -> Path:
    resolved = profile.expanduser().resolve()
    forbidden = {
        (user_home / ".gemini/tools/gmail/chrome_profile").resolve(),
        (user_home / "AppData/Local/Microsoft/Edge/User Data").resolve(),
    }
    if resolved in forbidden or any(root in resolved.parents for root in forbidden):
        raise ValueError(
            "PoC profile must not use a production Chromium or normal Edge profile"
        )
    return resolved
