# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""A DNS record: create a TXT record, then refresh the zone so the name servers serve it.

A record is not served until the zone is refreshed. It changes the zone: use a test zone.

    OVH_CLIENT_ID, OVH_CLIENT_SECRET   OAuth2 service-account credentials
    OVH_REGION                         eu (default), ca or us
    ZONE                               a DNS zone of the account, for example example.com

    python examples/dns-record.py
"""

import os
import sys

import ovhcloud
from ovhcloud.api.domain import models

zone = os.environ.get("ZONE", "")
if not zone:
    sys.exit("set ZONE")

with ovhcloud.Client() as client:
    record = client.domain.create_record(
        zone,
        models.DomainZoneRecordCreateWritable(
            field_type="TXT",
            sub_domain="sdk-example",
            target='"created by the OVHcloud Python SDK"',
            ttl=60,
        ),
    )
    print(f"record {record.id}: {record.sub_domain}.{zone} {record.field_type} {record.target}")

    # Apply the change: the name servers now serve the new record.
    client.domain.refresh_zone(zone)
    print(f"zone {zone} refreshed")

    # To remove it: delete_record, then refresh_zone again.
    if os.environ.get("CLEANUP") and record.id is not None:
        client.domain.delete_record(zone, record.id)
        client.domain.refresh_zone(zone)
        print(f"record {record.id} deleted")
