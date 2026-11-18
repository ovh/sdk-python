# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""A raw call: a route by its path, for a route that has no method yet.

ovhcloud.path puts the values in the path and escapes them. result= gives the type of the
result. Read-only.

    OVH_CLIENT_ID, OVH_CLIENT_SECRET   OAuth2 service-account credentials
    OVH_REGION                         eu (default), ca or us
    IP_BLOCK                           an IP block of the account, for example 192.0.2.0/24

    python examples/raw-call.py
"""

import os
import sys
import typing as t

import ovhcloud
from ovhcloud.api.ip import models

block = os.environ.get("IP_BLOCK", "")
if not block:
    sys.exit("set IP_BLOCK")


class Account(t.TypedDict):
    """Your own type, with only the fields the program reads."""

    nichandle: str
    email: str


with ovhcloud.Client(read_only=True) as client:
    me = client.get("/v1/me", result=Account)
    print(f"account {me['nichandle']} <{me['email']}>")

    # "192.0.2.0/24" goes in the path as 192.0.2.0%2F24. Without ovhcloud.path, the slash would
    # call another route. A section's model works too.
    ip = client.get(ovhcloud.path("/v1/ip/{ip}", ip=block), result=models.IPIPWithIAM)
    print(f"{ip.ip} {ip.type} {ip.description or ''}")

    # The same call through the generated method: client.ip.get_ip(block).
