"""Serialized, authenticated loopback broker for one Managed Edge owner."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
import re
import secrets
import sys
import time
import uuid
from typing import Any, Callable, Protocol

if __package__:
    from .gmail_broker_protocol import (
        MAX_FRAME_BYTES,
        PROTOCOL_VERSION,
        BrokerErrorCode,
        BrokerRequest,
        BrokerResponse,
        ProtocolError,
        decode_request,
        encode_response,
        validate_token,
    )
    from .gmail_broker_state import (
        BrokerState,
        BrokerStateStore,
        LifetimeFileLock,
        SanitizedRotatingLogger,
        apply_windows_acl,
        default_broker_paths,
    )
    from .gmail_edge_common import (
        APP_SCRIPT_URL,
        AuthState,
        build_action_url,
        classify_response,
        validate_profile_path,
    )
else:
    from gmail_broker_protocol import (
        MAX_FRAME_BYTES,
        PROTOCOL_VERSION,
        BrokerErrorCode,
        BrokerRequest,
        BrokerResponse,
        ProtocolError,
        decode_request,
        encode_response,
        validate_token,
    )
    from gmail_broker_state import (
        BrokerState,
        BrokerStateStore,
        LifetimeFileLock,
        SanitizedRotatingLogger,
        apply_windows_acl,
        default_broker_paths,
    )
    from gmail_edge_common import (
        APP_SCRIPT_URL,
        AuthState,
        build_action_url,
        classify_response,
        validate_profile_path,
    )
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


QUEUE_WAIT_TIMEOUT_SECONDS = 300
EXECUTION_TIMEOUT_SECONDS = 60
CLIENT_TIMEOUT_SECONDS = 370
FRAME_READ_TIMEOUT_SECONDS = 5
LOGIN_TIMEOUT_SECONDS = 330
CONNECTION_DRAIN_TIMEOUT_SECONDS = 370
IDLE_TIMEOUT_SECONDS = 2 * 60 * 60
NAVIGATION_TIMEOUT_MS = 30_000
APP_RESPONSE_TIMEOUT_MS = 30_000
INTERACTIVE_LOGIN_TIMEOUT_SECONDS = 300
LOGIN_POLL_INTERVAL_MS = 1_000
LOGIN_VERIFY_QUERY = "subject:__avaya_gmail_edge_broker_verify__"

_SAFE_READ_METHODS = frozenset({"gmail_search", "gmail_read"})
_GMAIL_METHODS = _SAFE_READ_METHODS | {"gmail_send"}
_AUTH_REQUIRED_STATES = frozenset(
    {
        AuthState.AUTH_REQUIRED_MICROSOFT,
        AuthState.AUTH_REQUIRED_GOOGLE,
    }
)
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class BrowserAdapter(Protocol):
    """Browser ownership seam implemented by Managed Edge or a test fake."""

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def execute(self, method: str, params: dict[str, str]) -> str: ...

    async def interactive_login(self) -> AuthState: ...


class BrowserAdapterError(RuntimeError):
    """The browser process or automation transport failed."""


class BrowserLoginError(BrowserAdapterError):
    """Interactive login failed after headless Edge was restored successfully."""


class BrowserApplicationError(RuntimeError):
    """The Apps Script application returned an unusable response."""


class BrowserAuthRequired(RuntimeError):
    """The browser reached an enterprise or Google authentication page."""

    def __init__(self, state: AuthState, message: str = "Authentication required") -> None:
        if state not in _AUTH_REQUIRED_STATES:
            raise ValueError("state must be a supported authentication-required state")
        self.state = state
        super().__init__(message)


class ManagedEdgeAdapter:
    """Own one persistent Managed Edge context for broker browser operations."""

    def __init__(
        self,
        profile_dir: Path | str | None = None,
        *,
        user_home: Path | str | None = None,
        playwright_factory: Callable[[], Any] = async_playwright,
        app_script_url: str = APP_SCRIPT_URL,
        navigation_timeout_ms: int = NAVIGATION_TIMEOUT_MS,
        response_timeout_ms: int = APP_RESPONSE_TIMEOUT_MS,
        login_timeout_seconds: float = INTERACTIVE_LOGIN_TIMEOUT_SECONDS,
        login_poll_interval_ms: int = LOGIN_POLL_INTERVAL_MS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        home = Path(
            user_home
            if user_home is not None
            else os.environ.get("USERPROFILE", Path.home())
        )
        selected_profile = Path(
            profile_dir
            if profile_dir is not None
            else home / ".gemini/tools/gmail/edge_broker_profile"
        )
        self.profile_dir = validate_profile_path(selected_profile, home)
        if not callable(playwright_factory):
            raise TypeError("playwright_factory must be callable")
        if not isinstance(app_script_url, str) or not app_script_url:
            raise ValueError("app_script_url must be a non-empty string")
        if type(navigation_timeout_ms) is not int or navigation_timeout_ms <= 0:
            raise ValueError("navigation_timeout_ms must be a positive integer")
        if type(response_timeout_ms) is not int or response_timeout_ms <= 0:
            raise ValueError("response_timeout_ms must be a positive integer")
        if type(login_poll_interval_ms) is not int or login_poll_interval_ms <= 0:
            raise ValueError("login_poll_interval_ms must be a positive integer")
        if not callable(clock):
            raise TypeError("clock must be callable")

        self._playwright_factory = playwright_factory
        self._app_script_url = app_script_url
        self._navigation_timeout_ms = navigation_timeout_ms
        self._response_timeout_ms = response_timeout_ms
        self._login_timeout_seconds = _positive_timeout(
            "login_timeout_seconds", login_timeout_seconds
        )
        self._login_poll_interval_ms = login_poll_interval_ms
        self._clock = clock
        self._playwright: Any | None = None
        self._context: Any | None = None

    async def start(self) -> None:
        if self._context is not None:
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._playwright = await self._playwright_factory().start()
            self._context = await self._launch_context(headless=True)
        except asyncio.CancelledError:
            await self._close_resources()
            raise
        except Exception as exc:
            await self._close_resources()
            raise BrowserAdapterError("Unable to start Managed Edge") from exc

    async def close(self) -> None:
        await self._close_resources()

    async def execute(self, method: str, params: dict[str, str]) -> str:
        context = self._context
        if context is None:
            raise BrowserAdapterError("Managed Edge is not started")
        url = self._build_method_url(method, params)
        page = None
        try:
            page = await context.new_page()
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self._navigation_timeout_ms,
            )
            http_status = response.status if response is not None else None
            early_state = classify_response(page.url, http_status, "")
            self._raise_for_state(early_state)
            try:
                await page.wait_for_load_state(
                    "networkidle",
                    timeout=self._response_timeout_ms,
                )
            except PlaywrightTimeoutError:
                pass
            body = (await page.text_content("body") or "").strip()
            state = classify_response(page.url, http_status, body)
            self._raise_for_state(state)
            if state is not AuthState.AUTHENTICATED:
                raise BrowserApplicationError(
                    "Apps Script returned an unrecognized response"
                )
            return body
        except (BrowserAuthRequired, BrowserApplicationError):
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise BrowserAdapterError("Managed Edge request failed") from exc
        finally:
            if page is not None:
                with contextlib.suppress(Exception):
                    await page.close()

    async def interactive_login(self) -> AuthState:
        if self._context is None or self._playwright is None:
            raise BrowserAdapterError("Managed Edge is not started")

        headless_context = self._context
        self._context = None
        with contextlib.suppress(Exception):
            await headless_context.close()

        headful_context = None
        page = None
        pending_error: BaseException | None = None
        result: AuthState | None = None
        headless_restored = False
        try:
            headful_context = await self._launch_context(headless=False)
            page = await headful_context.new_page()
            response = await page.goto(
                self._verification_url(),
                wait_until="domcontentloaded",
                timeout=self._navigation_timeout_ms,
            )
            http_status = response.status if response is not None else None
            result = await self._poll_interactive_login(page, http_status)
        except asyncio.CancelledError as exc:
            pending_error = exc
        except (BrowserAuthRequired, BrowserApplicationError, BrowserAdapterError) as exc:
            pending_error = exc
        except Exception as exc:
            pending_error = BrowserAdapterError(
                "Managed Edge interactive login failed"
            )
            pending_error.__cause__ = exc
        finally:
            if headful_context is not None:
                with contextlib.suppress(Exception):
                    await headful_context.close()
            try:
                self._context = await self._launch_context(headless=True)
                headless_restored = True
            except asyncio.CancelledError as exc:
                pending_error = exc
            except Exception as exc:
                pending_error = BrowserAdapterError(
                    "Unable to restore headless Managed Edge"
                )
                pending_error.__cause__ = exc

        if pending_error is not None:
            if headless_restored and isinstance(pending_error, BrowserAdapterError):
                raise BrowserLoginError(
                    "Managed Edge interactive login failed after headless restore"
                ) from pending_error
            raise pending_error
        if result is not AuthState.AUTHENTICATED:
            raise BrowserApplicationError(
                "Interactive Gmail login could not be verified"
            )
        return result

    async def _poll_interactive_login(
        self,
        page: Any,
        http_status: int | None,
    ) -> AuthState:
        deadline = float(self._clock()) + self._login_timeout_seconds
        state = classify_response(page.url, http_status, "")
        while float(self._clock()) < deadline:
            if page.is_closed():
                raise BrowserAdapterError("Managed Edge login window was closed")
            try:
                body = (await page.text_content("body") or "").strip()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if page.is_closed():
                    raise BrowserAdapterError(
                        "Managed Edge login window was closed"
                    ) from exc
                await page.wait_for_timeout(self._login_poll_interval_ms)
                continue
            state = classify_response(page.url, http_status, body)
            if state is AuthState.AUTHENTICATED:
                return state
            if state is AuthState.APP_ERROR:
                raise BrowserApplicationError(
                    "Apps Script could not verify interactive login"
                )
            await page.wait_for_timeout(self._login_poll_interval_ms)

        if state in _AUTH_REQUIRED_STATES:
            raise BrowserAuthRequired(state)
        if page.is_closed():
            raise BrowserAdapterError("Managed Edge login window was closed")
        raise BrowserApplicationError("Interactive Gmail login timed out")

    async def _launch_context(self, *, headless: bool) -> Any:
        if self._playwright is None:
            raise BrowserAdapterError("Playwright is not started")
        return await self._playwright.chromium.launch_persistent_context(
            channel="msedge",
            user_data_dir=str(self.profile_dir),
            headless=headless,
        )

    async def _close_resources(self) -> None:
        context = self._context
        playwright = self._playwright
        self._context = None
        self._playwright = None
        if context is not None:
            with contextlib.suppress(Exception):
                await context.close()
        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()

    def _verification_url(self) -> str:
        return build_action_url(
            "search",
            {"q": LOGIN_VERIFY_QUERY},
            base_url=self._app_script_url,
        )

    def _build_method_url(self, method: str, params: dict[str, str]) -> str:
        if not isinstance(params, dict):
            raise BrowserApplicationError("Gmail request parameters are invalid")
        if method == "gmail_search":
            action = "search"
            mapped = {"q": self._required_string(params, "query")}
        elif method == "gmail_read":
            action = "read"
            mapped = {"id": self._required_string(params, "message_id")}
        elif method == "gmail_send":
            action = "send"
            mapped = {
                "to": self._required_string(params, "to"),
                "subject": self._required_string(params, "subject"),
                "body": self._required_string(params, "body"),
            }
        else:
            raise BrowserApplicationError("Unsupported Gmail browser method")
        return build_action_url(action, mapped, base_url=self._app_script_url)

    @staticmethod
    def _required_string(params: dict[str, str], name: str) -> str:
        value = params.get(name)
        if not isinstance(value, str):
            raise BrowserApplicationError("Gmail request parameters are invalid")
        return value

    @staticmethod
    def _raise_for_state(state: AuthState) -> None:
        if state in _AUTH_REQUIRED_STATES:
            raise BrowserAuthRequired(state)
        if state is AuthState.APP_ERROR:
            raise BrowserApplicationError("Apps Script returned an error")


class _RequestFailure(RuntimeError):
    def __init__(self, code: BrokerErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _positive_timeout(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


class GmailEdgeBroker:
    """Own one adapter and serialize all browser work across loopback clients."""

    def __init__(
        self,
        adapter: BrowserAdapter,
        *,
        state_store: BrokerStateStore | None = None,
        owner_lock: LifetimeFileLock | None = None,
        logger: SanitizedRotatingLogger | None = None,
        logger_factory: Callable[[Path], SanitizedRotatingLogger] | None = None,
        build_id: str = "source",
        instance_id: str | None = None,
        token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        queue_wait_timeout: float = QUEUE_WAIT_TIMEOUT_SECONDS,
        execution_timeout: float = EXECUTION_TIMEOUT_SECONDS,
        frame_read_timeout: float = FRAME_READ_TIMEOUT_SECONDS,
        login_timeout: float = LOGIN_TIMEOUT_SECONDS,
        connection_drain_timeout: float = CONNECTION_DRAIN_TIMEOUT_SECONDS,
        idle_timeout: float = IDLE_TIMEOUT_SECONDS,
        idle_check_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(build_id, str) or not build_id:
            raise ValueError("build_id must be a non-empty string")
        if instance_id is not None and (
            not isinstance(instance_id, str) or not instance_id
        ):
            raise ValueError("instance_id must be a non-empty string")
        if token is not None and (not isinstance(token, str) or not token):
            raise ValueError("token must be a non-empty string")
        if host != "127.0.0.1":
            raise ValueError("broker host must be 127.0.0.1")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if not callable(clock):
            raise TypeError("clock must be callable")

        self.adapter = adapter
        self.state_store = state_store or BrokerStateStore()
        self.owner_lock = owner_lock or LifetimeFileLock(
            self.state_store.paths.broker_lock_file
        )
        self.logger = logger
        self._logger_factory = logger_factory
        self.build_id = build_id
        self.instance_id = instance_id or str(uuid.uuid4())
        self.token = token or secrets.token_urlsafe(32)
        self.host = host
        self.port = port
        self.queue_wait_timeout = _positive_timeout(
            "queue_wait_timeout", queue_wait_timeout
        )
        self.execution_timeout = _positive_timeout(
            "execution_timeout", execution_timeout
        )
        self.frame_read_timeout = _positive_timeout(
            "frame_read_timeout", frame_read_timeout
        )
        self.login_timeout = _positive_timeout(
            "login_timeout", login_timeout
        )
        self.connection_drain_timeout = _positive_timeout(
            "connection_drain_timeout", connection_drain_timeout
        )
        self.idle_timeout = _positive_timeout("idle_timeout", idle_timeout)
        self.idle_check_interval = _positive_timeout(
            "idle_check_interval", idle_check_interval
        )
        self._clock = clock

        self._server: asyncio.AbstractServer | None = None
        self._operation_lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()
        self._idle_task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._running = False
        self._stopping = False
        self._browser_started = False
        self._login_in_progress = False
        self._queue_depth = 0
        self._active_requests = 0
        self._request_count = 0
        self._browser_start_count = 0
        self._browser_crash_count = 0
        self._current_browser_concurrency = 0
        self._max_browser_concurrency = 0
        self._started_at: float | None = None
        self._last_completed_at = 0.0
        self._connection_tasks: set[asyncio.Task[None]] = set()
        self._connection_writers: set[asyncio.StreamWriter] = set()

    @property
    def address(self) -> tuple[str, int]:
        server = self._server
        if server is None or not server.sockets:
            raise RuntimeError("broker is not listening")
        host, port = server.sockets[0].getsockname()[:2]
        return str(host), int(port)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def queue_depth(self) -> int:
        return self._queue_depth

    async def start(self) -> tuple[str, int]:
        """Acquire ownership, bind loopback port zero, and publish state."""

        if self._running:
            raise RuntimeError("broker is already running")
        if self._stopped.is_set():
            raise RuntimeError("a stopped broker instance cannot be restarted")

        try:
            self.owner_lock.acquire()
            if self.logger is None:
                if self._logger_factory is None:
                    self.logger = SanitizedRotatingLogger(
                        self.state_store.paths.log_file
                    )
                else:
                    self.logger = self._logger_factory(
                        self.state_store.paths.log_file
                    )
            self._server = await asyncio.start_server(
                self._handle_connection,
                self.host,
                self.port,
                limit=MAX_FRAME_BYTES + 1,
            )
            host, port = self.address
            state = BrokerState(
                protocol_version=PROTOCOL_VERSION,
                build_id=self.build_id,
                instance_id=self.instance_id,
                pid=os.getpid(),
                host=host,
                port=port,
                token=self.token,
                started_at=_utc_timestamp(),
            )
            self.state_store.write(state)
            now = float(self._clock())
            self._started_at = now
            self._last_completed_at = now
            self._running = True
            self._stopping = False
            self._idle_task = asyncio.create_task(
                self._idle_watch(),
                name=f"gmail-edge-broker-idle-{self.instance_id}",
            )
            self._safe_log(
                "info",
                "broker_started",
                result_code="OK",
                **self._counter_fields(),
            )
            return host, port
        except BaseException:
            self._running = False
            if self._idle_task is not None:
                self._idle_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._idle_task
                self._idle_task = None
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
                self._server = None
            if self.owner_lock.is_acquired:
                with contextlib.suppress(Exception):
                    self.state_store.cleanup(
                        self.instance_id,
                        owner_lock=self.owner_lock,
                    )
                self.owner_lock.release()
            if self.logger is not None:
                self.logger.close()
            self._stopped.set()
            raise

    async def stop(self) -> None:
        """Close browser before instance-owned state cleanup and lock release."""

        async with self._stop_lock:
            if self._stopped.is_set():
                return
            self._running = False
            self._stopping = True
            first_error: BaseException | None = None

            if self._server is not None:
                self._server.close()

            current_task = asyncio.current_task()
            if self._idle_task is not None and self._idle_task is not current_task:
                self._idle_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._idle_task
            self._idle_task = None

            current_task = asyncio.current_task()
            pending_connections = [
                task
                for task in self._connection_tasks
                if task is not current_task and not task.done()
            ]
            if pending_connections:
                done, pending = await asyncio.wait(
                    pending_connections,
                    timeout=self.connection_drain_timeout,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(
                        *pending,
                        return_exceptions=True,
                    )

            if self._server is not None:
                await self._server.wait_closed()
                self._server = None

            await self._operation_lock.acquire()
            try:
                if self._browser_started:
                    try:
                        await self.adapter.close()
                    except BaseException as exc:
                        first_error = exc
                    finally:
                        self._browser_started = False
            finally:
                self._operation_lock.release()
            self._edge_state = "STOPPED"

            if self.owner_lock.is_acquired:
                try:
                    self.state_store.cleanup(
                        self.instance_id,
                        owner_lock=self.owner_lock,
                    )
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
                finally:
                    try:
                        self.owner_lock.release()
                    except BaseException as exc:
                        if first_error is None:
                            first_error = exc

            try:
                self._safe_log(
                    "info",
                    "broker_stopped",
                    result_code="OK" if first_error is None else "APP_ERROR",
                    **self._counter_fields(),
                )
            finally:
                if self.logger is not None:
                    with contextlib.suppress(Exception):
                        self.logger.close()
                self._stopped.set()

            if first_error is not None:
                raise first_error

    async def wait_stopped(self) -> None:
        await self._stopped.wait()

    def diagnostics(self) -> dict[str, object]:
        """Return the finite public health/diagnostic contract."""

        return {
            "protocol_version": PROTOCOL_VERSION,
            "pid": os.getpid(),
            "edge_state": getattr(self, "_edge_state", "STARTING"),
            "queue_depth": self._queue_depth,
            "request_count": self._request_count,
            "browser_start_count": self._browser_start_count,
            "browser_crash_count": self._browser_crash_count,
            "current_browser_concurrency": self._current_browser_concurrency,
            "max_browser_concurrency": self._max_browser_concurrency,
            "build_id": self.build_id,
            "instance_id": self.instance_id,
            "uptime_seconds": self._uptime_seconds(),
        }

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._connection_tasks.add(task)
        self._connection_writers.add(writer)
        request: BrokerRequest | None = None
        response: BrokerResponse
        shutdown_after_response = False
        try:
            if not self._is_loopback(writer):
                raise ProtocolError(
                    BrokerErrorCode.INVALID_REQUEST,
                    "Broker accepts loopback connections only",
                )
            frame = await asyncio.wait_for(
                reader.readline(),
                timeout=self.frame_read_timeout,
            )
            if not frame:
                raise ProtocolError(
                    BrokerErrorCode.INVALID_REQUEST,
                    "Request frame is empty",
                )
            request = decode_request(frame)
            if not validate_token(request.token, self.token):
                response = BrokerResponse.failure(
                    request.id,
                    BrokerErrorCode.INVALID_REQUEST,
                    "Broker authentication failed",
                )
                self._log_rejected(request, BrokerErrorCode.INVALID_REQUEST)
            else:
                response = await self._dispatch(request)
                shutdown_after_response = request.method == "shutdown" and response.ok
        except (
            ProtocolError,
            asyncio.LimitOverrunError,
            asyncio.TimeoutError,
            ValueError,
        ):
            response = BrokerResponse.failure(
                "invalid-request",
                BrokerErrorCode.INVALID_REQUEST,
                "Invalid broker request",
            )
            self._log_rejected(None, BrokerErrorCode.INVALID_REQUEST)
        except asyncio.CancelledError:
            raise
        except Exception:
            response = BrokerResponse.failure(
                request.id if request is not None else "invalid-request",
                BrokerErrorCode.APP_ERROR,
                "Broker request handling failed",
            )
            self._log_rejected(request, BrokerErrorCode.APP_ERROR)

        encoded = self._encode_safely(response)
        try:
            writer.write(encoded)
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            self._connection_writers.discard(writer)
            if task is not None:
                self._connection_tasks.discard(task)
        if shutdown_after_response:
            asyncio.create_task(self.stop())

    async def _dispatch(self, request: BrokerRequest) -> BrokerResponse:
        started = float(self._clock())
        queue_wait_ms = 0
        self._active_requests += 1
        if request.method != "health":
            self._request_count += 1
        try:
            if self._stopping and request.method != "health":
                response = BrokerResponse.failure(
                    request.id,
                    BrokerErrorCode.APP_ERROR,
                    "Broker is stopping",
                )
            elif request.method == "health":
                response = BrokerResponse.success(request.id, self.diagnostics())
            elif request.method == "shutdown":
                response = BrokerResponse.success(request.id, {"stopping": True})
            elif self._login_in_progress and request.method in _GMAIL_METHODS:
                response = BrokerResponse.failure(
                    request.id,
                    BrokerErrorCode.LOGIN_IN_PROGRESS,
                    "Interactive Gmail login is in progress",
                )
            else:
                response, queue_wait_ms = await self._dispatch_serialized(request)
            return response
        finally:
            self._active_requests -= 1
            self._last_completed_at = float(self._clock())
            elapsed_ms = self._elapsed_ms(started)
            response_for_log = locals().get("response")
            result_code = (
                "APP_ERROR"
                if not isinstance(response_for_log, BrokerResponse)
                else self._result_code(response_for_log)
            )
            self._log_finished(
                request,
                result_code=result_code,
                elapsed_ms=elapsed_ms,
                queue_wait_ms=queue_wait_ms,
            )

    async def _dispatch_serialized(
        self,
        request: BrokerRequest,
    ) -> tuple[BrokerResponse, int]:
        previous_state: str | None = None
        if request.method == "auth_login":
            if self._login_in_progress:
                return (
                    BrokerResponse.failure(
                        request.id,
                        BrokerErrorCode.LOGIN_IN_PROGRESS,
                        "Interactive Gmail login is already in progress",
                    ),
                    0,
                )
            self._login_in_progress = True
            previous_state = getattr(self, "_edge_state", "STARTING")
            self._edge_state = "LOGIN_IN_PROGRESS"

        queue_started = float(self._clock())
        self._queue_depth += 1
        acquired = False
        try:
            try:
                await asyncio.wait_for(
                    self._operation_lock.acquire(),
                    timeout=self.queue_wait_timeout,
                )
                acquired = True
            except asyncio.TimeoutError:
                queue_wait_ms = self._elapsed_ms(queue_started)
                return (
                    BrokerResponse.failure(
                        request.id,
                        BrokerErrorCode.REQUEST_TIMEOUT,
                        "Broker queue wait timed out",
                    ),
                    queue_wait_ms,
                )
            finally:
                self._queue_depth -= 1

            queue_wait_ms = self._elapsed_ms(queue_started)
            try:
                operation_timeout = (
                    self.login_timeout
                    if request.method == "auth_login"
                    else self.execution_timeout
                )
                result = await asyncio.wait_for(
                    self._perform(request),
                    timeout=operation_timeout,
                )
                return BrokerResponse.success(request.id, result), queue_wait_ms
            except asyncio.TimeoutError:
                return (
                    BrokerResponse.failure(
                        request.id,
                        BrokerErrorCode.REQUEST_TIMEOUT,
                        "Browser execution timed out",
                    ),
                    queue_wait_ms,
                )
            except _RequestFailure as exc:
                return (
                    BrokerResponse.failure(request.id, exc.code, str(exc)),
                    queue_wait_ms,
                )
        finally:
            if acquired:
                self._operation_lock.release()
            if request.method == "auth_login":
                self._login_in_progress = False
                if getattr(self, "_edge_state", None) == "LOGIN_IN_PROGRESS":
                    self._edge_state = previous_state or "STARTING"

    async def _perform(self, request: BrokerRequest) -> Any:
        self._current_browser_concurrency += 1
        self._max_browser_concurrency = max(
            self._max_browser_concurrency,
            self._current_browser_concurrency,
        )
        try:
            if request.method == "auth_login":
                return await self._perform_login()
            return await self._perform_gmail(request.method, request.params)
        finally:
            self._current_browser_concurrency -= 1

    async def _perform_gmail(self, method: str, params: dict[str, Any]) -> str:
        attempts = 2 if method in _SAFE_READ_METHODS else 1
        for attempt in range(attempts):
            try:
                await self._ensure_browser_started()
                result = await self.adapter.execute(method, params)
            except BrowserAuthRequired as exc:
                self._edge_state = exc.state.value
                raise _RequestFailure(
                    BrokerErrorCode.AUTH_REQUIRED,
                    "Interactive Gmail authentication is required",
                ) from exc
            except BrowserApplicationError as exc:
                self._edge_state = AuthState.APP_ERROR.value
                raise _RequestFailure(
                    BrokerErrorCode.APP_ERROR,
                    "Gmail application request failed",
                ) from exc
            except BrowserAdapterError as exc:
                self._browser_crash_count += 1
                self._edge_state = AuthState.BROWSER_ERROR.value
                await self._discard_browser()
                if attempt + 1 < attempts:
                    continue
                raise _RequestFailure(
                    BrokerErrorCode.BROWSER_ERROR,
                    "Managed Edge browser request failed",
                ) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._edge_state = AuthState.APP_ERROR.value
                raise _RequestFailure(
                    BrokerErrorCode.APP_ERROR,
                    "Gmail broker operation failed",
                ) from exc
            self._edge_state = AuthState.AUTHENTICATED.value
            return result
        raise AssertionError("browser attempt loop exhausted")

    async def _perform_login(self) -> dict[str, str]:
        try:
            await self._ensure_browser_started()
            state = await self.adapter.interactive_login()
        except BrowserAuthRequired as exc:
            self._edge_state = exc.state.value
            raise _RequestFailure(
                BrokerErrorCode.AUTH_REQUIRED,
                "Interactive Gmail authentication is still required",
            ) from exc
        except BrowserApplicationError as exc:
            self._edge_state = AuthState.APP_ERROR.value
            raise _RequestFailure(
                BrokerErrorCode.APP_ERROR,
                "Interactive Gmail login could not be verified",
            ) from exc
        except BrowserLoginError as exc:
            self._browser_crash_count += 1
            self._edge_state = AuthState.BROWSER_ERROR.value
            raise _RequestFailure(
                BrokerErrorCode.BROWSER_ERROR,
                "Managed Edge interactive login failed",
            ) from exc
        except BrowserAdapterError as exc:
            self._browser_crash_count += 1
            self._edge_state = AuthState.BROWSER_ERROR.value
            await self._discard_browser()
            raise _RequestFailure(
                BrokerErrorCode.BROWSER_ERROR,
                "Managed Edge interactive login failed",
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._edge_state = AuthState.APP_ERROR.value
            raise _RequestFailure(
                BrokerErrorCode.APP_ERROR,
                "Interactive Gmail login failed",
            ) from exc

        if not isinstance(state, AuthState):
            self._edge_state = AuthState.APP_ERROR.value
            raise _RequestFailure(
                BrokerErrorCode.APP_ERROR,
                "Interactive Gmail login returned an invalid state",
            )
        self._edge_state = state.value
        if state in _AUTH_REQUIRED_STATES:
            raise _RequestFailure(
                BrokerErrorCode.AUTH_REQUIRED,
                "Interactive Gmail authentication is still required",
            )
        if state is AuthState.BROWSER_ERROR:
            raise _RequestFailure(
                BrokerErrorCode.BROWSER_ERROR,
                "Managed Edge interactive login failed",
            )
        if state is not AuthState.AUTHENTICATED:
            raise _RequestFailure(
                BrokerErrorCode.APP_ERROR,
                "Interactive Gmail login could not be verified",
            )

        try:
            await self.adapter.execute(
                "gmail_search",
                {"query": LOGIN_VERIFY_QUERY},
            )
        except BrowserAuthRequired as exc:
            self._edge_state = exc.state.value
            raise _RequestFailure(
                BrokerErrorCode.AUTH_REQUIRED,
                "Interactive Gmail authentication is still required",
            ) from exc
        except BrowserApplicationError as exc:
            self._edge_state = AuthState.APP_ERROR.value
            raise _RequestFailure(
                BrokerErrorCode.APP_ERROR,
                "Interactive Gmail login verification failed",
            ) from exc
        except BrowserAdapterError as exc:
            self._browser_crash_count += 1
            self._edge_state = AuthState.BROWSER_ERROR.value
            await self._discard_browser()
            raise _RequestFailure(
                BrokerErrorCode.BROWSER_ERROR,
                "Managed Edge login verification failed",
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._edge_state = AuthState.APP_ERROR.value
            raise _RequestFailure(
                BrokerErrorCode.APP_ERROR,
                "Interactive Gmail login verification failed",
            ) from exc
        self._edge_state = AuthState.AUTHENTICATED.value
        return {"state": state.value}

    async def _ensure_browser_started(self) -> None:
        if self._browser_started:
            return
        await self.adapter.start()
        self._browser_started = True
        self._browser_start_count += 1

    async def _discard_browser(self) -> None:
        if not self._browser_started:
            return
        try:
            await self.adapter.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            self._browser_started = False

    async def _idle_watch(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.idle_check_interval)
                idle_for = float(self._clock()) - self._last_completed_at
                if self._active_requests == 0 and idle_for >= self.idle_timeout:
                    await self.stop()
                    return
        except asyncio.CancelledError:
            raise

    def _counter_fields(self) -> dict[str, int]:
        return {
            "request_count": self._request_count,
            "browser_start_count": self._browser_start_count,
            "browser_crash_count": self._browser_crash_count,
            "current_browser_concurrency": self._current_browser_concurrency,
            "max_browser_concurrency": self._max_browser_concurrency,
            "uptime_seconds": self._uptime_seconds(),
        }

    def _uptime_seconds(self) -> int:
        if self._started_at is None:
            return 0
        return max(0, int(float(self._clock()) - self._started_at))

    def _elapsed_ms(self, started: float) -> int:
        return max(0, int((float(self._clock()) - started) * 1000))

    def _log_finished(
        self,
        request: BrokerRequest,
        *,
        result_code: str,
        elapsed_ms: int,
        queue_wait_ms: int,
    ) -> None:
        fields: dict[str, object] = {
            "method": request.method,
            "result_code": result_code,
            "elapsed_ms": elapsed_ms,
            "queue_wait_ms": queue_wait_ms,
            "queue_depth": self._queue_depth,
            **self._counter_fields(),
        }
        if _SAFE_REQUEST_ID.fullmatch(request.id) is not None:
            fields["request_id"] = request.id
        if self.logger is not None:
            self._safe_log("info", "request_finished", **fields)

    def _log_rejected(
        self,
        request: BrokerRequest | None,
        code: BrokerErrorCode,
    ) -> None:
        fields: dict[str, object] = {
            "result_code": code.value,
            **self._counter_fields(),
        }
        if request is not None:
            fields["method"] = request.method
            if _SAFE_REQUEST_ID.fullmatch(request.id) is not None:
                fields["request_id"] = request.id
        if self.logger is not None:
            self._safe_log("warning", "request_rejected", **fields)

    def _safe_log(
        self,
        level: str,
        event: str,
        **fields: object,
    ) -> None:
        logger = self.logger
        if logger is None:
            return
        try:
            getattr(logger, level)(event, **fields)
        except Exception:
            # Broker logging must never make Gmail delivery ambiguous.
            return

    @staticmethod
    def _result_code(response: BrokerResponse) -> str:
        if response.ok:
            return "OK"
        assert response.error is not None
        return response.error.code.value

    @staticmethod
    def _encode_safely(response: BrokerResponse) -> bytes:
        try:
            return encode_response(response)
        except ProtocolError as exc:
            return encode_response(
                BrokerResponse.failure(response.id, exc.code, str(exc))
            )

    @staticmethod
    def _is_loopback(writer: asyncio.StreamWriter) -> bool:
        peer = writer.get_extra_info("peername")
        if not isinstance(peer, tuple) or not peer:
            return False
        try:
            return ipaddress.ip_address(peer[0]).is_loopback
        except ValueError:
            return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the per-user Managed Edge Gmail broker.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("serve",),
        default="serve",
        help="serve authenticated loopback requests (default: serve)",
    )
    return parser


async def _serve() -> int:
    adapter = ManagedEdgeAdapter()
    paths = default_broker_paths()
    paths.directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        apply_windows_acl(paths.directory)
    state_store = BrokerStateStore(paths.directory, acl_applier=None)
    owner_lock = LifetimeFileLock(
        paths.broker_lock_file,
        acl_applier=None,
    )
    broker = GmailEdgeBroker(
        adapter,
        state_store=state_store,
        owner_lock=owner_lock,
        logger_factory=lambda path: SanitizedRotatingLogger(
            path,
            acl_applier=None,
        ),
    )
    await broker.start()
    try:
        await broker.wait_stopped()
    finally:
        await broker.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "serve":
        raise AssertionError("unreachable broker command")
    try:
        return asyncio.run(_serve())
    except KeyboardInterrupt:
        return 130


__all__ = [
    "APP_RESPONSE_TIMEOUT_MS",
    "CLIENT_TIMEOUT_SECONDS",
    "CONNECTION_DRAIN_TIMEOUT_SECONDS",
    "EXECUTION_TIMEOUT_SECONDS",
    "FRAME_READ_TIMEOUT_SECONDS",
    "IDLE_TIMEOUT_SECONDS",
    "INTERACTIVE_LOGIN_TIMEOUT_SECONDS",
    "LOGIN_POLL_INTERVAL_MS",
    "LOGIN_TIMEOUT_SECONDS",
    "LOGIN_VERIFY_QUERY",
    "NAVIGATION_TIMEOUT_MS",
    "QUEUE_WAIT_TIMEOUT_SECONDS",
    "BrowserAdapter",
    "BrowserAdapterError",
    "BrowserApplicationError",
    "BrowserAuthRequired",
    "BrowserLoginError",
    "GmailEdgeBroker",
    "ManagedEdgeAdapter",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
