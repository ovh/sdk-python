# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Waiting for asynchronous work.

Many operations only start the work. A v2 resource is created or updated in the background:
its resourceStatus moves from CREATING or UPDATING to READY. A v1 operation returns a task
whose status moves from todo to done. The wait functions call a GET until the work is over::

    instance = ovhcloud.wait_ready(lambda: cloud.get_instance(project_id, instance_id))

They poll every 2 seconds at first, then less often, up to every 30 seconds, and give up after
30 minutes. ``poll`` and ``timeout`` change that. A response of 429, 500, 502, 503 or 504 is
polled again. Any other error stops the wait.

With AsyncClient, use the async_ functions, with await. get returns an awaitable::

    instance = await ovhcloud.async_wait_ready(lambda: cloud.get_instance(project_id, iid))
"""

from __future__ import annotations

import collections.abc
import enum
import time
import typing as t

from ._errors import ApiError, NotFoundError, OvhError, WaitFailedError, WaitTimeoutError

__all__ = [
    "async_wait",
    "async_wait_gone",
    "async_wait_ready",
    "async_wait_task",
    "wait",
    "wait_gone",
    "wait_ready",
    "wait_task",
]

_T = t.TypeVar("_T")

_TRANSIENT = frozenset({429, 500, 502, 503, 504})

# Task statuses across the API. done in either case is success. These end the wait with a
# WaitFailedError. Any other status (todo, doing, init, PENDING, RUNNING...) is polled again.
_TASK_FAILED = frozenset(
    {
        "error",
        "ERROR",
        "cancelled",
        "canceled",
        "customerError",
        "ovhError",
        "problem",
        "FAILED",
        "CANCELLED",
    }
)
# The task waits for someone: polling will not move it on.
_TASK_BLOCKED = frozenset({"WAITING_USER_INPUT", "pause", "PAUSED", "standby"})
_RESOURCE_FAILED = frozenset({"ERROR", "SUSPENDED", "DELETED", "REMOVED"})

DEFAULT_POLL: t.Final = (2.0, 30.0)
DEFAULT_TIMEOUT: t.Final = 30 * 60.0


class _Poll:
    """The rules of a wait, with no I/O: how long to sleep, when to give up, and what to say.
    wait and async_wait run the same loop around it."""

    def __init__(
        self, poll: tuple[float, float], timeout: float | None, clock: t.Callable[[], float]
    ) -> None:
        first, longest = poll
        if first <= 0:
            first = 1.0
        self.longest = max(longest, first)
        self.clock = clock
        self.start = clock()
        self.deadline = None if timeout is None or timeout <= 0 else self.start + timeout
        self.interval = first
        self.state = "not read yet"

    def failed(self, err: ApiError) -> None:
        """An error of get: a transient one is polled again, any other ends the wait."""
        if err.status_code not in _TRANSIENT:
            raise err
        self.state = str(err)

    def read(self, value: object) -> None:
        self.state = _describe(value)

    def next(self) -> tuple[float, bool]:
        """How long to sleep, and whether to give up after that sleep."""
        now = self.clock()
        if self.deadline is not None and now + self.interval > self.deadline:
            return max(self.deadline - now, 0.0), True
        interval = self.interval
        self.interval = min(self.interval * 1.5, self.longest)
        return interval, False

    def timeout_error(self, last: object) -> WaitTimeoutError:
        return WaitTimeoutError(
            f"gave up waiting after {_duration(self.clock() - self.start)}, {self.state}", last
        )


def wait(
    get: t.Callable[[], _T],
    done: t.Callable[[_T], bool],
    *,
    poll: tuple[float, float] = DEFAULT_POLL,
    timeout: float | None = DEFAULT_TIMEOUT,
    sleep: t.Callable[[float], None] = time.sleep,
    clock: t.Callable[[], float] = time.monotonic,
) -> _T:
    """Call get, then done with what it returned, until done returns True.

    poll is (first, longest): the interval between two polls grows by half at each poll,
    from first to longest. timeout is in seconds. None waits forever.

    Return get's last value. Raise WaitTimeoutError when the timeout ends first, and any
    error of get or done that is not transient. Example::

        order = ovhcloud.wait(lambda: me.get_order(order_id), lambda o: o.status == "delivered")

    async_wait is the same with await: change both.
    """
    state = _Poll(poll, timeout, clock)
    last: _T | None = None
    while True:
        try:
            value = get()
        except ApiError as err:
            state.failed(err)
        else:
            last = value
            if done(value):
                return value
            state.read(value)
        seconds, give_up = state.next()
        if give_up:
            if seconds > 0:
                sleep(seconds)
            raise state.timeout_error(last)
        sleep(seconds)


async def async_wait(
    get: t.Callable[[], t.Awaitable[_T]],
    done: t.Callable[[_T], bool],
    *,
    poll: tuple[float, float] = DEFAULT_POLL,
    timeout: float | None = DEFAULT_TIMEOUT,
    sleep: t.Callable[[float], t.Awaitable[None]] | None = None,
    clock: t.Callable[[], float] = time.monotonic,
) -> _T:
    """wait, for AsyncClient: get returns an awaitable. done stays a plain function::

    order = await ovhcloud.async_wait(
        lambda: client.me.get_order(order_id), lambda o: o.status == "delivered"
    )
    """
    if sleep is None:
        import asyncio  # only async programs pay for it

        sleep = asyncio.sleep
    state = _Poll(poll, timeout, clock)
    last: _T | None = None
    while True:
        try:
            value = await get()
        except ApiError as err:
            state.failed(err)
        else:
            last = value
            if done(value):
                return value
            state.read(value)
        seconds, give_up = state.next()
        if give_up:
            if seconds > 0:
                await sleep(seconds)
            raise state.timeout_error(last)
        await sleep(seconds)


def _ready(value: object) -> bool:
    status = _status(value, "resource_status", "resourceStatus")
    if status == "READY":
        return True
    if status in _RESOURCE_FAILED:
        raise WaitFailedError(f"the operation failed: resourceStatus is {status}", value)
    return False


def _task_done(value: object) -> bool:
    status = _status(value, "status", "status")
    if status in ("done", "DONE"):
        return True
    if status in _TASK_FAILED:
        raise WaitFailedError(f"the operation failed: the task's status is {status}", value)
    if status in _TASK_BLOCKED:
        raise WaitFailedError(
            f"the operation failed: the task's status is {status}: it waits for an action",
            value,
        )
    return False


def wait_ready(
    get: t.Callable[[], _T],
    *,
    poll: tuple[float, float] = DEFAULT_POLL,
    timeout: float | None = DEFAULT_TIMEOUT,
    sleep: t.Callable[[float], None] = time.sleep,
    clock: t.Callable[[], float] = time.monotonic,
) -> _T:
    """Wait for a v2 resource: until its resource_status is READY.

    ERROR, SUSPENDED, DELETED and REMOVED end the wait with a WaitFailedError. The object
    must have a resource_status attribute (or a "resourceStatus" key), as the v2 resources
    of the generated sections have.
    """
    return wait(get, _ready, poll=poll, timeout=timeout, sleep=sleep, clock=clock)


async def async_wait_ready(
    get: t.Callable[[], t.Awaitable[_T]],
    *,
    poll: tuple[float, float] = DEFAULT_POLL,
    timeout: float | None = DEFAULT_TIMEOUT,
    sleep: t.Callable[[float], t.Awaitable[None]] | None = None,
    clock: t.Callable[[], float] = time.monotonic,
) -> _T:
    """wait_ready, for AsyncClient::

    instance = await ovhcloud.async_wait_ready(lambda: cloud.get_instance(project_id, iid))
    """
    return await async_wait(get, _ready, poll=poll, timeout=timeout, sleep=sleep, clock=clock)


def wait_task(
    get: t.Callable[[], _T],
    *,
    poll: tuple[float, float] = DEFAULT_POLL,
    timeout: float | None = DEFAULT_TIMEOUT,
    sleep: t.Callable[[float], None] = time.sleep,
    clock: t.Callable[[], float] = time.monotonic,
) -> _T:
    """Wait for a task: until its status is done (or DONE).

    A task in error, cancelled, or waiting for an action (WAITING_USER_INPUT, pause, standby)
    ends the wait with a WaitFailedError. The object must have a status attribute (or a
    "status" key), as the tasks of the generated sections have::

        task = server.reboot(service_name)
        task = ovhcloud.wait_task(lambda: server.get_task(service_name, task.task_id))
    """
    return wait(get, _task_done, poll=poll, timeout=timeout, sleep=sleep, clock=clock)


async def async_wait_task(
    get: t.Callable[[], t.Awaitable[_T]],
    *,
    poll: tuple[float, float] = DEFAULT_POLL,
    timeout: float | None = DEFAULT_TIMEOUT,
    sleep: t.Callable[[float], t.Awaitable[None]] | None = None,
    clock: t.Callable[[], float] = time.monotonic,
) -> _T:
    """wait_task, for AsyncClient."""
    return await async_wait(get, _task_done, poll=poll, timeout=timeout, sleep=sleep, clock=clock)


def wait_gone(
    get: t.Callable[[], object],
    *,
    poll: tuple[float, float] = DEFAULT_POLL,
    timeout: float | None = DEFAULT_TIMEOUT,
    sleep: t.Callable[[float], None] = time.sleep,
    clock: t.Callable[[], float] = time.monotonic,
) -> None:
    """Wait for a deletion: until get raises NotFoundError (404)::

    cloud.delete_instance(project_id, instance_id)
    ovhcloud.wait_gone(lambda: cloud.get_instance(project_id, instance_id))
    """

    def gone() -> bool:
        try:
            get()
        except NotFoundError:
            return True
        return False

    wait(gone, lambda g: g, poll=poll, timeout=timeout, sleep=sleep, clock=clock)


async def async_wait_gone(
    get: t.Callable[[], t.Awaitable[object]],
    *,
    poll: tuple[float, float] = DEFAULT_POLL,
    timeout: float | None = DEFAULT_TIMEOUT,
    sleep: t.Callable[[float], t.Awaitable[None]] | None = None,
    clock: t.Callable[[], float] = time.monotonic,
) -> None:
    """wait_gone, for AsyncClient."""

    async def gone() -> bool:
        try:
            await get()
        except NotFoundError:
            return True
        return False

    await async_wait(gone, lambda g: g, poll=poll, timeout=timeout, sleep=sleep, clock=clock)


def _status(value: object, attr: str, key: str) -> str:
    """Read a status field: an attribute, or a key of a dict. "" when it is None."""
    if value is None:
        raise OvhError(f"cannot wait on None: no {attr}")
    raw: object
    kind = type(value).__name__
    if isinstance(value, collections.abc.Mapping):
        mapping = t.cast("collections.abc.Mapping[str, object]", value)
        if key not in mapping:
            raise OvhError(f"cannot wait on a {kind}: it has no {key!r} key")
        raw = mapping[key]
    else:
        if not hasattr(value, attr):
            raise OvhError(f"cannot wait on a {type(value).__name__}: it has no {attr} field")
        raw = getattr(value, attr)
    if raw is None:
        return ""
    if isinstance(raw, enum.Enum):
        raw = t.cast("object", raw.value)
    if not isinstance(raw, str):
        raise OvhError(
            f"cannot wait on a {kind}: its {attr} is a {type(raw).__name__}, not a string"
        )
    return raw


def _describe(value: object) -> str:
    """Where a wait stands, for the error when it gives up."""
    for attr, key in (("resource_status", "resourceStatus"), ("status", "status")):
        try:
            status = _status(value, attr, key)
        except OvhError:
            continue
        if status:
            return f"last status {status}"
    return "not done yet"


def _duration(seconds: float) -> str:
    """Go's Duration.Round(time.Second).String(): "30m0s", "1h2m3s", "45s"."""
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes}m{secs}s"
    if minutes:
        return f"{minutes}m{secs}s"
    return f"{secs}s"
