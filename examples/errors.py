# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Errors: each HTTP error has its own exception class.

Catch them from the most precise to the most general. Read-only.

    OVH_CLIENT_ID, OVH_CLIENT_SECRET   OAuth2 service-account credentials
    OVH_REGION                         eu (default), ca or us

    python examples/errors.py
"""

import ovhcloud

with ovhcloud.Client(read_only=True) as client:
    try:
        # .invalid is a reserved name: this zone does not exist.
        zone = client.domain.get_zone("no-such-zone.invalid")
        print(f"found {zone.name}")
    except ovhcloud.NotFoundError as err:
        # 404: the object does not exist, or the account cannot see it.
        print(f"not found: {err.method} {err.path}: {err.message}")
    except ovhcloud.ForbiddenError as err:
        # 403: the IAM actions that the service account needs.
        print(f"forbidden: the service account needs {', '.join(err.iam_actions)}")
    except ovhcloud.ApiError as err:
        # Any other HTTP error. Give the query id to the support.
        print(f"{err.status} from {err.operation}, query id {err.query_id}")
    except ovhcloud.OvhError as err:
        # Not an HTTP error: credentials, network, timeout, read-only mode...
        print(f"{type(err).__name__}: {err}")
