# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The clients of the OVHcloud API: Client, and AsyncClient for asyncio programs."""

from __future__ import annotations

import dataclasses
import os
import ssl
import typing as t

import httpx

from ._auth import (
    AsyncOAuth2ClientCredentials,
    AsyncTokenSource,
    OAuth2ClientCredentials,
    TokenSource,
)
from ._config import (
    ENV_CLIENT_ID,
    ENV_CLIENT_SECRET,
    ENV_REGION,
    Region,
    check_endpoint,
    check_product,
    parse_region,
    sdk_user_agent,
)
from ._engine import AsyncEngine, Engine
from ._errors import ConfigurationError
from ._hooks import (
    AfterRequestHook,
    AsyncAfterRequestHook,
    AsyncBeforeRequestHook,
    BeforeRequestHook,
    check_hooks,
)
from ._models import decode, decode_raw
from ._pagination import aiterate, iterate
from ._policy import Policy
from ._request import Request, check_header
from ._retry import RetryPolicy
from ._transport import (
    CertFile,
    check_ssl_context,
    new_async_http_client,
    new_http_client,
    ssl_context,
    timeout,
)
from ._types import NOT_GIVEN, NotGiven

__all__ = ["AsyncClient", "Client"]

_Self = t.TypeVar("_Self", bound="_BaseClient[t.Any]")
_E = t.TypeVar("_E", Engine, AsyncEngine)
_T = t.TypeVar("_T")

QueryOrHeaders: t.TypeAlias = t.Mapping[str, object] | t.Iterable[tuple[str, object]] | None

# Headers the headers option cannot set: the SDK owns them.
_OWN_HEADERS = {
    "user-agent": "use the user_agent option",
    "x-schemas-version": "the SDK sends the version its types were generated from",
}


class _BaseClient(t.Generic[_E]):
    """What Client and AsyncClient share."""

    _engine: _E
    _owns_http: bool
    _region: Region

    def __repr__(self) -> str:
        return f"{type(self).__name__}(endpoint={self._engine.endpoint!r})"

    @property
    def endpoint(self) -> str:
        """The API base URL requests go to: "https://api.eu.ovhcloud.com"."""
        return self._engine.endpoint

    @property
    def region(self) -> Region:
        return self._region

    def with_options(
        self: _Self,
        *,
        timeout: float | None | NotGiven = NOT_GIVEN,
        retry: RetryPolicy | bool | None | NotGiven = NOT_GIVEN,
        max_response_bytes: int | NotGiven = NOT_GIVEN,
        headers: t.Mapping[str, str] | None = None,
    ) -> _Self:
        """A client like this one, with other settings. It shares this client's connections
        and token, so it is cheap. Closing it does nothing: close the first client::

            client.with_options(timeout=5).vrack.list_vracks()
        """
        changes: dict[str, object] = {}
        if not isinstance(timeout, NotGiven):
            if timeout is not None and timeout <= 0:
                raise ConfigurationError(f"timeout must be positive, not {timeout}")
            changes["timeout"] = timeout_for(timeout)
            changes["deadline"] = timeout
        if not isinstance(retry, NotGiven):
            changes["retry"] = _retry_policy(retry)
        if not isinstance(max_response_bytes, NotGiven):
            changes["max_response_bytes"] = max(max_response_bytes, 0)
        if headers:
            changes["headers"] = self._engine.headers + _check_headers(headers)
        clone = object.__new__(type(self))
        clone._engine = dataclasses.replace(self._engine, **changes)  # pyright: ignore[reportArgumentType]
        clone._owns_http = False
        clone._region = self._region
        return clone


