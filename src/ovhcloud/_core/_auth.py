# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""OAuth2 authentication: client credentials, or tokens the caller gets another way."""

from __future__ import annotations

import base64
import json
import threading
import time
import typing as t
from urllib.parse import quote_plus, urlencode

import httpx

from ._errors import TokenError

__all__ = [
    "AsyncOAuth2ClientCredentials",
    "AsyncTokenSource",
    "OAuth2ClientCredentials",
    "StaticTokenSource",
    "TokenSource",
]

# A token is renewed this many seconds before it expires, as golang.org/x/oauth2 does.
_EXPIRY_DELTA = 10.0


@t.runtime_checkable
class TokenSource(t.Protocol):
    """Gives the bearer token of each request.

    Implement it to get tokens your own way. It is called before every request, so it must
    cache its token. It must be safe to call from several threads.
    """

    def token(self) -> str:
        """Return a valid access token."""
        ...


@t.runtime_checkable
class AsyncTokenSource(t.Protocol):
    """TokenSource for AsyncClient: its token method is async.

    AsyncClient also takes a TokenSource. It then calls token() in the event loop, so that
    one must not block: it must have its token in memory.
    """

    async def token(self) -> str:
        """Return a valid access token."""
        ...


class StaticTokenSource:
    """Always gives the same token. It is never renewed."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("StaticTokenSource: empty token")
        self._token = token

    def token(self) -> str:
        return self._token

    def __repr__(self) -> str:
        return "StaticTokenSource(token=[REDACTED])"


class _OAuth2Base:
    """What the sync and async client credentials flows share: the token cache, the form,
    and the reading of the answer."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        *,
        scopes: t.Sequence[str],
        clock: t.Callable[[], float],
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self.token_url = token_url
        self._scopes = tuple(scopes)
        self._clock = clock
        self._token = ""
        self._expiry: float | None = None
        # Like golang.org/x/oauth2's AuthStyleAutoDetect: try HTTP Basic first, then the
        # credentials in the form, and keep the one that worked.
        self._in_params: bool | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}(client_id={self._client_id!r}, token_url={self.token_url!r})"

    def _valid(self) -> bool:
        """Whether the cached token can still be used."""
        return bool(self._token) and (
            self._expiry is None or self._clock() < self._expiry - _EXPIRY_DELTA
        )

    def _styles(self) -> tuple[bool, ...]:
        """Where to put the credentials, in the order to try: in the form (True) or in HTTP
        Basic (False)."""
        return (False, True) if self._in_params is None else (self._in_params,)

    def _form(self, in_params: bool) -> tuple[str, dict[str, str]]:
        """The body and headers of a token request."""
        form = {"grant_type": "client_credentials"}
        if self._scopes:
            form["scope"] = " ".join(self._scopes)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        if in_params:
            form["client_id"] = self._client_id
            form["client_secret"] = self._client_secret
        else:
            pair = f"{quote_plus(self._client_id)}:{quote_plus(self._client_secret)}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        return urlencode(form), headers

    def _unreachable(self, err: httpx.HTTPError) -> TokenError:
        return TokenError(self._hide(f"obtaining an OAuth2 token from {self.token_url}: {err}"))

    def _accept(self, resp: httpx.Response, in_params: bool) -> None:
        """Keep the token of an answer. Raise _RefusedError when the server refused it."""
        start = self._clock()
        if not 200 <= resp.status_code <= 299:
            raise _RefusedError(
                self._hide(
                    f"obtaining an OAuth2 token from {self.token_url}: "
                    f"{resp.status_code} {resp.reason_phrase}: {_describe(resp.content)}"
                )
            )
        token, expires_in = _parse_token(resp)
        if not token:
            raise TokenError(
                f"obtaining an OAuth2 token from {self.token_url}: the response has no access_token"
            )
        self._token = token
        self._expiry = start + expires_in if expires_in and expires_in > 0 else None
        self._in_params = in_params

    def _hide(self, text: str) -> str:
        """Remove the client secret from a message, should the server echo it."""
        if self._client_secret:
            text = text.replace(self._client_secret, "[REDACTED]")
            text = text.replace(quote_plus(self._client_secret), "[REDACTED]")
        return text


