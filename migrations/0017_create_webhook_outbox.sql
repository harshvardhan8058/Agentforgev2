-- 0017_create_webhook_outbox.sql
-- Durable webhook delivery: one row per (event, subscription) awaiting delivery.
-- Strictly additive and idempotent (CREATE ... IF NOT EXISTS), so re-running is a no-op.
--
-- Until now delivery was in-process and best-effort: the emitter POSTed inside a background
-- task, retried two or three times over a few seconds, and a deploy in the middle of that lost
-- the event. That is the difference between "we send webhooks" and "we deliver webhooks", and it
-- is the gap every comparable product (Stripe, GitHub, Shopify) closes the same way — write the
-- intent to durable storage in the transaction that produced it, and let a worker drain it.
--
-- This table IS that intent. It is deliberately not a generic job queue: the schema knows it is
-- carrying webhooks, so the worker needs no dispatch table and a stuck row can be understood by
-- a human reading it.
CREATE TABLE IF NOT EXISTS webhook_outbox (
    -- Also the delivery id sent as `X-AgentForge-Delivery` and echoed in the envelope's `id`,
    -- so a consumer deduplicating retries and an operator reading this table are looking at the
    -- same identifier. Allocated at enqueue time and stable for the life of the entry.
    id                UUID PRIMARY KEY,
    org_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- CASCADE: an undelivered event for a deleted subscription has nowhere to go.
    subscription_id   UUID NOT NULL
                      REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    event             TEXT NOT NULL,
    -- The rendered `data` object, stored so the payload a consumer eventually receives is the
    -- one the platform decided to send — not a re-derivation from state that has since moved on.
    -- JSONB rather than TEXT because an operator debugging a stuck row wants to query into it.
    payload           JSONB NOT NULL,
    -- The logical identity of the event, stable across every retry AND across a genuinely
    -- repeated occurrence that means the same thing (a re-streamed run, a budget threshold
    -- re-announced after a delivery outage). This is what a consumer should deduplicate on;
    -- `id` only dedupes retries of one attempt sequence. NULL for events with no natural
    -- identity, such as a guardrail block.
    idempotency_key   TEXT,
    -- pending   -> awaiting its next attempt
    -- delivered -> a 2xx was received; kept briefly for the delivery log's benefit
    -- abandoned -> the attempt schedule was exhausted; requires a human or a redelivery
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'delivered', 'abandoned')),
    attempts          INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    -- When this row becomes eligible. Set to now() at enqueue (first attempt is immediate) and
    -- pushed out by the exponential schedule after each failure, which is what lets retries
    -- span hours instead of the seconds an in-process loop could afford.
    next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A lease, so several application instances can drain the same table without two of them
    -- delivering the same event. Claiming sets it; a worker that dies leaves a lease that simply
    -- expires, and the row is picked up again — at-least-once, never lost.
    leased_until      TIMESTAMPTZ,
    last_error        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The worker's only query: "which rows are due?". Partial on `status = 'pending'` because
-- delivered and abandoned rows are the overwhelming majority over time and are never scanned
-- for work, so keeping them out of the index keeps it small and the claim fast.
CREATE INDEX IF NOT EXISTS webhook_outbox_due_idx
    ON webhook_outbox (next_attempt_at)
    WHERE status = 'pending';

-- For the operator-facing "what is stuck for this tenant" question, and for the prune job that
-- removes settled rows.
CREATE INDEX IF NOT EXISTS webhook_outbox_org_status_idx
    ON webhook_outbox (org_id, status, created_at DESC);
