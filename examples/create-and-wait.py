# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Create, then wait: a Public Cloud private network.

The API only starts the work, so the program waits until the network is READY. Then it deletes
the network and waits until it is gone. It changes the project: run it on a test project.

    OVH_CLIENT_ID, OVH_CLIENT_SECRET   OAuth2 service-account credentials
    OVH_REGION                         eu (default), ca or us
    PROJECT_ID                         the Public Cloud project
    CLOUD_REGION                       the region of the network, for example GRA11

    python examples/create-and-wait.py
"""

import os
import sys

import ovhcloud
from ovhcloud.api.public_cloud import models

project_id = os.environ.get("PROJECT_ID", "")
region = os.environ.get("CLOUD_REGION", "")
if not project_id or not region:
    sys.exit("set PROJECT_ID and CLOUD_REGION")

with ovhcloud.Client() as client:
    created = client.public_cloud.create_network(
        project_id,
        models.PublicCloudNetworkNetworkCreation(
            target_spec=models.PublicCloudNetworkNetworkTargetSpec(
                name="sdk-example", location=models.PublicCloudCommonLocation(region=region)
            )
        ),
    )
    network_id = created.id or ""
    if not network_id:
        raise RuntimeError("the API returned a network with no id")
    print(f"network {network_id} is {created.resource_status}")

    def get() -> models.PublicCloudNetworkNetwork:
        return client.public_cloud.get_network(project_id, network_id)

    try:
        # Polls every 2 seconds at first, then less often. Gives up after 10 minutes here.
        network = ovhcloud.wait_ready(get, timeout=10 * 60)
        print(f"network {network_id} is {network.resource_status}")
    except ovhcloud.WaitFailedError as err:
        # The resource went to ERROR (or SUSPENDED...). err.last is its last state.
        print(f"the network failed: {err}", file=sys.stderr)
        raise
    finally:
        client.public_cloud.delete_network(project_id, network_id)
        ovhcloud.wait_gone(get)
        print(f"network {network_id} deleted")
