# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Iterators over lists: v2 cursor pagination, and v1 lists of IDs.

Both are lazy: nothing is requested before the first item is asked for, and the next page
or object is requested only when the loop reaches it. Both raise the first error they meet.
"""

from __future__ import annotations

import dataclasses
import typing as t

from ._errors import DecodeError, NotFoundError, OvhError
from ._models import decode

if t.TYPE_CHECKING:
    import httpx

    from ._request import Request

__all__ = ["MAX_CURSOR_PAGES", "aeach", "aiterate", "each", "iterate"]

#: The most pages one cursor walk reads, so a server that hands out new cursors forever
#: cannot make it loop forever.
MAX_CURSOR_PAGES: t.Final = 200

_T = t.TypeVar("_T")
_ID = t.TypeVar("_ID")

CURSOR_HEADER: t.Final = "X-Pagination-Cursor"
CURSOR_NEXT_HEADER: t.Final = "X-Pagination-Cursor-Next"


class Sender(t.Protocol):
    def send(self, req: Request) -> tuple[bytes, httpx.Headers]: ...


class AsyncSender(t.Protocol):
    async def send(self, req: Request) -> tuple[bytes, httpx.Headers]: ...


def iterate(sender: Sender, req: Request, item: object) -> t.Iterator[t.Any]:
    """Yield every item of a v2 list paginated by cursor.

    The first page is the request as given. Each next page is the same request with the
    X-Pagination-Cursor header set to the X-Pagination-Cursor-Next of the last response.
    The walk ends on a response with no X-Pagination-Cursor-Next. aiterate is the same with
    await: change both.
    """
    page: Request | None = req
    for _ in range(MAX_CURSOR_PAGES):
        if page is None:
            return
        body, headers = sender.send(page)
        yield from _items(req, body, item)
        page = _next_page(req, headers)
    if page is not None:
        raise _endless(req)


async def aiterate(sender: AsyncSender, req: Request, item: object) -> t.AsyncIterator[t.Any]:
    """iterate, with await."""
    page: Request | None = req
    for _ in range(MAX_CURSOR_PAGES):
        if page is None:
            return
        body, headers = await sender.send(page)
        for one in _items(req, body, item):
            yield one
        page = _next_page(req, headers)
    if page is not None:
        raise _endless(req)


def _items(req: Request, body: bytes, item: object) -> list[object]:
    items = decode(list[item], body)  # type: ignore[valid-type]
    # A page that is not a list is an error, like in Go. Lenient decoding keeps it as it
    # came, and iterating over it would yield the keys of an object or the letters of a
    # string.
    if items is not None and not isinstance(items, list):
        raise DecodeError(
            f"{req.method} {req.path}: a page is a JSON {_json_kind(items)}, not a list"
        )
    return t.cast("list[object]", items or [])


def _next_page(req: Request, headers: httpx.Headers) -> Request | None:
    """The request of the next page, or None after the last one."""
    cursor = headers.get(CURSOR_NEXT_HEADER, "")
    if not cursor:
        return None
    base = tuple((k, v) for k, v in req.headers if k.lower() != CURSOR_HEADER.lower())
    return dataclasses.replace(req, headers=(*base, (CURSOR_HEADER, cursor)))


def _endless(req: Request) -> OvhError:
    return OvhError(f"{req.method} {req.path}: still paginating after {MAX_CURSOR_PAGES} pages")


def _json_kind(data: object) -> str:
    if isinstance(data, dict):
        return "object"
    if isinstance(data, str):
        return "string"
    if isinstance(data, bool):
        return "boolean"
    if isinstance(data, (int, float)):
        return "number"
    return type(data).__name__


def each(
    list_ids: t.Callable[[], t.Iterable[_ID]],
    get: t.Callable[[_ID], _T],
) -> t.Iterator[_T]:
    """Yield the object behind every ID a v1 list returns.

    It calls list_ids once, then get for each ID, when the loop asks for the next object. An
    object that answers 404 was deleted between the list and its fetch: it is skipped.
    """
    for listed_id in list_ids():
        try:
            obj = get(listed_id)
        except NotFoundError:
            continue
        yield obj


async def aeach(
    list_ids: t.Callable[[], t.Awaitable[t.Iterable[_ID]]],
    get: t.Callable[[_ID], t.Awaitable[_T]],
) -> t.AsyncIterator[_T]:
    """each, with await."""
    for listed_id in await list_ids():
        try:
            obj = await get(listed_id)
        except NotFoundError:
            continue
        yield obj
