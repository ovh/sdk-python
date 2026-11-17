# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""The HTTP client the SDK uses: TLS 1.2 at least, certificates always checked."""

from __future__ import annotations

import os
import ssl
import typing as t

import httpx

from ._errors import ConfigurationError

__all__ = ["new_async_http_client", "new_http_client", "ssl_context"]

# Connections kept open for reuse. The SDK talks to one API host, so Go's default of 2 idle
# connections per host would make it open and close connections under concurrency. The Go
# SDK keeps 10, and so does this one.
_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=10, keepalive_expiry=90.0)

# Connect timeout, TLS handshake included. Go uses 30s to dial, then 10s for TLS.
_CONNECT_TIMEOUT = 30.0

CertFile: t.TypeAlias = str | os.PathLike[str]


def ssl_context(
    *,
    root_cas: CertFile | None = None,
    root_cas_pem: str | bytes | None = None,
    client_cert: CertFile | None = None,
    client_key: CertFile | None = None,
    client_key_password: str | None = None,
) -> ssl.SSLContext:
    """The TLS settings of SDK requests.

    TLS 1.2 is the minimum. Certificates and host names are always checked: there is no
    option to turn that off.

    root_cas (a PEM file) or root_cas_pem (PEM data) replace the system's certificate
    authorities, for a private CA. client_cert and client_key turn on mutual TLS.
    """
    if root_cas is not None and root_cas_pem is not None:
        raise ConfigurationError("give root_cas or root_cas_pem, not both")
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if root_cas is not None or root_cas_pem is not None:
        # Replace the system trust store, like Go's WithRootCAs: a new context with only
        # these authorities.
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            if root_cas is not None:
                ctx.load_verify_locations(cafile=os.fspath(root_cas))
            else:
                data = root_cas_pem.decode() if isinstance(root_cas_pem, bytes) else root_cas_pem
                ctx.load_verify_locations(cadata=data)
        except (ssl.SSLError, ValueError, OSError) as err:
            raise ConfigurationError(f"root CAs: no certificate could be loaded: {err}") from None
        if not ctx.get_ca_certs():
            raise ConfigurationError("root CAs: no certificates found in the PEM data")
    if client_cert is not None:
        try:
            ctx.load_cert_chain(
                os.fspath(client_cert),
                os.fspath(client_key) if client_key is not None else None,
                client_key_password,
            )
        except (ssl.SSLError, OSError) as err:
            raise ConfigurationError(f"client certificate: {err}") from None
    elif client_key is not None:
        raise ConfigurationError("client_key needs client_cert")
    check_ssl_context(ctx)
    return ctx


def check_ssl_context(ctx: ssl.SSLContext) -> None:
    """Refuse a TLS context that does not check certificates or allows TLS below 1.2."""
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
        raise ConfigurationError(
            "ssl_context: certificate checks are off: the SDK always checks the API's certificate"
        )
    if ctx.minimum_version < ssl.TLSVersion.TLSv1_2 and ctx.minimum_version not in (
        ssl.TLSVersion.MINIMUM_SUPPORTED,
    ):
        raise ConfigurationError("ssl_context: TLS below 1.2 is allowed: set minimum_version")
    if ctx.minimum_version == ssl.TLSVersion.MINIMUM_SUPPORTED:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2


def timeout(seconds: float | None) -> httpx.Timeout:
    """The timeouts of each request. None: no timeout, apart from the connect timeout."""
    if seconds is None:
        return httpx.Timeout(None, connect=_CONNECT_TIMEOUT)
    return httpx.Timeout(seconds, connect=min(seconds, _CONNECT_TIMEOUT))


def new_http_client(
    *,
    context: ssl.SSLContext,
    timeout_seconds: float | None,
    proxy: str | None,
    trust_env: bool,
) -> httpx.Client:
    """The httpx.Client of SDK requests and token requests.

    It is never a shared client: other code cannot change its settings, and it carries the
    SDK's own timeout. It does not follow redirects, unlike Go's http.Client: a redirect
    would send the request and its token to a route the client's policy did not check.
    """
    return httpx.Client(**_settings(context, timeout_seconds, proxy, trust_env))


def new_async_http_client(
    *,
    context: ssl.SSLContext,
    timeout_seconds: float | None,
    proxy: str | None,
    trust_env: bool,
) -> httpx.AsyncClient:
    """new_http_client, for AsyncClient: the same settings."""
    return httpx.AsyncClient(**_settings(context, timeout_seconds, proxy, trust_env))


def _settings(
    context: ssl.SSLContext, timeout_seconds: float | None, proxy: str | None, trust_env: bool
) -> dict[str, t.Any]:
    # No explicit transport: httpx then builds one per proxy from HTTP(S)_PROXY and NO_PROXY
    # when trust_env is on, each with these TLS settings and limits.
    return {
        "verify": context,
        "limits": _LIMITS,
        "proxy": proxy,
        "timeout": timeout(timeout_seconds),
        "follow_redirects": False,
        "trust_env": trust_env,
    }
