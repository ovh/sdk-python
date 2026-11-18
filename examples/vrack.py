# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""vRack: every vRack of the account, with the Public Cloud projects in it. Read-only.

OVH_CLIENT_ID, OVH_CLIENT_SECRET   OAuth2 service-account credentials
OVH_REGION                         eu (default), ca or us

python examples/vrack.py
"""

import ovhcloud

with ovhcloud.Client(read_only=True) as client:
    # list_vracks gives the names only. all_vracks gets each vRack too.
    count = 0
    for vrack in client.vrack.all_vracks():
        count += 1
        name = vrack.service_name or ""
        print(f"{name} {vrack.name!r} {vrack.description or ''}")
        for project in client.vrack.list_cloud_projects(name):
            print(f"  Public Cloud project {project}")
    print(f"{count} vRack(s)")
