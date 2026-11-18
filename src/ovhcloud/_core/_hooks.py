# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Request hooks: functions the client calls before and after each API call.

This is ``ovh/hooks.go`` of the Go SDK. Go's WithBeforeRequest and WithAfterRequest are the
``before_request`` and ``after_request`` arguments of the client. A Go before hook returns
an error to refuse a call. A Python one raises an exception, and the caller gets a
HookRefusedError with that exception as its ``__cause__``. A BaseException that is not an
Exception (KeyboardInterrupt, asyncio.CancelledError) is not a refusal: it goes on as it is,
like a panic in Go, after the after hooks saw it. Go has no async hooks: AsyncClient takes
plain functions and async ones.
"""

from __future__ import annotations

import dataclasses
import inspect
import time
import typing as t

from ._errors import ConfigurationError
from ._registry import is_read_only
from ._types import NotGiven

if t.TYPE_CHECKING:
    from ._registry import Operation
    from ._request import Request

__all__ = [
    "AfterRequestHook",
    "AsyncAfterRequestHook",
    "AsyncBeforeRequestHook",
    "BeforeRequestHook",
    "CallInfo",
    "CallResult",
]


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class CallInfo:
    """One API call, as the hooks see it. It never holds the Authorization header or the
    token. It is frozen: a hook cannot change the call."""

    #: The operation called. None when the registry does not know the route: a raw call
    #: (``client.get``...) to a section the program never loaded.
    operation: Operation | None
    #: The HTTP method: "POST".
    method: str
    #: The path with its parameters filled in: "/v1/vrack/pn-1/cloudProject".
    path: str
    #: The query the call sends, as encoded pairs, with any query written in the path. For a
    #: call refused before it was encoded (by the policy, or because it is malformed), it is
    #: the query the call was given, before encoding.
    query: tuple[tuple[str, object], ...]
    #: The request body as the caller gave it, before JSON encoding. None when the call has
    #: no body.
    body: object

    @property
    def read_only(self) -> bool:
        """True for GET and HEAD: a call that only reads, which a dry run sends. Go has it as
        Operation.ReadOnly() only. Here it is on the call too, so it works for an unknown
        route, as in the TypeScript SDK."""
        return is_read_only(self.method)


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class CallResult:
    """How a call ended, for the after hooks."""

    #: The HTTP status of the last response. 0 when there was none: the call was refused
    #: before it was sent, or the network failed.
    status_code: int
    #: The X-Ovh-Queryid header of the last response, which identifies the request to
    #: OVHcloud support. "" when there was no response.
    query_id: str
    #: The exception the caller gets. None on success.
    error: BaseException | None
    #: Seconds the whole call took, retries included.
    duration: float
    #: How many times the request was sent: 0 when it was not sent, more than 1 when it was
    #: retried.
    attempts: int


#: A hook that runs before each call. It refuses the call by raising an exception.
BeforeRequestHook: t.TypeAlias = t.Callable[[CallInfo], None]
#: A hook that runs after each call, whatever the outcome.
AfterRequestHook: t.TypeAlias = t.Callable[[CallInfo, CallResult], None]
#: A before hook of AsyncClient: a plain function or an async one.
AsyncBeforeRequestHook: t.TypeAlias = t.Callable[[CallInfo], t.Awaitable[None] | None]
#: An after hook of AsyncClient: a plain function or an async one.
AsyncAfterRequestHook: t.TypeAlias = t.Callable[[CallInfo, CallResult], t.Awaitable[None] | None]


class Call:
    """What the engine learns about one call while it runs, for the after hooks."""

    __slots__ = ("attempts", "info", "query_id", "started", "status_code")

    def __init__(self, req: Request) -> None:
        self.started = time.monotonic()
        self.info = CallInfo(
            operation=req.operation,
            method=req.method,
            path=req.path,
            query=req.query,
            body=None if isinstance(req.body, NotGiven) else req.body,
        )
        self.status_code = 0
        self.query_id = ""
        self.attempts = 0

    def result(self, error: BaseException | None) -> CallResult:
        return CallResult(
            status_code=self.status_code,
            query_id=self.query_id,
            error=error,
            duration=time.monotonic() - self.started,
            attempts=self.attempts,
        )


_Hook = t.TypeVar("_Hook", bound=t.Callable[..., object])


def check_hooks(
    option: str, hooks: _Hook | t.Iterable[_Hook] | None, *, allow_async: bool
) -> tuple[_Hook, ...]:
    """The hooks of a client argument: one function, or several. Raise ConfigurationError
    for something that is not a function, and for an async function given to Client."""
    if hooks is None:
        return ()
    given = t.cast("object", hooks)  # the types say what is expected, not what is passed
    if callable(given):
        items: tuple[object, ...] = (given,)
    elif isinstance(given, (str, bytes)) or not isinstance(given, t.Iterable):
        raise ConfigurationError(f"{option}: {given!r} is not a function or a list of them")
    else:
        items = tuple(t.cast("t.Iterable[object]", given))
    for hook in items:
        if not callable(hook):
            raise ConfigurationError(f"{option}: {hook!r} is not a function")
        if not allow_async and inspect.iscoroutinefunction(hook):
            raise ConfigurationError(
                f"{option}: {hook!r} is an async function: give it to AsyncClient"
            )
    return t.cast("tuple[_Hook, ...]", items)
