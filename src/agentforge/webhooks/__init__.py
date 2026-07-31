"""Webhook_Layer — outbound, signed, org-scoped event delivery.

Three features already produced facts that somebody outside the console needed to hear about
— a run finishing, a guardrail refusing an input, a document finishing ingestion — and the
only way to learn any of them was to be looking at a page. This package is the one seam that
serves all of them, and the shape every comparable platform settles on: a tenant registers a
URL and the events it wants, the platform POSTs a signed JSON envelope, and every attempt is
recorded in a log the tenant can read.

Module map (each file has one job):

* ``base.py`` — the event vocabulary, the domain records, and the three abstract seams
  (subscription store, delivery store, transport).
* ``security.py`` — everything a hostile input can reach: URL admission (SSRF defence) and
  HMAC request signing.
* ``store.py`` — in-memory and Postgres implementations of both stores.
* ``transport.py`` — the real HTTP transport, with redirects disabled and every limit bounded.
* ``emitter.py`` — the application service: match subscriptions, sign, deliver with bounded
  retries, record the outcome, and never let any of that reach the caller.
"""

from __future__ import annotations

__all__: list[str] = []
