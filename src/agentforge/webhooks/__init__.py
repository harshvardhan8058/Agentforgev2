"""Outbound webhooks: subscriptions, signed delivery, and the delivery log.

The package the platform needed to stop being silent. Read in this order:

* :mod:`agentforge.webhooks.base` — the event vocabulary, the subscription and delivery
  records, and the transport seam.
* :mod:`agentforge.webhooks.security` — URL admission (SSRF defence) and HMAC signing.
* :mod:`agentforge.webhooks.store` — persistence, in-memory and Postgres.
* :mod:`agentforge.webhooks.transport` — the HTTP transport and its recording double.
* :mod:`agentforge.webhooks.emitter` — bounded, logged fan-out that can never fail its caller.
* :mod:`agentforge.webhooks.events` — the payload of each event, defined once.
"""

from __future__ import annotations

from agentforge.webhooks.base import (
    SUBSCRIBABLE_EVENTS,
    Subscribable_Event,
    Transport_Result,
    Webhook_Delivery,
    Webhook_Event,
    Webhook_Subscription,
    Webhook_Transport,
)

__all__ = [
    "SUBSCRIBABLE_EVENTS",
    "Subscribable_Event",
    "Transport_Result",
    "Webhook_Delivery",
    "Webhook_Event",
    "Webhook_Subscription",
    "Webhook_Transport",
]