class Client(_BaseClient[Engine]):
    """A client of the OVHcloud API. Create one and share it: it is safe to use from
    several threads.

    With no arguments it reads its credentials from OVH_CLIENT_ID and OVH_CLIENT_SECRET (an
    OAuth2 service account) and its region from OVH_REGION (eu, ca or us; eu by default).
    Arguments win over the environment::

        import ovhcloud

        with ovhcloud.Client() as client:
            print(client.me.get_account_details())

    Each API section is an attribute, loaded on first use: ``client.vrack``,
    ``client.public_cloud``. Each API call is a method of its section:
    ``client.me.get_account_details()``.

    Arguments, all keyword-only:

    region
        "eu", "ca" or "us". It also picks the OAuth2 token endpoint, which must match: a
        token of one region is refused by the others, with a 401 that looks like a bad
        secret.
    client_id, client_secret
        An OAuth2 service account (client credentials flow).
    token_source
        Tokens you get your own way: an object with a ``token() -> str`` method.
    endpoint
        Replaces the region's API URL, for a proxy or a test server. No version suffix.
    timeout
        Seconds one request may take, from sending it to the end of the response body, like
        the Go SDK's WithTimeout. Each retry attempt has its own. None (the default) means
        no timeout, apart from a 30s connect timeout.
    retry
        A RetryPolicy, or True for RetryPolicy.default(). Off by default.
    max_response_bytes
        Fail, never truncate, on a response body larger than this. 0: no limit.
    debug, debug_bodies
        Log every request and response on the "ovhcloud" logger at DEBUG level. Credential
        headers are always hidden. debug_bodies adds the bodies, which often carry secrets.
    user_agent
        Your application, "my-tool/1.2". It is added after the SDK's own User-Agent.
    headers
        Headers sent with every request. They cannot set User-Agent or X-Schemas-Version.
    read_only
        True: send only GET and HEAD. A list of operation name patterns: the same, plus
        these operations.
    allowed_operations
        Send only the operations whose name matches one of these patterns: "vrack.*",
        "*.get_*".
    dry_run
        True: send reads (GET and HEAD) as usual, and nothing else. Any other call raises
        DryRunError, with the URL, headers and body it would have sent. No token is fetched
        for it. The policy (read_only, allowed_operations) still applies first.
    before_request
        A function, or a list of them, called with a CallInfo before each call. Raise an
        exception to refuse the call: nothing is sent, and the caller gets a
        HookRefusedError. It runs once per call, not per retry. A call refused by the
        policy, or malformed, never reaches it.
    after_request
        A function, or a list of them, called with a CallInfo and a CallResult after each
        call, once its retries are over. It sees every call, also those refused by the
        policy, by a before hook or by dry_run, so it can keep a full audit log.

        Hooks run in the order given. Each page of an ``all_`` iterator is a separate call.
        The client is shared, so a hook must be safe to call from several threads at once.
    root_cas, root_cas_pem
        Replace the system's certificate authorities with a PEM file or PEM data.
    client_cert, client_key, client_key_password
        Mutual TLS.
    ssl_context
        Your own TLS settings. It must check certificates, with TLS 1.2 at least.
    proxy
        A proxy URL, or None for no proxy. By default HTTPS_PROXY and NO_PROXY apply.
    http_client
        Your own httpx.Client. The TLS and proxy arguments cannot be used with it.
    retry_sleep
        Called with the seconds to wait between two retry attempts, in place of time.sleep.
        For tests: ``retry_sleep=lambda seconds: None`` retries a mocked 503 at once. The
        retry limits still apply. The Go SDK has this only inside its own tests.
    """

    def __init__(
        self,
        *,
        region: str | Region | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
        retry: RetryPolicy | bool | None = None,
        max_response_bytes: int = 0,
        debug: bool = False,
        debug_bodies: bool = False,
        user_agent: str | None = None,
        headers: t.Mapping[str, str] | None = None,
        read_only: bool | t.Iterable[str] = False,
        allowed_operations: t.Iterable[str] | None = None,
        root_cas: CertFile | None = None,
        root_cas_pem: str | bytes | None = None,
        client_cert: CertFile | None = None,
        client_key: CertFile | None = None,
        client_key_password: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        proxy: str | None | NotGiven = NOT_GIVEN,
        token_source: TokenSource | None = None,
        http_client: httpx.Client | None = None,
        retry_sleep: t.Callable[[float], None] | None = None,
        dry_run: bool = False,
        before_request: BeforeRequestHook | t.Sequence[BeforeRequestHook] | None = None,
        after_request: AfterRequestHook | t.Sequence[AfterRequestHook] | None = None,
    ) -> None:
        setup = _Setup.resolve(
            region=region,
            endpoint=endpoint,
            timeout=timeout,
            retry=retry,
            max_response_bytes=max_response_bytes,
            debug=debug,
            debug_bodies=debug_bodies,
            user_agent=user_agent,
            headers=headers,
            read_only=read_only,
            allowed_operations=allowed_operations,
            root_cas=root_cas,
            root_cas_pem=root_cas_pem,
            client_cert=client_cert,
            client_key=client_key,
            client_key_password=client_key_password,
            ssl_context=ssl_context,
            proxy=proxy,
            http_client_given=http_client is not None,
            dry_run=dry_run,
        )
        before = check_hooks("before_request", before_request, allow_async=False)
        after = check_hooks("after_request", after_request, allow_async=False)
        if http_client is not None:
            if timeout is not None:
                http_client.timeout = timeout_for(timeout)
            http, owns = http_client, False
        else:
            http, owns = new_http_client(**setup.http_args()), True
        try:
            tokens = _token_source(token_source, client_id, client_secret, setup.region, http)
        except BaseException:
            if owns:
                http.close()
            raise
        engine = Engine(
            http=http,
            tokens=tokens,
            before_request=before,
            after_request=after,
            **setup.engine_args(),
        )
        if retry_sleep is not None:
            engine = dataclasses.replace(engine, sleep=retry_sleep)
        self._engine = engine
        self._owns_http = owns
        self._region = setup.region

    def close(self) -> None:
        """Close the connections, unless the client was given its http_client."""
        if self._owns_http:
            self._engine.http.close()

    def __enter__(self: _Self) -> _Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- calling any route ------------------------------------------------------------------

    @t.overload
    def request(
        self,
        method: str,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        body: object = NOT_GIVEN,
        schemas_version: str | None = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    def request(
        self,
        method: str,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        body: object = NOT_GIVEN,
        schemas_version: str | None = None,
        result: type[_T],
    ) -> _T: ...
    def request(
        self,
        method: str,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        body: object = NOT_GIVEN,
        schemas_version: str | None = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """Call any route and return the decoded JSON (dicts and lists), or None.

        path has the API version: "/v1/me", "/v2/iam/policy". Build a path with parameters
        with ``ovhcloud.path``, which escapes them. A response that is a bare, unquoted string
        is returned as a str. An error status raises ApiError, like the generated methods::

            me = client.request("GET", "/v1/me")
            client.request("POST", "/v1/me/contact", body={"email": "..."})

        With result, the response is decoded as that type, the way the generated methods
        decode theirs: a response that does not match it is still decoded, without
        validation. This is Go's ``ovh.Call[T]``::

            names = client.get("/v1/vrack", result=list[str])
        """
        req = _raw_request(method, path, query, headers, body, schemas_version)
        content, _ = self._engine.send(req)
        if result is None:
            return decode_raw(content)
        return decode(result, content)

    @t.overload
    def get(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    def get(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    def get(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("GET", path, ...)``."""
        return self.request("GET", path, query=query, headers=headers, result=result)

    @t.overload
    def post(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    def post(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    def post(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("POST", path, body=body, ...)``."""
        return self.request("POST", path, query=query, headers=headers, body=body, result=result)

    @t.overload
    def put(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    def put(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    def put(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("PUT", path, body=body, ...)``."""
        return self.request("PUT", path, query=query, headers=headers, body=body, result=result)

    @t.overload
    def patch(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    def patch(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    def patch(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("PATCH", path, body=body, ...)``."""
        return self.request("PATCH", path, query=query, headers=headers, body=body, result=result)

    @t.overload
    def delete(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    def delete(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    def delete(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("DELETE", path, ...)``."""
        return self.request("DELETE", path, query=query, headers=headers, result=result)

    def iterate(
        self,
        path: str,
        *,
        method: str = "GET",
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        body: object = NOT_GIVEN,
        schemas_version: str | None = None,
    ) -> t.Iterator[t.Any]:
        """Iterate over the items of any v2 list paginated by cursor, page by page::

        for policy in client.iterate("/v2/iam/policy"):
            print(policy["name"])
        """
        req = _raw_request(method, path, query, headers, body, schemas_version)
        return iterate(self._engine, req, t.Any)


class AsyncClient(_BaseClient[AsyncEngine]):
    """Client, for asyncio programs. It takes the same arguments, and its methods are the
    same, with await::

        import ovhcloud

        async with ovhcloud.AsyncClient() as client:
            print(await client.me.get_account_details())
            async for project in client.public_cloud.all_projects():
                print(project.name)

    Iterators (``all_`` methods, ``iterate``) are async iterators: use ``async for``. The
    wait functions have async forms: ``ovhcloud.async_wait_ready``...

    Differences with Client:

    token_source
        An AsyncTokenSource (``async def token()``), or a TokenSource. A TokenSource is
        called in the event loop, so it must not block.
    http_client
        Your own httpx.AsyncClient.
    retry_sleep
        An async function: ``async def no_sleep(seconds: float) -> None: pass``.
    before_request, after_request
        Plain functions or async functions. A plain one runs in the event loop, so it must
        not block. Calls made at the same time in the loop run a hook at the same time.

    Use one AsyncClient in one event loop. Close it with ``await client.aclose()``, or use
    ``async with``.
    """

    def __init__(
        self,
        *,
        region: str | Region | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
        retry: RetryPolicy | bool | None = None,
        max_response_bytes: int = 0,
        debug: bool = False,
        debug_bodies: bool = False,
        user_agent: str | None = None,
        headers: t.Mapping[str, str] | None = None,
        read_only: bool | t.Iterable[str] = False,
        allowed_operations: t.Iterable[str] | None = None,
        root_cas: CertFile | None = None,
        root_cas_pem: str | bytes | None = None,
        client_cert: CertFile | None = None,
        client_key: CertFile | None = None,
        client_key_password: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        proxy: str | None | NotGiven = NOT_GIVEN,
        token_source: AsyncTokenSource | TokenSource | None = None,
        http_client: httpx.AsyncClient | None = None,
        retry_sleep: t.Callable[[float], t.Awaitable[None]] | None = None,
        dry_run: bool = False,
        before_request: AsyncBeforeRequestHook | t.Sequence[AsyncBeforeRequestHook] | None = None,
        after_request: AsyncAfterRequestHook | t.Sequence[AsyncAfterRequestHook] | None = None,
    ) -> None:
        setup = _Setup.resolve(
            region=region,
            endpoint=endpoint,
            timeout=timeout,
            retry=retry,
            max_response_bytes=max_response_bytes,
            debug=debug,
            debug_bodies=debug_bodies,
            user_agent=user_agent,
            headers=headers,
            read_only=read_only,
            allowed_operations=allowed_operations,
            root_cas=root_cas,
            root_cas_pem=root_cas_pem,
            client_cert=client_cert,
            client_key=client_key,
            client_key_password=client_key_password,
            ssl_context=ssl_context,
            proxy=proxy,
            http_client_given=http_client is not None,
            dry_run=dry_run,
        )
        before = check_hooks("before_request", before_request, allow_async=True)
        after = check_hooks("after_request", after_request, allow_async=True)
        if http_client is not None:
            if timeout is not None:
                http_client.timeout = timeout_for(timeout)
            http, owns = http_client, False
        else:
            http, owns = new_async_http_client(**setup.http_args()), True
        # Nothing to close on error: an httpx.AsyncClient opens no connection before its
        # first request.
        tokens = _async_token_source(token_source, client_id, client_secret, setup.region, http)
        engine = AsyncEngine(
            http=http,
            tokens=tokens,
            before_request=before,
            after_request=after,
            **setup.engine_args(),
        )
        if retry_sleep is not None:
            engine = dataclasses.replace(engine, sleep=retry_sleep)
        self._engine = engine
        self._owns_http = owns
        self._region = setup.region

    async def aclose(self) -> None:
        """Close the connections, unless the client was given its http_client."""
        if self._owns_http:
            await self._engine.http.aclose()

    async def __aenter__(self: _Self) -> _Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # --- calling any route ------------------------------------------------------------------

    @t.overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        body: object = NOT_GIVEN,
        schemas_version: str | None = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        body: object = NOT_GIVEN,
        schemas_version: str | None = None,
        result: type[_T],
    ) -> _T: ...
    async def request(
        self,
        method: str,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        body: object = NOT_GIVEN,
        schemas_version: str | None = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """Call any route and return the decoded JSON (dicts and lists), or None.

        path has the API version: "/v1/me", "/v2/iam/policy". Build a path with parameters
        with ``ovhcloud.path``, which escapes them. A response that is a bare, unquoted string
        is returned as a str. An error status raises ApiError, like the generated methods::

            me = await client.request("GET", "/v1/me")
            await client.request("POST", "/v1/me/contact", body={"email": "..."})

        With result, the response is decoded as that type, the way the generated methods
        decode theirs: a response that does not match it is still decoded, without
        validation. This is Go's ``ovh.Call[T]``::

            names = await client.get("/v1/vrack", result=list[str])
        """
        req = _raw_request(method, path, query, headers, body, schemas_version)
        content, _ = await self._engine.send(req)
        if result is None:
            return decode_raw(content)
        return decode(result, content)

    @t.overload
    async def get(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    async def get(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    async def get(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("GET", path, ...)``."""
        return await self.request("GET", path, query=query, headers=headers, result=result)

    @t.overload
    async def post(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    async def post(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    async def post(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("POST", path, body=body, ...)``."""
        return await self.request(
            "POST", path, query=query, headers=headers, body=body, result=result
        )

    @t.overload
    async def put(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    async def put(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    async def put(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("PUT", path, body=body, ...)``."""
        return await self.request(
            "PUT", path, query=query, headers=headers, body=body, result=result
        )

    @t.overload
    async def patch(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    async def patch(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    async def patch(
        self,
        path: str,
        body: object = NOT_GIVEN,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("PATCH", path, body=body, ...)``."""
        return await self.request(
            "PATCH", path, query=query, headers=headers, body=body, result=result
        )

    @t.overload
    async def delete(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: None = None,
    ) -> t.Any: ...
    @t.overload
    async def delete(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[_T],
    ) -> _T: ...
    async def delete(
        self,
        path: str,
        *,
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        result: type[t.Any] | None = None,
    ) -> t.Any:
        """``request("DELETE", path, ...)``."""
        return await self.request("DELETE", path, query=query, headers=headers, result=result)

    def iterate(
        self,
        path: str,
        *,
        method: str = "GET",
        query: QueryOrHeaders = None,
        headers: QueryOrHeaders = None,
        body: object = NOT_GIVEN,
        schemas_version: str | None = None,
    ) -> t.AsyncIterator[t.Any]:
        """Iterate over the items of any v2 list paginated by cursor, page by page::

        async for policy in client.iterate("/v2/iam/policy"):
            print(policy["name"])
        """
        req = _raw_request(method, path, query, headers, body, schemas_version)
        return aiterate(self._engine, req, t.Any)


@dataclasses.dataclass(frozen=True, slots=True)
class _Setup:
    """The arguments of a client, checked and resolved. Client and AsyncClient then build
    their own HTTP client and token source."""

    region: Region
    endpoint: str
    user_agent: str
    headers: tuple[tuple[str, str], ...]
    retry: RetryPolicy
    max_response_bytes: int
    debug: bool
    debug_bodies: bool
    policy: Policy
    deadline: float | None
    #: The TLS settings of the HTTP client the SDK makes. None when the caller gave one.
    context: ssl.SSLContext | None
    proxy: str | None
    trust_env: bool
    dry_run: bool

    @classmethod
    def resolve(
        cls,
        *,
        region: str | Region | None,
        endpoint: str | None,
        timeout: float | None,
        retry: RetryPolicy | bool | None,
        max_response_bytes: int,
        debug: bool,
        debug_bodies: bool,
        user_agent: str | None,
        headers: t.Mapping[str, str] | None,
        read_only: bool | t.Iterable[str],
        allowed_operations: t.Iterable[str] | None,
        root_cas: CertFile | None,
        root_cas_pem: str | bytes | None,
        client_cert: CertFile | None,
        client_key: CertFile | None,
        client_key_password: str | None,
        ssl_context: ssl.SSLContext | None,
        proxy: str | None | NotGiven,
        http_client_given: bool,
        dry_run: bool,
    ) -> _Setup:
        resolved_region = parse_region(region or os.environ.get(ENV_REGION) or Region.EU)

        base = resolved_region.api_url
        if endpoint is not None:
            base = check_endpoint(endpoint)

        agent = sdk_user_agent()
        if user_agent is not None:
            agent = f"{agent} {check_product(user_agent)}"

        extra_headers = _check_headers(headers or {})
        policy_retry = _retry_policy(retry)
        policy = Policy.build(read_only, allowed_operations)

        if timeout is not None and timeout <= 0:
            raise ConfigurationError(f"timeout must be positive, not {timeout}")

        tls_given = any(
            v is not None
            for v in (
                root_cas,
                root_cas_pem,
                client_cert,
                client_key,
                client_key_password,
                ssl_context,
            )
        )
        context: ssl.SSLContext | None = None
        if http_client_given:
            if tls_given or not isinstance(proxy, NotGiven):
                raise ConfigurationError(
                    "the TLS and proxy arguments cannot change a given http_client: "
                    "configure them on it"
                )
        elif ssl_context is not None:
            if root_cas is not None or root_cas_pem is not None or client_cert is not None:
                raise ConfigurationError(
                    "give ssl_context, or root_cas, root_cas_pem and client_cert, not both"
                )
            check_ssl_context(ssl_context)
            context = ssl_context
        else:
            context = _ssl_context(
                root_cas, root_cas_pem, client_cert, client_key, client_key_password
            )

        return cls(
            region=resolved_region,
            endpoint=base,
            user_agent=agent,
            headers=extra_headers,
            retry=policy_retry,
            max_response_bytes=max(max_response_bytes, 0),
            debug=debug or debug_bodies,
            debug_bodies=debug_bodies,
            policy=policy,
            deadline=timeout,
            context=context,
            proxy=None if isinstance(proxy, NotGiven) else proxy,
            trust_env=isinstance(proxy, NotGiven),
            dry_run=dry_run,
        )

    def engine_args(self) -> dict[str, t.Any]:
        return {
            "endpoint": self.endpoint,
            "user_agent": self.user_agent,
            "headers": self.headers,
            "retry": self.retry,
            "max_response_bytes": self.max_response_bytes,
            "debug": self.debug,
            "debug_bodies": self.debug_bodies,
            "policy": self.policy,
            "deadline": self.deadline,
            "dry_run": self.dry_run,
        }

    def http_args(self) -> dict[str, t.Any]:
        assert self.context is not None
        return {
            "context": self.context,
            "timeout_seconds": self.deadline,
            "proxy": self.proxy,
            "trust_env": self.trust_env,
        }


def _raw_request(
    method: str,
    path: str,
    query: QueryOrHeaders,
    headers: QueryOrHeaders,
    body: object,
    schemas_version: str | None,
) -> Request:
    return Request(
        method=method.upper(),
        path=path,
        query=_pairs(query),
        headers=_pairs(headers),
        body=body,
        schemas_version=schemas_version,
    )


def timeout_for(seconds: float | None) -> httpx.Timeout:
    return timeout(seconds)


def _retry_policy(retry: RetryPolicy | bool | None) -> RetryPolicy:
    if retry is None or retry is False:
        return RetryPolicy()
    if retry is True:
        return RetryPolicy.default()
    retry.validate()
    return retry


def _check_headers(headers: t.Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for key, value in headers.items():
        why = _OWN_HEADERS.get(key.lower())
        if why is not None:
            raise ConfigurationError(f"headers cannot set {key}: {why}")
        try:
            check_header(key, value)
        except ValueError as err:
            raise ConfigurationError(str(err)) from None
        out.append((key, value))
    return tuple(out)


def _ssl_context(
    root_cas: CertFile | None,
    root_cas_pem: str | bytes | None,
    client_cert: CertFile | None,
    client_key: CertFile | None,
    client_key_password: str | None,
) -> ssl.SSLContext:
    return ssl_context(
        root_cas=root_cas,
        root_cas_pem=root_cas_pem,
        client_cert=client_cert,
        client_key=client_key,
        client_key_password=client_key_password,
    )


def _token_source(
    token_source: TokenSource | None,
    client_id: str | None,
    client_secret: str | None,
    region: Region,
    http: httpx.Client,
) -> TokenSource:
    if token_source is not None:
        if not callable(getattr(token_source, "token", None)):
            raise ConfigurationError("token_source has no token() method")
        return token_source
    client_id, client_secret = _credentials(client_id, client_secret)
    # Tokens are fetched with the same hardened client as API calls.
    return OAuth2ClientCredentials(client_id, client_secret, region.token_url, http_client=http)


def _async_token_source(
    token_source: AsyncTokenSource | TokenSource | None,
    client_id: str | None,
    client_secret: str | None,
    region: Region,
    http: httpx.AsyncClient,
) -> AsyncTokenSource:
    if token_source is not None:
        token = getattr(token_source, "token", None)
        if not callable(token):
            raise ConfigurationError("token_source has no token() method")
        import inspect  # only async programs pay for it

        if inspect.iscoroutinefunction(token):
            return t.cast("AsyncTokenSource", token_source)
        return _AsyncTokens(t.cast("TokenSource", token_source))
    client_id, client_secret = _credentials(client_id, client_secret)
    return AsyncOAuth2ClientCredentials(
        client_id, client_secret, region.token_url, http_client=http
    )


class _AsyncTokens:
    """A TokenSource used by AsyncClient. Its token() is called in the event loop."""

    __slots__ = ("source",)

    def __init__(self, source: TokenSource) -> None:
        self.source = source

    async def token(self) -> str:
        return self.source.token()

    def __repr__(self) -> str:
        return repr(self.source)


def _credentials(client_id: str | None, client_secret: str | None) -> tuple[str, str]:
    """The service account: the arguments, or else the environment."""
    if client_id is None and client_secret is None:
        client_id = os.environ.get(ENV_CLIENT_ID, "")
        client_secret = os.environ.get(ENV_CLIENT_SECRET, "")
    client_id = client_id or ""
    client_secret = client_secret or ""
    if client_id and client_secret:
        return client_id, client_secret
    if client_id or client_secret:
        raise ConfigurationError(
            "both a client ID and a client secret are needed: only one was given"
        )
    raise ConfigurationError(
        f"no credentials: set {ENV_CLIENT_ID} and {ENV_CLIENT_SECRET}, "
        "or give client_id and client_secret, or token_source"
    )


def _pairs(
    values: t.Mapping[str, object] | t.Iterable[tuple[str, object]] | None,
) -> tuple[tuple[str, object], ...]:
    if values is None:
        return ()
    if isinstance(values, t.Mapping):
        return tuple(t.cast("t.Mapping[str, object]", values).items())
    return tuple(values)
