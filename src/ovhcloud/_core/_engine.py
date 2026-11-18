# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The machinery behind Client and AsyncClient: build, authenticate, send, retry, log,
decode."""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import itertools
import time
import typing as t

import httpx

from . import _debug
from ._auth import AsyncTokenSource, TokenSource
from ._errors import (
    DecodeError,
    DryRunError,
    HookRefusedError,
    InvalidRequestError,
    RequestTimeoutError,
    ResponseTooLargeError,
    TransportError,
    api_error_class,
)
from ._hooks import Call, CallInfo, CallResult
from ._models import decode, to_body
from ._pagination import aiterate, iterate
from ._policy import Policy
from ._registry import Operation, is_read_only, match_operation
from ._request import (
    Request,
    build_headers,
    build_query,
    check_header,
    check_path,
    encode_body,
    fill_path,
)
from ._retry import MAX_RETRY_WAIT, RetryPolicy, retry_delay, should_retry
from ._types import NOT_GIVEN, NotGiven

__all__ = ["AsyncEngine", "Engine"]

SCHEMAS_VERSION_HEADER: t.Final = "X-Schemas-Version"

# Headers httpx adds from the URL and the body. A DryRunError leaves them out, as Go's does:
# there, the transport sets them.
_TRANSPORT_HEADERS: t.Final = frozenset({"Host", "Content-Length"})


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _EngineBase:
    """What the sync and async engines share: settings, and every step that does no I/O.
    Frozen: with_options makes a copy."""

    endpoint: str
    user_agent: str
    headers: tuple[tuple[str, str], ...] = ()
    retry: RetryPolicy = dataclasses.field(default_factory=RetryPolicy)
    max_response_bytes: int = 0
    debug: bool = False
    debug_bodies: bool = False
    policy: Policy = dataclasses.field(default_factory=Policy)
    #: Per-request timeout override, set by with_options. NOT_GIVEN: the HTTP client's.
    timeout: httpx.Timeout | NotGiven = NOT_GIVEN
    #: Seconds one attempt may take in all, from sending to the end of the body, like Go's
    #: http.Client.Timeout. None: no limit. httpx only limits each step (connect, each read),
    #: so a server that sends a byte now and then would never time out without it.
    deadline: float | None = None
    #: dry_run=True: send GET and HEAD, refuse anything else with DryRunError.
    dry_run: bool = False
    #: The before_request and after_request hooks. AsyncEngine awaits what they return when
    #: it is awaitable.
    before_request: tuple[t.Callable[[CallInfo], object], ...] = ()
    after_request: tuple[t.Callable[[CallInfo, CallResult], object], ...] = ()

    def operation_request(
        self,
        op: Operation,
        path_params: t.Mapping[str, object] | None,
        query: t.Iterable[tuple[str, object]],
        headers: t.Iterable[tuple[str, object]],
        body: object,
        body_type: object = None,
    ) -> Request:
        """The Request of a generated method. body_type is the type of op's body: prepare
        turns a dict or a list body into it (see to_body)."""
        return Request(
            method=op.method,
            path=fill_path(op.path, path_params or {}),
            query=tuple(query),
            headers=tuple(headers),
            body=body,
            operation=op,
            schemas_version=op.schemas_version,
            body_type=body_type,
        )

    def prepare(self, req: Request, call: Call) -> tuple[Request, httpx.Request]:
        """Check req (its path, then the policy, then its body) and build its HTTP request,
        with no token yet. The returned Request names the operation the path matched, if
        any. call learns the operation, then the query that is sent."""
        op = req.operation
        if op is None:
            op = match_operation(req.method, req.path)
            call.info = dataclasses.replace(call.info, operation=op)
        # First the path: the policy must check the route that is really sent.
        check_path(req.path, req.method, op)
        self.policy.check(op, req.method, req.path)
        if req.operation is None and op is not None:
            req = dataclasses.replace(req, operation=op)  # the caller's Request is unchanged
        if req.body_type is not None and op is not None:
            req = dataclasses.replace(req, body=to_body(op, req.body_type, req.body))
        request = self.build(req)
        call.info = dataclasses.replace(call.info, query=tuple(request.url.params.multi_items()))
        return req, request

    def hook_refused(self, call: Call, err: Exception) -> HookRefusedError:
        op = call.info.operation
        return HookRefusedError(
            operation=op.name if op is not None else "",
            method=call.info.method,
            path=call.info.path,
            cause=err,
        )

    def check_dry_run(self, req: Request, request: httpx.Request) -> None:
        """In dry-run mode, raise DryRunError for a call that does not only read. The
        credential headers are left out, though sign has not added the token yet: the
        headers option or a request may hold some."""
        if not self.dry_run or is_read_only(req.method):
            return
        headers: dict[str, str] = {}
        for raw_name, raw_value in request.headers.raw:
            name = _debug.canonical_header_key(raw_name.decode("latin-1"))
            if name in _debug.SENSITIVE_HEADERS or name in _TRANSPORT_HEADERS:
                continue
            value = raw_value.decode("latin-1")
            headers[name] = f"{headers[name]}, {value}" if name in headers else value
        raise DryRunError(
            operation=req.operation.name if req.operation is not None else "",
            method=req.method,
            url=str(request.url),
            headers=headers,
            body=None if isinstance(req.body, NotGiven) else request.content,
        )

    @staticmethod
    def saw_response(call: Call, response: httpx.Response) -> None:
        call.status_code = response.status_code
        call.query_id = response.headers.get("X-Ovh-Queryid", "")

    def build(self, req: Request) -> httpx.Request:
        """The HTTP request of req, without its token: sign adds it."""
        path, _, existing = req.path.partition("?")
        query = build_query(existing, req.query)
        url = self.endpoint + path + ("?" + query if query else "")
        try:
            parsed = httpx.URL(url)
        except httpx.InvalidURL as err:
            raise InvalidRequestError(f"path {req.path!r}: {err}") from None

        pairs: list[tuple[str, str]] = [("Accept", "application/json")]
        content: bytes | None = None
        if not isinstance(req.body, NotGiven):
            content = encode_body(req.body)
            pairs.append(("Content-Type", "application/json"))
        pairs.extend(self.headers)
        pairs.extend(build_headers(req.headers))
        if req.schemas_version:
            # Set, not added: the API reads the first value.
            _set(pairs, SCHEMAS_VERSION_HEADER, req.schemas_version)
        # Set last, so neither the client's headers nor a request can replace it.
        _set(pairs, "User-Agent", self.user_agent)
        headers = httpx.Headers(pairs)

        extensions: dict[str, object] = {}
        if not isinstance(self.timeout, NotGiven):
            extensions["timeout"] = self.timeout.as_dict()
        return httpx.Request(
            req.method,
            parsed,
            headers=headers,
            content=content,
            extensions=extensions or None,
        )

    @staticmethod
    def sign(request: httpx.Request, token: str) -> None:
        """Set the Authorization header, last, over any other value."""
        check_header("Authorization", token)
        if "Authorization" in request.headers:
            del request.headers["Authorization"]
        request.headers["Authorization"] = f"Bearer {token}"

    @staticmethod
    def result(
        req: Request, response: httpx.Response, content: bytes
    ) -> tuple[bytes, httpx.Headers]:
        """The body and headers of a 2xx response. Raise ApiError for any other status."""
        if 200 <= response.status_code <= 299:
            return content, response.headers
        cls = api_error_class(response.status_code)
        raise cls(
            method=req.method,
            path=req.path,
            status_code=response.status_code,
            status=f"{response.status_code} {response.reason_phrase}".strip(),
            body=content,
            query_id=response.headers.get("X-Ovh-Queryid", ""),
            schemas_version=response.headers.get(SCHEMAS_VERSION_HEADER, ""),
            operation=req.operation,
        )

    def log_request(self, request: httpx.Request) -> None:
        if self.debug:
            _debug.log(_debug.redact_dump(_debug.dump_request(request, body=self.debug_bodies)))

    def log_response(self, response: httpx.Response, content: bytes | None) -> None:
        _debug.log(_debug.redact_dump(_debug.dump_response(response, content)))

    def retry_delay(
        self,
        request: httpx.Request,
        response: httpx.Response,
        attempt: int,
        attempts: int,
        waited: float,
    ) -> float | None:
        """Seconds to wait before the next attempt. None: hand this response back as it is
        (the last attempt, a response that is not retried, or a server that asks to wait
        longer than allowed)."""
        if attempt >= attempts or not should_retry(request.method, response.status_code):
            return None
        delay = retry_delay(self.retry, attempt, response.headers.get("Retry-After"))
        if delay is not None and waited + delay > MAX_RETRY_WAIT:
            return None
        return delay

    def log_retry(
        self,
        request: httpx.Request,
        response: httpx.Response,
        delay: float,
        attempt: int,
        attempts: int,
    ) -> None:
        if self.debug:
            _debug.LOGGER.debug(
                "retrying %s %s after %.1fs (attempt %d/%d, got %d %s)",
                request.method,
                request.url.path,
                delay,
                attempt + 1,
                attempts,
                response.status_code,
                response.reason_phrase,
            )

    def check_size(self, content: bytes) -> None:
        if 0 < self.max_response_bytes < len(content):
            raise ResponseTooLargeError(_too_large(self.max_response_bytes))

    def check_deadline(self, started: float | None) -> None:
        if self.deadline is None or started is None:
            return
        if time.monotonic() - started > self.deadline:
            raise RequestTimeoutError(f"timed out: the request took more than {self.deadline:g}s")


class _Body:
    """Collects a response body, failing (never truncating) past cap bytes (0: no cap), and
    failing when the attempt passes its deadline."""

    __slots__ = ("cap", "chunks", "engine", "size", "started")

    def __init__(self, engine: _EngineBase, started: float | None, cap: int | None) -> None:
        self.engine = engine
        self.started = started
        self.cap = engine.max_response_bytes if cap is None else cap
        self.chunks: list[bytes] = []
        self.size = 0

    def add(self, chunk: bytes) -> None:
        self.size += len(chunk)
        if self.cap > 0 and self.size > self.cap:
            raise ResponseTooLargeError(_too_large(self.cap))
        self.engine.check_deadline(self.started)
        self.chunks.append(chunk)

    def content(self) -> bytes:
        return b"".join(self.chunks)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class Engine(_EngineBase):
    """The machinery of Client."""

    http: httpx.Client
    tokens: TokenSource
    #: Waits between retry attempts. The retry_sleep argument of the client replaces it.
    sleep: t.Callable[[float], None] = time.sleep

    # --- what generated code calls ------------------------------------------------------

    def call(
        self,
        op: Operation,
        *,
        path_params: t.Mapping[str, object] | None = None,
        query: t.Iterable[tuple[str, object]] = (),
        headers: t.Iterable[tuple[str, object]] = (),
        body: object = NOT_GIVEN,
        body_type: object = None,
        result: object = None,
    ) -> t.Any:
        """Call one operation and decode its result as the type result (None: no result)."""
        req = self.operation_request(op, path_params, query, headers, body, body_type)
        content, _ = self.send(req)
        if result is None:
            return None
        return decode(result, content)

    def pages(
        self,
        op: Operation,
        *,
        path_params: t.Mapping[str, object] | None = None,
        query: t.Iterable[tuple[str, object]] = (),
        headers: t.Iterable[tuple[str, object]] = (),
        body: object = NOT_GIVEN,
        body_type: object = None,
        item: object = t.Any,
    ) -> t.Iterator[t.Any]:
        """Iterate over a v2 list paginated by cursor."""
        req = self.operation_request(op, path_params, query, headers, body, body_type)
        return iterate(self, req, item)

    # --- sending --------------------------------------------------------------------------

    def send(self, req: Request) -> tuple[bytes, httpx.Headers]:
        """Send one call. The steps run in this order: find the operation, check the path
        and the policy, build the request, run the before hooks, stop there in dry-run mode,
        then fetch the token and send, with retries and the size cap. Return the body and
        headers of a 2xx response. Raise ApiError for any other status.

        The after hooks see every outcome, refusals and exceptions included, then the
        exception goes on. AsyncEngine.send is the same with await: change both."""
        call = Call(req)
        try:
            out = self._send(req, call)
        except BaseException as err:
            for after in self.after_request:
                after(call.info, call.result(err))
            raise
        for after in self.after_request:
            after(call.info, call.result(None))
        return out

    def _send(self, req: Request, call: Call) -> tuple[bytes, httpx.Headers]:
        req, request = self.prepare(req, call)
        for before in self.before_request:
            try:
                before(call.info)
            except Exception as err:
                raise self.hook_refused(call, err) from err
        self.check_dry_run(req, request)
        self.sign(request, self.tokens.token())
        response, content = self.exchange(request, call)
        return self.result(req, response, content)

    def exchange(self, request: httpx.Request, call: Call) -> tuple[httpx.Response, bytes]:
        """One logical request: debug logging, retries, the deadline and the size cap. call
        learns the number of attempts and the last response. AsyncEngine.exchange is the
        same with await: change both."""
        attempts = self.retry.attempts()
        waited = 0.0
        for attempt in itertools.count(1):
            self.log_request(request)
            started = time.monotonic()
            call.attempts = attempt
            # Not retried: a request that got no response may still have been applied.
            with _wrap_httpx(f"{request.method} {request.url.path}"):
                response = self.http.send(request, stream=True)
            self.saw_response(call, response)
            content: bytes | None = None
            try:
                self.check_deadline(started)
                if self.debug:
                    if self.debug_bodies:
                        # The whole body, past max_response_bytes too: the dump shows what
                        # came. The cap applies below, to the response handed back.
                        content = self.read(response, started, cap=0)
                    self.log_response(response, content)
                delay = self.retry_delay(request, response, attempt, attempts, waited)
                if delay is None:
                    if content is None:
                        content = self.read(response, started)
                    else:
                        self.check_size(content)
                    return response, content
                waited += delay
            except BaseException:
                response.close()
                raise
            response.close()
            self.log_retry(request, response, delay, attempt, attempts)
            self.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def read(
        self, response: httpx.Response, started: float | None = None, cap: int | None = None
    ) -> bytes:
        """Read the body, failing past cap bytes (default: max_response_bytes, 0: no cap),
        and failing when the attempt that started at started passes the deadline."""
        body = _Body(self, started, cap)
        try:
            with _wrap_httpx("reading the response"):
                for chunk in response.iter_bytes():
                    body.add(chunk)
                return body.content()
        finally:
            response.close()


async def _async_sleep(seconds: float) -> None:
    import asyncio  # only async programs pay for it

    await asyncio.sleep(seconds)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class AsyncEngine(_EngineBase):
    """The machinery of AsyncClient: Engine, with await."""

    http: httpx.AsyncClient
    tokens: AsyncTokenSource
    #: Waits between retry attempts. The retry_sleep argument of the client replaces it.
    sleep: t.Callable[[float], t.Awaitable[None]] = _async_sleep

    # --- what generated code calls ------------------------------------------------------

    async def call(
        self,
        op: Operation,
        *,
        path_params: t.Mapping[str, object] | None = None,
        query: t.Iterable[tuple[str, object]] = (),
        headers: t.Iterable[tuple[str, object]] = (),
        body: object = NOT_GIVEN,
        body_type: object = None,
        result: object = None,
    ) -> t.Any:
        """Call one operation and decode its result as the type result (None: no result)."""
        req = self.operation_request(op, path_params, query, headers, body, body_type)
        content, _ = await self.send(req)
        if result is None:
            return None
        return decode(result, content)

    def pages(
        self,
        op: Operation,
        *,
        path_params: t.Mapping[str, object] | None = None,
        query: t.Iterable[tuple[str, object]] = (),
        headers: t.Iterable[tuple[str, object]] = (),
        body: object = NOT_GIVEN,
        body_type: object = None,
        item: object = t.Any,
    ) -> t.AsyncIterator[t.Any]:
        """Iterate over a v2 list paginated by cursor."""
        req = self.operation_request(op, path_params, query, headers, body, body_type)
        return aiterate(self, req, item)

    # --- sending --------------------------------------------------------------------------

    async def send(self, req: Request) -> tuple[bytes, httpx.Headers]:
        """Engine.send, with await. A hook may be a plain function or an async one."""
        call = Call(req)
        try:
            out = await self._send(req, call)
        except BaseException as err:
            for after in self.after_request:
                await _maybe_await(after(call.info, call.result(err)))
            raise
        for after in self.after_request:
            await _maybe_await(after(call.info, call.result(None)))
        return out

    async def _send(self, req: Request, call: Call) -> tuple[bytes, httpx.Headers]:
        req, request = self.prepare(req, call)
        for before in self.before_request:
            try:
                await _maybe_await(before(call.info))
            except Exception as err:
                raise self.hook_refused(call, err) from err
        self.check_dry_run(req, request)
        self.sign(request, await self.tokens.token())
        response, content = await self.exchange(request, call)
        return self.result(req, response, content)

    async def exchange(self, request: httpx.Request, call: Call) -> tuple[httpx.Response, bytes]:
        """Engine.exchange, with await: change both."""
        attempts = self.retry.attempts()
        waited = 0.0
        for attempt in itertools.count(1):
            self.log_request(request)
            started = time.monotonic()
            call.attempts = attempt
            with _wrap_httpx(f"{request.method} {request.url.path}"):
                response = await self.http.send(request, stream=True)
            self.saw_response(call, response)
            content: bytes | None = None
            try:
                self.check_deadline(started)
                if self.debug:
                    if self.debug_bodies:
                        content = await self.read(response, started, cap=0)
                    self.log_response(response, content)
                delay = self.retry_delay(request, response, attempt, attempts, waited)
                if delay is None:
                    if content is None:
                        content = await self.read(response, started)
                    else:
                        self.check_size(content)
                    return response, content
                waited += delay
            except BaseException:
                await response.aclose()
                raise
            await response.aclose()
            self.log_retry(request, response, delay, attempt, attempts)
            await self.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    async def read(
        self, response: httpx.Response, started: float | None = None, cap: int | None = None
    ) -> bytes:
        """Engine.read, with await."""
        body = _Body(self, started, cap)
        try:
            with _wrap_httpx("reading the response"):
                async for chunk in response.aiter_bytes():
                    body.add(chunk)
                return body.content()
        finally:
            await response.aclose()


async def _maybe_await(value: object) -> None:
    """Await what an async hook returned. A plain function's None is left as it is."""
    if inspect.isawaitable(value):
        await value


@contextlib.contextmanager
def _wrap_httpx(what: str) -> t.Generator[None]:
    """Turn the httpx errors of a block into OvhError. A body httpx cannot decode (a broken
    gzip) is a DecodeError. A timeout is a RequestTimeoutError. Any other httpx error is a
    TransportError."""
    try:
        yield
    except httpx.DecodingError as err:
        raise DecodeError(f"{what}: the body cannot be decoded: {err}") from err
    except httpx.TimeoutException as err:
        raise RequestTimeoutError(f"{what}: timed out: {err}") from err
    except httpx.HTTPError as err:
        raise TransportError(f"{what}: {err}") from err


def _set(pairs: list[tuple[str, str]], name: str, value: str) -> None:
    """Replace every value of a header with one value."""
    lower = name.lower()
    pairs[:] = [(k, v) for k, v in pairs if k.lower() != lower]
    pairs.append((name, value))


def _too_large(cap: int) -> str:
    return f"the response exceeds the maximum response size ({cap} bytes)"
