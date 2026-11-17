# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The base class of the generated section classes (client.vrack, client.public_cloud...)."""

from __future__ import annotations

import typing as t

from ._pagination import aeach, each
from ._retry import RetryPolicy
from ._types import NOT_GIVEN, NotGiven

if t.TYPE_CHECKING:
    from ._client import AsyncClient, Client
    from ._engine import AsyncEngine, Engine
    from ._registry import Operation

__all__ = ["AsyncSectionApi", "SectionApi"]

_Self = t.TypeVar("_Self", bound="SectionApi")
_ASelf = t.TypeVar("_ASelf", bound="AsyncSectionApi")
_T = t.TypeVar("_T")
_ID = t.TypeVar("_ID")


class SectionApi:
    """The operations of one API section. Get it from the client: ``client.vrack``."""

    _client: Client
    _engine: Engine

    def __init__(self, client: Client) -> None:
        self._client = client
        self._engine = client._engine  # pyright: ignore[reportPrivateUsage]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._client!r})"

    def with_options(
        self: _Self,
        *,
        timeout: float | None | NotGiven = NOT_GIVEN,
        retry: RetryPolicy | bool | None | NotGiven = NOT_GIVEN,
        max_response_bytes: int | NotGiven = NOT_GIVEN,
        headers: t.Mapping[str, str] | None = None,
    ) -> _Self:
        """This section on a client with other settings (see Client.with_options)::

        client.vrack.with_options(timeout=5).list_vracks()
        """
        client = self._client.with_options(
            timeout=timeout, retry=retry, max_response_bytes=max_response_bytes, headers=headers
        )
        return type(self)(client)

    # What the generated methods call.

    def _call(
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
        return self._engine.call(
            op,
            path_params=path_params,
            query=query,
            headers=headers,
            body=body,
            body_type=body_type,
            result=result,
        )

    def _pages(
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
        return self._engine.pages(
            op,
            path_params=path_params,
            query=query,
            headers=headers,
            body=body,
            body_type=body_type,
            item=item,
        )

    def _each(
        self,
        list_ids: t.Callable[[], t.Iterable[_ID]],
        get: t.Callable[[_ID], _T],
    ) -> t.Iterator[_T]:
        return each(list_ids, get)


class AsyncSectionApi:
    """SectionApi, for AsyncClient: the methods are async. Get it from the client:
    ``client.vrack``."""

    _client: AsyncClient
    _engine: AsyncEngine

    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._engine = client._engine  # pyright: ignore[reportPrivateUsage]

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._client!r})"

    def with_options(
        self: _ASelf,
        *,
        timeout: float | None | NotGiven = NOT_GIVEN,
        retry: RetryPolicy | bool | None | NotGiven = NOT_GIVEN,
        max_response_bytes: int | NotGiven = NOT_GIVEN,
        headers: t.Mapping[str, str] | None = None,
    ) -> _ASelf:
        """This section on a client with other settings (see Client.with_options)::

        await client.vrack.with_options(timeout=5).list_vracks()
        """
        client = self._client.with_options(
            timeout=timeout, retry=retry, max_response_bytes=max_response_bytes, headers=headers
        )
        return type(self)(client)

    # What the generated methods call.

    async def _call(
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
        return await self._engine.call(
            op,
            path_params=path_params,
            query=query,
            headers=headers,
            body=body,
            body_type=body_type,
            result=result,
        )

    def _pages(
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
        return self._engine.pages(
            op,
            path_params=path_params,
            query=query,
            headers=headers,
            body=body,
            body_type=body_type,
            item=item,
        )

    def _each(
        self,
        list_ids: t.Callable[[], t.Awaitable[t.Iterable[_ID]]],
        get: t.Callable[[_ID], t.Awaitable[_T]],
    ) -> t.AsyncIterator[_T]:
        return aeach(list_ids, get)