class OAuth2ClientCredentials(_OAuth2Base):
    """Tokens of an OAuth2 service account, with the client credentials flow.

    The token is fetched on first use, reused until 10 seconds before it expires, then
    fetched again. Threads that need a token at the same time share one fetch.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        *,
        http_client: httpx.Client,
        scopes: t.Sequence[str] = ("all",),
        clock: t.Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(client_id, client_secret, token_url, scopes=scopes, clock=clock)
        self._http = http_client
        self._lock = threading.Lock()

    def token(self) -> str:
        with self._lock:
            if not self._valid():
                self._fetch()
            return self._token

    def _fetch(self) -> None:
        """AsyncOAuth2ClientCredentials._fetch is the same with await: change both."""
        styles = self._styles()
        for i, in_params in enumerate(styles):
            body, headers = self._form(in_params)
            try:
                resp = self._http.post(self.token_url, content=body, headers=headers)
            except httpx.HTTPError as err:
                raise self._unreachable(err) from None
            try:
                self._accept(resp, in_params)
                return
            except _RefusedError as err:
                if i == len(styles) - 1:
                    raise TokenError(str(err)) from None


class AsyncOAuth2ClientCredentials(_OAuth2Base):
    """OAuth2ClientCredentials for AsyncClient: the same flow, with an httpx.AsyncClient.

    Tasks that need a token at the same time share one fetch. Use it in one event loop.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        *,
        http_client: httpx.AsyncClient,
        scopes: t.Sequence[str] = ("all",),
        clock: t.Callable[[], float] = time.monotonic,
    ) -> None:
        import asyncio  # only async programs pay for it

        super().__init__(client_id, client_secret, token_url, scopes=scopes, clock=clock)
        self._http = http_client
        self._lock = asyncio.Lock()

    async def token(self) -> str:
        async with self._lock:
            if not self._valid():
                await self._fetch()
            return self._token

    async def _fetch(self) -> None:
        styles = self._styles()
        for i, in_params in enumerate(styles):
            body, headers = self._form(in_params)
            try:
                resp = await self._http.post(self.token_url, content=body, headers=headers)
            except httpx.HTTPError as err:
                raise self._unreachable(err) from None
            try:
                self._accept(resp, in_params)
                return
            except _RefusedError as err:
                if i == len(styles) - 1:
                    raise TokenError(str(err)) from None


class _RefusedError(Exception):
    """The token endpoint answered outside 2xx."""


def _parse_token(resp: httpx.Response) -> tuple[str, float | None]:
    content_type = resp.headers.get("Content-Type", "")
    data: dict[str, object]
    if "application/x-www-form-urlencoded" in content_type or "text/plain" in content_type:
        data = dict(httpx.QueryParams(resp.text).items())
    else:
        try:
            loaded: object = json.loads(resp.content)
        except ValueError:
            raise TokenError("the OAuth2 token response is not JSON") from None
        if not isinstance(loaded, dict):
            raise TokenError("the OAuth2 token response is not a JSON object")
        data = t.cast("dict[str, object]", loaded)
    token = data.get("access_token")
    expires_in = data.get("expires_in")
    expiry: float | None = None
    is_number = isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool)
    if is_number or (isinstance(expires_in, str) and expires_in.isdigit()):
        expiry = float(t.cast("float | str", expires_in))
    return (token if isinstance(token, str) else ""), expiry


def _describe(body: bytes) -> str:
    """The error of a token endpoint answer: "invalid_client: Bad credentials"."""
    try:
        data: object = json.loads(body)
    except ValueError:
        return body.decode("utf-8", "replace").strip()[:500]
    if isinstance(data, dict):
        data = t.cast("dict[str, object]", data)
        err = data.get("error")
        desc = data.get("error_description")
        if isinstance(err, str) and isinstance(desc, str) and desc:
            return f"{err}: {desc}"
        if isinstance(err, str):
            return err
    return body.decode("utf-8", "replace").strip()[:500]
