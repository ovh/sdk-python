# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The SDK's exceptions.

Every exception the SDK raises is an OvhError. The Go SDK has sentinel errors matched with
errors.Is. Here each sentinel is an exception class:

=====================  =======================
Go                     Python
=====================  =======================
*APIError              ApiError
ErrBadRequest          BadRequestError (400)
ErrUnauthorized        UnauthorizedError (401)
ErrForbidden           ForbiddenError (403)
ErrNotFound            NotFoundError (404)
ErrConflict            ConflictError (409)
ErrTooManyRequests     TooManyRequestsError (429)
ErrInvalidRequest      InvalidRequestError
ErrNotAllowed          NotAllowedError
ErrResponseTooLarge    ResponseTooLargeError
ErrWaitFailed          WaitFailedError
=====================  =======================
"""

from __future__ import annotations

import json
import typing as t

if t.TYPE_CHECKING:
    from ._registry import Operation

__all__ = [
    "ApiError",
    "BadRequestError",
    "ConfigurationError",
    "ConflictError",
    "DecodeError",
    "ForbiddenError",
    "InvalidRequestError",
    "NotAllowedError",
    "NotFoundError",
    "OvhError",
    "RequestTimeoutError",
    "ResponseTooLargeError",
    "TokenError",
    "TooManyRequestsError",
    "TransportError",
    "UnauthorizedError",
    "WaitFailedError",
    "WaitTimeoutError",
]


class OvhError(Exception):
    """The base class of every exception the SDK raises."""

    def __reduce__(self) -> tuple[object, ...]:
        # The default calls cls(*self.args), which fails for the errors with keyword-only or
        # more arguments than args holds. Rebuild from args and the attributes instead, so
        # every error survives pickle and copy (multiprocessing, concurrent.futures...).
        return (_rebuild, (type(self), self.args, self.__dict__))


def _rebuild(cls: type[OvhError], args: tuple[object, ...], state: dict[str, object]) -> OvhError:
    err = cls.__new__(cls)
    err.args = args
    err.__dict__.update(state)
    return err


class ConfigurationError(OvhError, ValueError):
    """The client cannot be created with these settings: no credentials, an unknown region..."""


class ApiError(OvhError):
    """The API answered with a status outside 2xx.

    The message is the API's own, so printing the error is usually enough. It names the
    operation, and on a 401 or 403 the IAM actions the call needs::

        vrack.get_vrack: GET /v1/vrack/pn-1: 403 Forbidden: ... (Client::Forbidden);
        requires the IAM action vrack:apiovh:get

    (on one line).

    Catch a subclass to handle one status: ``except ovhcloud.NotFoundError``. Read
    ``status_code``, ``message`` or ``query_id`` on any of them.
    """

    #: The operation's registry name, "vrack.get_vrack", when the registry knows the route.
    operation: str
    #: The IAM actions the operation needs. On a 403, the caller's policy lacks one of them.
    iam_actions: tuple[str, ...]
    method: str
    path: str
    status_code: int
    #: The status line: "403 Forbidden".
    status: str
    #: ``class`` and ``message`` of the API's error body, when it has that usual shape.
    error_class: str
    message: str
    #: Identifies the request to OVHcloud support (the X-Ovh-Queryid header).
    query_id: str
    #: The X-Schemas-Version the API served the response with (v2 routes only), or "".
    schemas_version: str
    #: The raw response body.
    body: bytes

    def __init__(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        status: str,
        body: bytes = b"",
        query_id: str = "",
        schemas_version: str = "",
        operation: Operation | None = None,
    ) -> None:
        self.method = method
        self.path = path
        self.status_code = status_code
        self.status = status
        self.body = body
        self.query_id = query_id
        self.schemas_version = schemas_version
        self.operation = operation.name if operation is not None else ""
        self.iam_actions = operation.iam_actions if operation is not None else ()
        self.error_class, self.message = _error_payload(body)
        super().__init__(self._text())

    def _text(self) -> str:
        parts: list[str] = []
        if self.operation:
            parts.append(f"{self.operation}: ")
        parts.append(f"{self.method} {self.path}: {self.status}")
        if self.message:
            parts.append(f": {self.message}")
        elif self.body:
            parts.append(f": {self.body.decode('utf-8', 'replace').strip()}")
        if self.error_class:
            parts.append(f" ({self.error_class})")
        if self.iam_actions and self.status_code in (401, 403):
            s = "s" if len(self.iam_actions) > 1 else ""
            parts.append(f"; requires the IAM action{s} {', '.join(self.iam_actions)}")
        if self.status_code == 400 and "Unknown version" in self.message:
            parts.append(
                "; this SDK release targets an X-Schemas-Version the API no longer serves:"
                " upgrade the SDK"
            )
        return "".join(parts)

    def __str__(self) -> str:
        return self._text()


class BadRequestError(ApiError):
    """400 Bad Request."""


class UnauthorizedError(ApiError):
    """401 Unauthorized: the token is missing, expired, or from another region."""


class ForbiddenError(ApiError):
    """403 Forbidden: the service account lacks an IAM action. Retrying does not help."""


class NotFoundError(ApiError):
    """404 Not Found."""


class ConflictError(ApiError):
    """409 Conflict."""


class TooManyRequestsError(ApiError):
    """429 Too Many Requests."""


_STATUS_ERRORS: dict[int, type[ApiError]] = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    429: TooManyRequestsError,
}


def api_error_class(status_code: int) -> type[ApiError]:
    """Return the ApiError subclass of a status code, or ApiError itself."""
    return _STATUS_ERRORS.get(status_code, ApiError)


def _error_payload(body: bytes) -> tuple[str, str]:
    """Read ``class`` and ``message`` from an error body of the usual shape."""
    try:
        payload: object = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    payload = t.cast("dict[str, object]", payload)
    cls = payload.get("class")
    msg = payload.get("message")
    return (cls if isinstance(cls, str) else ""), (msg if isinstance(msg, str) else "")


class InvalidRequestError(OvhError, ValueError):
    """A request refused before it is sent because it is malformed.

    For example an empty path parameter, or a path that does not start with "/".
    """


class NotAllowedError(OvhError):
    """A request the client is configured to refuse. Nothing was sent.

    See the ``read_only`` and ``allowed_operations`` options of Client.
    """

    #: The operation's name, or "" when the registry does not know the route.
    operation: str
    method: str
    path: str
    #: Which option refused it.
    reason: str

    def __init__(self, *, operation: str, method: str, path: str, reason: str) -> None:
        self.operation = operation
        self.method = method
        self.path = path
        self.reason = reason
        name = operation or "request"
        super().__init__(f"{name} ({method} {path}) not sent: {reason}")


class ResponseTooLargeError(OvhError):
    """The response body exceeds the client's ``max_response_bytes``.

    The SDK fails rather than truncate the body.
    """


class TransportError(OvhError):
    """The request got no response: connection refused, DNS failure, timeout, TLS error.

    It is never retried: the server may have applied a request that got no answer. The
    httpx exception is the ``__cause__``.
    """


class RequestTimeoutError(TransportError, TimeoutError):
    """The request timed out: httpx gave up on a step (connect, read...), or the attempt
    took more than the client's timeout in all.

    It is a TransportError, so it is never retried either, and a TimeoutError, so
    ``except TimeoutError`` catches it. When httpx timed out, its exception is the
    ``__cause__``. Go has no such type: there, the error's Timeout() method tells.
    """


class TokenError(OvhError):
    """The OAuth2 token endpoint refused the credentials or could not be reached.

    The message never contains the client secret.
    """


class DecodeError(OvhError):
    """A 2xx response body is not valid JSON, or a body cannot be decoded (a broken gzip)."""


class WaitFailedError(OvhError):
    """A wait ended in a failure: a resourceStatus of ERROR, a task in error or cancelled,
    or a task that waits for an action.

    ``last`` is the last value the wait read.
    """

    last: object

    def __init__(self, message: str, last: object) -> None:
        super().__init__(message)
        self.last = last


class WaitTimeoutError(OvhError, TimeoutError):
    """A wait gave up: the work was not done before the timeout.

    ``last`` is the last value the wait read, or None.
    """

    last: object

    def __init__(self, message: str, last: object) -> None:
        super().__init__(message)
        self.last = last
