# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Retries of transient API failures. Same rules and limits as the Go SDK."""

from __future__ import annotations

import dataclasses
import email.utils
import random
import re
import time
import typing as t

from ._errors import ConfigurationError

__all__ = [
    "MAX_RETRY_ATTEMPTS",
    "MAX_RETRY_DELAY",
    "MAX_RETRY_WAIT",
    "MIN_RETRY_DELAY",
    "RetryPolicy",
]

# Retry limits. They are not options: they protect the API from clients that would retry too
# often or too fast. Client refuses a RetryPolicy outside them. Durations are in seconds.

#: The most attempts a request may make, the first one included.
MAX_RETRY_ATTEMPTS: t.Final = 3
#: The shortest wait before a retry. It applies to the backoff and to a Retry-After header
#: that asks for less.
MIN_RETRY_DELAY: t.Final = 3.0
#: The longest single wait a policy may allow.
MAX_RETRY_DELAY: t.Final = 60.0
#: The longest total time one request may spend waiting between attempts.
MAX_RETRY_WAIT: t.Final = 120.0

_DEFAULT_BASE_DELAY = MIN_RETRY_DELAY
_DEFAULT_MAX_DELAY = 30.0

# The responses worth repeating: the server says it is overloaded or not available for now,
# not that the request was wrong.
_RETRYABLE_STATUS = frozenset({429, 503, 504})

# Only methods that read or delete. The API has PUTs that start tasks or place orders, so
# the HTTP idea of an idempotent PUT does not hold here.
_RETRYABLE_METHODS = frozenset({"GET", "HEAD", "DELETE"})


@dataclasses.dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How to retry transient API failures.

    The zero value (``RetryPolicy()``) does not retry: retries are opt-in. Use
    ``RetryPolicy.default()``, or ``retry=True`` on the client.

    Only responses that are safe to repeat are retried: status 429, 503 and 504, and only
    for GET, HEAD and DELETE. POST, PUT and PATCH are never retried: on this API a PUT can
    start a task or place an order. A DELETE that the server had already applied answers
    404 on the retry.

    A request that got no response (connection reset, timeout) is never retried: there is
    no way to know whether the server applied it.

    Durations are in seconds.
    """

    #: Total attempts, the first one included. 0 or 1 disables retries. At most 3.
    max_attempts: int = 0
    #: The first backoff step, doubled at each attempt. 0 means 3s. Else at least 3s.
    base_delay: float = 0.0
    #: The longest single wait. 0 means 30s. Else between base_delay and 60s. A Retry-After
    #: header that asks for longer is not followed: the response goes back to the caller.
    max_delay: float = 0.0

    @classmethod
    def default(cls) -> RetryPolicy:
        """The recommended policy: up to 3 attempts, waiting 3s to 30s between them."""
        return cls(
            max_attempts=MAX_RETRY_ATTEMPTS,
            base_delay=_DEFAULT_BASE_DELAY,
            max_delay=_DEFAULT_MAX_DELAY,
        )

    def validate(self) -> None:
        """Raise ConfigurationError when the policy is outside the retry limits."""
        if not 0 <= self.max_attempts <= MAX_RETRY_ATTEMPTS:
            raise ConfigurationError(
                f"retry: max_attempts is {self.max_attempts}: "
                f"it must be between 0 and {MAX_RETRY_ATTEMPTS}"
            )
        if self.base_delay < 0 or 0 < self.base_delay < MIN_RETRY_DELAY:
            raise ConfigurationError(
                f"retry: base_delay is {self.base_delay}s: "
                f"it must be 0 (default) or at least {MIN_RETRY_DELAY}s"
            )
        if (
            self.max_delay < 0
            or 0 < self.max_delay < MIN_RETRY_DELAY
            or self.max_delay > MAX_RETRY_DELAY
        ):
            raise ConfigurationError(
                f"retry: max_delay is {self.max_delay}s: it must be 0 (default) "
                f"or between {MIN_RETRY_DELAY}s and {MAX_RETRY_DELAY}s"
            )
        base, top = self.bounds()
        if base > top:
            raise ConfigurationError(
                f"retry: base_delay ({base}s) is longer than max_delay ({top}s)"
            )

    def attempts(self) -> int:
        """The total attempt count, never below 1."""
        return max(self.max_attempts, 1)

    def bounds(self) -> tuple[float, float]:
        """The delay bounds, with defaults for zero values."""
        base = self.base_delay if self.base_delay > 0 else _DEFAULT_BASE_DELAY
        top = self.max_delay if self.max_delay > 0 else _DEFAULT_MAX_DELAY
        return base, top


def should_retry(method: str, status_code: int) -> bool:
    """Whether a response may be attempted again. Request bodies are always bytes here,
    so they can always be sent again."""
    return status_code in _RETRYABLE_STATUS and method.upper() in _RETRYABLE_METHODS


_SECONDS = re.compile(r"[+-]?[0-9]+", re.ASCII)


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Read a Retry-After header: a delay in seconds, or an HTTP date. None when absent or
    not readable."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    # Like Go's strconv.Atoi: ASCII digits, an optional sign, and a value that fits in 64
    # bits. Anything else is not a delay in seconds.
    if _SECONDS.fullmatch(value):
        seconds = int(value)
        if -(2**63) <= seconds < 2**63:
            return max(float(seconds), 0.0)
        return None
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        return None
    delay = when.timestamp() - (time.time() if now is None else now)
    return max(delay, 0.0)


def retry_delay(
    policy: RetryPolicy,
    attempt: int,
    retry_after: str | None,
    rand: t.Callable[[], float] = random.random,
) -> float | None:
    """How long to wait before the attempt after this one, or None to not retry.

    A Retry-After header wins over the local backoff: the server knows its load. When it
    asks for more than max_delay, there is no retry: retrying sooner than asked would spend
    an attempt to get another 429.

    Else the delay is exponential with equal jitter: half the backoff, plus a random part up
    to the other half, so clients throttled by the same spike do not retry together.

    Either way the delay is never below MIN_RETRY_DELAY.
    """
    base, top = policy.bounds()
    asked = parse_retry_after(retry_after)
    if asked is not None:
        if asked > top:
            return None
        return max(asked, MIN_RETRY_DELAY)
    backoff = base
    for _ in range(1, attempt):
        if backoff >= top:
            break
        backoff *= 2
    backoff = min(backoff, top)
    half = backoff / 2
    return max(half + rand() * half, MIN_RETRY_DELAY)
