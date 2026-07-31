-- 0015_create_webhooks.sql
-- Outbound webhook subscriptions and their delivery log, org-scoped.
-- Strictly additive and idempotent (CREATE ... IF NOT EXISTS), so re-running is a no-op and no
-- prior-phase column is altered or dropped.
--
-- Why the signing secret is stored as-is, unlike an API key:
--   an API key is *verified* against an argon2 hash, so the platform never needs the original.
--   A webhook signature must be *produced*, which requires the secret itself. It is therefore
--   stored, returned exactly once at creation, excluded from every response model, and never
--   logged. This asymmetry is deliberate and documented in docs/KNOWN_LIMITATIONS.md.
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id          UUID PRIMARY KEY,
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    -- The events this subscription wants, from the vocabulary in webhooks/base.py. A TEXT[]
    -- rather than a join table: the set is small, always read whole, and never queried by
    -- element outside `= ANY(...)`.
    events      TEXT[] NOT NULL DEFAULT '{}',
    secret      TEXT NOT NULL,
    description TEXT,
    -- Disabled subscriptions are kept, not deleted: pausing a noisy endpoint should not lose
    -- its delivery history or force the consumer to re-key.
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS webhook_subscriptions_org_idx
    ON webhook_subscriptions (org_id, created_at DESC);

-- One row per (event, subscription) attempt sequence — not per HTTP attempt. `attempts`
-- records how many were needed, which is what an operator debugging a flaky endpoint reads.
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              UUID PRIMARY KEY,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- CASCADE: a delivery log for a subscription that no longer exists has no reader, and the
    -- audit trail independently records that the subscription was deleted and by whom.
    subscription_id UUID NOT NULL REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('delivered', 'failed')),
    attempts        INTEGER NOT NULL CHECK (attempts >= 1),
    -- The endpoint's HTTP status, or NULL when no response was obtained (DNS, TLS, timeout).
    response_status INTEGER,
    -- A short, truncated diagnostic. Never a response body: a tenant's endpoint may echo
    -- material this platform has no business storing.
    error           TEXT,
    duration_ms     INTEGER CHECK (duration_ms >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- The only read pattern: one subscription's log, newest first, with the (created_at, id)
-- keyset the API paginates on.
CREATE INDEX IF NOT EXISTS webhook_deliveries_sub_time_idx
    ON webhook_deliveries (subscription_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS webhook_deliveries_org_time_idx
    ON webhook_deliveries (org_id, created_at DESC, id DESC);
