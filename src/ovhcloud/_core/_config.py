# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Regions, endpoints, environment variables and the User-Agent."""

from __future__ import annotations

import enum
import platform
import sys
import typing as t
from urllib.parse import urlsplit

from .._version import __version__
from ._errors import ConfigurationError

__all__ = [
    "ENV_CLIENT_ID",
    "ENV_CLIENT_SECRET",
    "ENV_REGION",
    "Region",
]

#: Environment variables Client reads when no argument overrides them. Same names as the Go SDK.
ENV_CLIENT_ID: t.Final = "OVH_CLIENT_ID"
ENV_CLIENT_SECRET: t.Final = "OVH_CLIENT_SECRET"
ENV_REGION: t.Final = "OVH_REGION"


class Region(enum.StrEnum):
    """The OVHcloud API a client talks to, and the OAuth2 token endpoint of its tokens.

    A token from one region is refused by the others.
    """

    EU = "eu"
    CA = "ca"
    US = "us"

    @property
    def api_url(self) -> str:
        """The public API host of the region. It accepts OAuth2 bearer tokens."""
        return _REGIONS[self][0]

    @property
    def token_url(self) -> str:
        """The OAuth2 token endpoint of the region."""
        return _REGIONS[self][1]


# The public API hosts, which accept OAuth2 bearer tokens. (The manager hosts that publish the
# OpenAPI specs refuse them.) api.eu.ovhcloud.com and api.ca.ovhcloud.com replace
# eu.api.ovh.com and ca.api.ovh.com, which serve the same API and still answer: pass one of
# them as endpoint if needed. The token endpoints are the ones the identity provider
# advertises in its OpenID configuration.
_REGIONS: dict[Region, tuple[str, str]] = {
    Region.EU: ("https://api.eu.ovhcloud.com", "https://www.ovh.com/auth/oauth2/token"),
    Region.CA: ("https://api.ca.ovhcloud.com", "https://ca.ovh.com/auth/oauth2/token"),
    Region.US: ("https://api.us.ovhcloud.com", "https://us.ovhcloud.com/auth/oauth2/token"),
}


def parse_region(value: str | Region) -> Region:
    """Return the region named by value, in any case. An unknown name is an error."""
    try:
        return Region(str(value).strip().lower())
    except ValueError:
        raise ConfigurationError(f"unknown region {str(value)!r}: want eu, ca or us") from None


def check_endpoint(url: str) -> str:
    """Check an endpoint override and return it without its trailing "/".

    Paths are appended to it as text, so it has no version suffix.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ConfigurationError(f"endpoint {url!r} is not an absolute URL")
    return url.rstrip("/")


def sdk_user_agent() -> str:
    """The SDK's own User-Agent: ``ovhcloud-python-sdk/0.1.0 (cpython3.12.3; linux/x86_64)``.

    It always comes first. The ``user_agent`` option only appends the caller's product.
    """
    runtime = f"{platform.python_implementation().lower()}{platform.python_version()}"
    machine = platform.machine().lower() or "unknown"
    return f"ovhcloud-python-sdk/{__version__} ({runtime}; {sys.platform}/{machine})"


def check_product(product: str) -> str:
    """Check a product the caller appends to the User-Agent: "my-tool/1.2"."""
    product = product.strip()
    if not product or "\r" in product or "\n" in product or not product.isascii():
        raise ConfigurationError(f"user_agent {product!r} is not a valid product")
    return product
