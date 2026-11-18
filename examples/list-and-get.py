# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""List and get: every DNS zone of the account with an iterator, then one zone and its records.

Read-only.

    OVH_CLIENT_ID, OVH_CLIENT_SECRET   OAuth2 service-account credentials
    OVH_REGION                         eu (default), ca or us

    python examples/list-and-get.py
"""

import ovhcloud

# read_only: this program cannot change anything, whatever its service account may do.
with ovhcloud.Client(read_only=True) as client:
    # all_zones lists the names, then gets each zone. The next zone is read only when the loop
    # reaches it, so a break stops the calls.
    names: list[str] = []
    for zone in client.domain.all_zones():
        print(f"{zone.name} last update {zone.last_update or 'never'}")
        if zone.name:
            names.append(zone.name)

    if not names:
        print("no DNS zone")
    else:
        first = names[0]
        # One object, by its name.
        zone = client.domain.get_zone(first)
        print(f"{zone.name}: name servers {', '.join(zone.name_servers or [])}")
        # The records of the zone, with a filter on the type.
        count = 0
        for record in client.domain.all_records(first, field_type="A"):
            count += 1
            print(f"  {record.sub_domain or '@'} {record.field_type} {record.target}")
        print(f"{count} A record(s)")
