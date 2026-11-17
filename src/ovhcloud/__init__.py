# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The Python SDK of the OVHcloud API.

::

    import ovhcloud

    with ovhcloud.Client() as client:  # OVH_CLIENT_ID, OVH_CLIENT_SECRET, OVH_REGION
        for vrack in client.vrack.all_vracks():
            print(vrack.name)

For asyncio programs, ``ovhcloud.AsyncClient`` has the same methods, with await.

Each API section is an attribute of the client, loaded on first use. Its models are in
``ovhcloud.api.<section>.models``.

The installed package has notes for coding agents and an index, next to this file:

- ``AGENTS.md``: the conventions in short. Read it first.
- ``index/<section>.jsonl``: one line per method, with its route and IAM actions. To find
  the method of a route, search it. ``index/README.md`` explains the fields.
- ``llms.txt``: a short summary and links.

Their folder is ``pathlib.Path(ovhcloud.__file__).parent``. In the package's repository,
they are at its root.
"""

from __future__ import annotations

import typing as t

from ._core._auth import (
    AsyncOAuth2ClientCredentials,
    AsyncTokenSource,
    OAuth2ClientCredentials,
    StaticTokenSource,
    TokenSource,
)
from ._core._config import ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_REGION, Region
from ._core._errors import (
    ApiError,
    BadRequestError,
    ConfigurationError,
    ConflictError,
    DecodeError,
    ForbiddenError,
    InvalidRequestError,
    NotAllowedError,
    NotFoundError,
    OvhError,
    RequestTimeoutError,
    ResponseTooLargeError,
    TokenError,
    TooManyRequestsError,
    TransportError,
    UnauthorizedError,
    WaitFailedError,
    WaitTimeoutError,
)
from ._core._models import BaseModel, OpenFloatEnum, OpenIntEnum, OpenStrEnum, is_validated
from ._core._pagination import MAX_CURSOR_PAGES
from ._core._registry import Operation, lookup_operation, match_operation, operations
from ._core._request import path
from ._core._retry import (
    MAX_RETRY_ATTEMPTS,
    MAX_RETRY_DELAY,
    MAX_RETRY_WAIT,
    MIN_RETRY_DELAY,
    RetryPolicy,
)
from ._core._types import NOT_GIVEN, NotGiven, NotGivenOr
from ._core._wait import (
    async_wait,
    async_wait_gone,
    async_wait_ready,
    async_wait_task,
    wait,
    wait_gone,
    wait_ready,
    wait_task,
)
from ._version import __version__

if t.TYPE_CHECKING:
    # The generated client: the core Client plus one attribute per API section. Missing in a
    # checkout of the core alone, before any generation.
    from .api._client import AsyncClient, Client  # pyright: ignore[reportMissingImports]
else:
    try:
        from .api._client import AsyncClient, Client
    except ModuleNotFoundError as _err:
        # A checkout of the core alone, before any generation.
        if _err.name not in (f"{__name__}.api", f"{__name__}.api._client"):
            raise
        from ._core._client import AsyncClient, Client

__all__ = [
    "ENV_CLIENT_ID",
    "ENV_CLIENT_SECRET",
    "ENV_REGION",
    "MAX_CURSOR_PAGES",
    "MAX_RETRY_ATTEMPTS",
    "MAX_RETRY_DELAY",
    "MAX_RETRY_WAIT",
    "MIN_RETRY_DELAY",
    "NOT_GIVEN",
    "ApiError",
    "AsyncClient",
    "AsyncOAuth2ClientCredentials",
    "AsyncTokenSource",
    "BadRequestError",
    "BaseModel",
    "Client",
    "ConfigurationError",
    "ConflictError",
    "DecodeError",
    "ForbiddenError",
    "InvalidRequestError",
    "NotAllowedError",
    "NotFoundError",
    "NotGiven",
    "NotGivenOr",
    "OAuth2ClientCredentials",
    "OpenFloatEnum",
    "OpenIntEnum",
    "OpenStrEnum",
    "Operation",
    "OvhError",
    "Region",
    "RequestTimeoutError",
    "ResponseTooLargeError",
    "RetryPolicy",
    "StaticTokenSource",
    "TokenError",
    "TokenSource",
    "TooManyRequestsError",
    "TransportError",
    "UnauthorizedError",
    "WaitFailedError",
    "WaitTimeoutError",
    "__version__",
    "async_wait",
    "async_wait_gone",
    "async_wait_ready",
    "async_wait_task",
    "is_validated",
    "lookup_operation",
    "match_operation",
    "operations",
    "path",
    "wait",
    "wait_gone",
    "wait_ready",
    "wait_task",
]
