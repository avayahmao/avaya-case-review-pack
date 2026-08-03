"""Serialized, authenticated loopback broker for one Managed Edge owner."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
import ipaddress
import os
import re
import secrets
import time
import uuid
from typing import Any, Callable, Protocol

from tools.gmail.gmail_broker_protocol import (
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
from tools.gmail.gmail_broker_state import (
    BrokerState,
    BrokerStateStore,
    LifetimeFileLock,
    SanitizedRotatingLogger,
)
from tools.gmail.gmail_edge_common import AuthState


QUEUE_WAIT_TIMEOUT_SECONDS = 300
EXECUTION_TIMEOUT_SECONDS = 60
CLIENT_TIMEOUT_SECONDS = 370
IDLE_TIMEOUT_SECONDS = 2 * 60 * 60

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


class BrowserApplicationError(RuntimeError):
    """The Apps Script application returned an unusable response."""


class BrowserAuthRequired(RuntimeError):
    """The browser reached an enterprise or Google authentication page."""

    def __init__(self, state: AuthState, message: str = "Authentication required") -> None:
        if state not in _AUTH_REQUIRED_STATES:
            raise ValueError("state must be a supported authentication-required state")
        self.state = state
        super().__init__(message)


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
        build_id: str = "source",
        instance_id: str | None = None,
        token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        queue_wait_timeout: float = QUEUE_WAIT_TIMEOUT_SECONDS,
        execution_timeout: float = EXECUTION_TIMEOUT_SECONDS,
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
                self.logger = SanitizedRotatingLogger(
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
            self._idle_task = asyncio.create_task(
                self._idle_watch(),
                name=f"gmail-edge-broker-idle-{self.instance_id}",
            )
            assert self.logger is not None
            self.logger.info(
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
            first_error: BaseException | None = None

            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
                self._server = None

            current_task = asyncio.current_task()
            if self._idle_task is not None and self._idle_task is not current_task:
                self._idle_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._idle_task
            self._idle_task = None

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
                if self.logger is not None:
                    self.logger.info(
                        "broker_stopped",
                        result_code="OK" if first_error is None else "APP_ERROR",
                        **self._counter_fields(),
                    )
            finally:
                if self.logger is not None:
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
        request: BrokerRequest | None = None
        response: BrokerResponse
        shutdown_after_response = False
        try:
            if not self._is_loopback(writer):
                raise ProtocolError(
                    BrokerErrorCode.INVALID_REQUEST,
                    "Broker accepts loopback connections only",
                )
            frame = await reader.readline()
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
        except (ProtocolError, asyncio.LimitOverrunError, ValueError):
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
        if shutdown_after_response:
            asyncio.create_task(self.stop())

    async def _dispatch(self, request: BrokerRequest) -> BrokerResponse:
        started = float(self._clock())
        queue_wait_ms = 0
        self._active_requests += 1
        if request.method != "health":
            self._request_count += 1
        try:
            if request.method == "health":
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
                result = await asyncio.wait_for(
                    self._perform(request),
                    timeout=self.execution_timeout,
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
            self.logger.info("request_finished", **fields)

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
            self.logger.warning("request_rejected", **fields)

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


__all__ = [
    "CLIENT_TIMEOUT_SECONDS",
    "EXECUTION_TIMEOUT_SECONDS",
    "IDLE_TIMEOUT_SECONDS",
    "QUEUE_WAIT_TIMEOUT_SECONDS",
    "BrowserAdapter",
    "BrowserAdapterError",
    "BrowserApplicationError",
    "BrowserAuthRequired",
    "GmailEdgeBroker",
]
