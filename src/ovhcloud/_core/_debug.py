# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Debug logging of requests and responses, with credentials hidden.

The client's ``debug`` option logs every request and response on the "ovhcloud" logger, at
DEBUG level. Show them with ``logging.basicConfig(level=logging.DEBUG)``.
"""

from __future__ import annotations

import logging
import typing as t

import httpx

__all__ = ["LOGGER", "dump_request", "dump_response", "redact_dump"]

#: The logger of the SDK.
LOGGER: t.Final = logging.getLogger("ovhcloud")

#: Replaces the value of a header that carries credentials.
REDACTED: t.Final = "[REDACTED]"

# Headers whose values must never reach the logs, in canonical case.
SENSITIVE_HEADERS: t.Final = frozenset(
    {
        "Authorization",
        "Proxy-Authorization",
        "Cookie",
        "Set-Cookie",
        # Legacy OVH application key auth. This SDK uses OAuth2, but a caller can still set
        # these with the headers option.
        "X-Ovh-Application",
        "X-Ovh-Consumer",
        "X-Ovh-Signature",
    }
)


def canonical_header_key(name: str) -> str:
    """Go's http.CanonicalHeaderKey: "x-ovh-consumer" gives "X-Ovh-Consumer".

    A name with a character that is not valid in a header name is returned as it is.
    """
    valid = "!#$%&'*+-.^_`|~"
    if not name or any(not (c.isascii() and (c.isalnum() or c in valid)) for c in name):
        return name
    out: list[str] = []
    upper = True
    for c in name:
        out.append(c.upper() if upper else c.lower())
        upper = c == "-"
    return "".join(out)


def redact_dump(dump: str) -> str:
    """Blank the values of credential headers in a dump of a request or response.

    It changes the text, never the request or response. Only the header block is read:
    scanning stops at the first empty line, so a body that contains "Authorization: ..."
    is left as it is.
    """
    lines = dump.split("\n")
    for i, line in enumerate(lines):
        if i == 0:
            continue  # request line or status line
        trimmed = line.rstrip("\r")
        if not trimmed:
            break  # end of the header block
        colon = trimmed.find(":")
        if colon <= 0:
            continue
        name = canonical_header_key(trimmed[:colon].strip())
        if name not in SENSITIVE_HEADERS:
            continue
        replacement = f"{name}: {REDACTED}"
        if line.endswith("\r"):
            replacement += "\r"
        lines[i] = replacement
    return "\n".join(lines)


def _headers(headers: httpx.Headers) -> str:
    return "".join(f"{k}: {v}\r\n" for k, v in headers.multi_items())


def dump_request(request: httpx.Request, *, body: bool) -> str:
    """The request as HTTP/1.1 text, credentials not hidden yet."""
    target = request.url.raw_path.decode("ascii", "replace")
    # httpx puts Host in the request's headers.
    text = f"{request.method} {target} HTTP/1.1\r\n" + _headers(request.headers) + "\r\n"
    if body:
        text += request.content.decode("utf-8", "replace")
    return text


def dump_response(response: httpx.Response, body: bytes | None) -> str:
    """The response as HTTP/1.1 text, with body when it is not None."""
    text = f"HTTP/1.1 {response.status_code} {response.reason_phrase}\r\n"
    text += _headers(response.headers) + "\r\n"
    if body is not None:
        text += body.decode("utf-8", "replace")
    return text


def log(text: str) -> None:
    LOGGER.debug("\n%s\n", text)
