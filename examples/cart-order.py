# SPDX-FileCopyrightText: 2026 OVH SAS
#
# SPDX-License-Identifier: Apache-2.0

"""Ordering with a cart: a cart, a domain name in it, and the price of the order.

It stops before payment: get_cart_checkout gives the price, create_cart_checkout would place the
order. Then it deletes the cart.

    OVH_CLIENT_ID, OVH_CLIENT_SECRET   OAuth2 service-account credentials
    OVH_REGION                         eu (default), ca or us
    DOMAIN                             a domain name to price, for example my-new-name.com
    SUBSIDIARY                         the OVHcloud subsidiary of the account: FR (default), GB...

    python examples/cart-order.py
"""

import os
import sys

import ovhcloud
from ovhcloud.api.order import models

domain = os.environ.get("DOMAIN", "")
if not domain:
    sys.exit("set DOMAIN")
# Not checked here: the API refuses an unknown subsidiary.
subsidiary = models.NichandleOvhSubsidiaryEnum(os.environ.get("SUBSIDIARY", "FR"))

with ovhcloud.Client() as client:
    cart = client.order.create_cart(
        models.OrderCartCreation(ovh_subsidiary=subsidiary, description="sdk example")
    )
    cart_id = cart.cart_id
    if not cart_id:
        raise RuntimeError("the API returned a cart with no id")
    try:
        # What the domain offers: is it free, for how long, at which price.
        offers = client.order.list_cart_domains(cart_id, domain)
        offer = next((o for o in offers if o.orderable), None)
        if offer is None:
            print(f"{domain} cannot be ordered")
        else:
            duration = offer.duration[0] if offer.duration else None
            client.order.create_cart_domain(
                cart_id, models.OrderCartGenericDomainCreation(domain=domain, duration=duration)
            )
            # The cart belongs to the account: needed before a checkout.
            client.order.assign_cart(cart_id)
            order = client.order.get_cart_checkout(cart_id)
            with_tax = order.prices.with_tax if order.prices else None
            print(f"{domain}: {with_tax.text if with_tax else ''} with tax")
    finally:
        client.order.delete_cart(cart_id)
