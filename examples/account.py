# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Account: the details of your account, GET /v1/me. The program of the README's quick start.

Read-only.

    OVH_CLIENT_ID, OVH_CLIENT_SECRET   OAuth2 service-account credentials
    OVH_REGION                         eu (default), ca or us

    python examples/account.py
"""

import ovhcloud

with ovhcloud.Client() as client:  # reads OVH_CLIENT_ID, OVH_CLIENT_SECRET, OVH_REGION
    account = client.me.get_account_details()  # GET /v1/me
    print("account:", account.nichandle)
    print("email:  ", account.email)
    print("country:", account.country)
