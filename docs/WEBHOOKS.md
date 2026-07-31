# AgentForge Webhooks

> Outbound, signed, org-scoped event delivery. Register an https endpoint, choose the events you
> want, and AgentForge POSTs a signed JSON envelope when they happen — with every attempt
> recorded in a delivery log you can read.
>
> Companion documents: `docs/CONFIGURATION.md` (delivery bounds), `docs/KNOWN_LIMITATIONS.md`
> (what this deliberately does not do), `docs/ARCHITECTURE_OVERVIEW.md` (where the seam sits).

## Why webhooks exist here

Three features already produced facts that somebody outside the console needed to hear about — a
run finishing, a guardrail refusing an input, a document finishing ingestion — and the only way
to learn any of them was to be looking at a page. Polling `GET /agent/runs` is the workaround,
and it is the wrong shape: it costs a request per interval per tenant to learn nothing most of
the time.

## Quick start

```bash
# 1. Register an endpoint. The response is the ONLY place the signing secret appears.
curl -sX POST https://agentforge.example.com/webhooks \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"url":"https://hooks.acme.example/agentforge",
       "events":["run.completed","guardrail.blocked"],
       "description":"Ops channel"}'
# => 201 {"webhook_id":"…","secret":"whsec_…", …}   ← store the secret now

# 2. Prove your endpoint works, before real traffic depends on it.
curl -sX POST https://agentforge.example.com/webhooks/$WEBHOOK_ID/test \
  -H "Authorization: Bearer $TOKEN"
# => 200 {"status":"delivered","response_status":200,"attempts":1, …}
#    A refusal is ALSO a 200 — the delivery outcome is the payload, not an error.

# 3. Read the log when something looks wrong.
curl -s "https://agentforge.example.com/webhooks/$WEBHOOK_ID/deliveries?limit=25" \
  -H "Authorization: Bearer $TOKEN"
```

An organization may register at most **20** endpoints; past that, `POST /webhooks` answers
`409 webhook_limit_reached`. This is not a display bound — every emitted event fans out to every
active subscription, each with its own retry budget — so it is enforced rather than assumed.

All six endpoints require the **`manage_webhooks`** permission, granted from `admin` upwards.
Every one is scoped to the caller's organization by construction: the store takes the
principal's `org_id`, there is no org parameter to tamper with, and another tenant's webhook id
is a `404` indistinguishable from one that does not exist.

## Events

The vocabulary is closed and published in the OpenAPI contract, so a client's event picker is
generated rather than hardcoded. Every event is **single-shot**: it describes something that
happened once, at a point in time.

| Event | Fires when | Payload (`data`) |
|---|---|---|
| `run.completed` | A run produced its result (`final-answer` for a single-agent run, `completed` for a multi-agent one) | `run_id`, `kind`, `termination_reason`, `conversation_id`, `citation_count` |
| `run.failed` | A run ended **without** an accepted result — an iteration or round limit, a rejected or aborted plan | same fields; `termination_reason` says which |
| `document.ingested` | A document finished ingestion | `document_id`, `filename`, `chunk_count`, `duplicate` |
| `guardrail.blocked` | A guardrail refused an input before it reached a model | `stage`, `surface` (`query` / `agent.run` / `multi_agent.run`), `reason` |
| `webhook.ping` | Only from `POST /webhooks/{id}/test`. **Not subscribable** — it is addressed at one endpoint on demand | `message`, `webhook_id` |

`kind` is `single_agent` or `multi_agent`, so a consumer routes on one field instead of
inferring from which optional keys are present. **Every key listed for an event is always
present**, with an explicit `null` where the emitting endpoint does not know the value — one
event name never carries two shapes, and you never have to distinguish "no citations" from "not
reported".

`guardrail.blocked` fires from `/query`, `/agent/run` and `POST /multi-agent/runs`. It does not
fire from the two streaming endpoints, because those run no input guardrail at all — worth
knowing if you are correlating on `surface`, and recorded in `docs/KNOWN_LIMITATIONS.md`.

**What payloads deliberately do not carry.** No agent answer, no document text, no blocked
input. A webhook endpoint lives outside this platform's trust boundary and outside your own
console auth; a run's answer may quote your private corpus, and a blocked input is by definition
what a guardrail judged hostile. You get an identifier and fetch the content through the
authenticated API if you are entitled to it.

## The delivery envelope

```http
POST /agentforge HTTP/1.1
Content-Type: application/json
User-Agent: AgentForge-Webhooks/1
X-AgentForge-Event: run.completed
X-AgentForge-Delivery: 6f1e…            ← unique per delivery; deduplicate on it
X-AgentForge-Webhook-Id: aaaa…          ← which subscription this is
X-AgentForge-Signature: t=1785312000,v1=9f86d0…

{"created_at":"2026-07-31T12:00:00+00:00","data":{"citation_count":2,"conversation_id":"c-1",
"kind":"single_agent","run_id":"r-1","termination_reason":"final-answer"},"event":"run.completed",
"id":"6f1e…","org_id":"1111…","webhook_id":"aaaa…"}
```

The body is serialised with sorted keys and no whitespace, deterministically. That matters: the
signature covers exactly these bytes, and determinism means a consumer who re-serialises the
parsed JSON before verifying still computes the same MAC.

## Verifying a signature

`X-AgentForge-Signature: t=<unix seconds>,v1=<hex>` where the MAC is
`HMAC-SHA256(secret, "<t>.<raw body>")`. The timestamp is **inside** the signed material, so a
consumer that rejects old timestamps also rejects replays of a captured delivery. This is the
scheme Stripe and GitHub use — deliberately not a bespoke one you would have to be taught.

```python
import hashlib, hmac, time

def verify(secret: str, body: bytes, header: str, tolerance_seconds: int = 300) -> bool:
    """Verify an AgentForge delivery. `body` MUST be the raw request bytes."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    timestamp, mac = parts.get("t"), parts.get("v1")
    if not timestamp or not mac:
        return False
    if abs(int(time.time()) - int(timestamp)) > tolerance_seconds:
        return False   # too old (or too far in the future) — reject the replay
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, mac)   # constant-time, always
```

This is not prose: the same function ships as `verify_signature()` in
`src/agentforge/webhooks/security.py` and is covered by
`tests/unit/test_webhook_security.py`, so the format above cannot drift from the wire.

```javascript
// Node — read the RAW body; a JSON body-parser has already discarded the exact bytes.
import { createHmac, timingSafeEqual } from "node:crypto";

export function verify(secret, rawBody, header, toleranceSeconds = 300) {
  const parts = Object.fromEntries(
    header.split(",").map((p) => p.split("=", 2)).filter((p) => p.length === 2),
  );
  const t = Number(parts.t);
  if (!t || !parts.v1) return false;
  if (Math.abs(Date.now() / 1000 - t) > toleranceSeconds) return false;
  const expected = createHmac("sha256", secret)
    .update(Buffer.concat([Buffer.from(`${t}.`), rawBody]))
    .digest("hex");
  const a = Buffer.from(expected), b = Buffer.from(parts.v1);
  return a.length === b.length && timingSafeEqual(a, b);
}
```

## What your endpoint should do

1. **Read the raw bytes before parsing.** Verification is over the exact body sent.
2. **Verify, then return 2xx quickly.** Any `2xx` is success; everything else is retried. Do the
   work asynchronously — the per-attempt timeout is `WEBHOOK_TIMEOUT_SECONDS` (default `4`).
3. **Deduplicate on `X-AgentForge-Delivery`.** A retry after your endpoint accepted-but-timed-out
   delivers the same event twice. Delivery is at-least-once, not exactly-once.
4. **Do not rely on ordering.** Two events emitted close together may arrive in either order.
5. **Return nothing useful.** The response body is never read or stored — only the status.

## Retries and the delivery log

An event is delivered with up to `WEBHOOK_MAX_ATTEMPTS` attempts (default `3`) and exponential
backoff (`WEBHOOK_BACKOFF_SECONDS`, default `0.5` → `0.5s`, `1.0s`). One row is written to the
delivery log per **(event, subscription)** — not per HTTP attempt — carrying `attempts`, the
endpoint's `response_status`, a short `error`, and `duration_ms`. `attempts > 1` with
`delivered` is how you spot a flaky consumer.

`duration_ms` counts only time spent talking to your endpoint, summed across attempts. AgentForge's
own backoff is excluded, so a fast endpoint that returns `500` three times reports single-digit
milliseconds rather than the thirteen seconds the whole sequence took.

`response_status` is `null` when no response was obtained at all — DNS failure, TLS failure,
timeout, refused connection — which is exactly the case `error` explains. `error` is a bounded
diagnostic and **never** a response body.

Emission is always off the request path (a FastAPI background task, or the hook after a stream's
terminal frame), so a slow endpoint of yours never slows a run of theirs. Delivery failure is
recorded and logged; it can never turn a completed run into a failed request.

## Which URLs are accepted

A webhook URL is attacker-controlled by construction — anyone who can manage webhooks supplies
it, and the platform then makes a request to it from inside its own network. That is textbook
SSRF, so admission is strict and all of the following must hold:

- **https only.** (`http` is permitted for a loopback host outside the production profile, so a
  developer can point a subscription at `http://localhost:9000` while building one.)
- **No credentials in the URL, no fragment, and the default port for that scheme** — `443` for
  `https`, `80` for `http`, paired with the scheme rather than pooled, so `https://host:80` is
  refused too.
- **Every resolved address must be globally routable unicast.** The host is resolved and refused
  if *any* answer is loopback, private, link-local (where cloud metadata services live),
  CGNAT/shared space, reserved, unspecified, or multicast. An allow-list, not a deny-list: a
  hand-written list of "internal" ranges keeps missing ones.
- **Re-checked at delivery time**, not only at registration, because DNS is mutable.
- **Redirects are not followed**, so a `302` cannot walk a validated request to an unvalidated
  address.

A refusal is `400 invalid_webhook_url` with the reason, at both create and update — including for
a malformed URL (a port outside `0-65535`, a DNS label over 63 characters), which is the caller's
to fix and never a `500`. The resolved address is never echoed back: that is the platform's
internal topology.

The audit trail records the **scheme, host and path** of a webhook URL, never its query string.
Webhook URLs are frequently themselves bearer credentials (`?token=…`, a Slack
`services/T…/B…/…` endpoint), and audit rows are readable by every auditor an organization
invites.

## The signing secret

Returned **once**, by `POST /webhooks`, and by no other endpoint: `WebhookSubscriptionResponse`
has no `secret` field at all, so a listing, a read-back after an update, or a delivery log
cannot leak it — not because each handler remembers to strip it, but because the shape it would
have to travel in does not have the field.

If the audit write for a registration fails (a deployment running `AUDIT_LOG_REQUIRED=true`
during an audit-store outage), the subscription is **deleted again** before the error is returned.
Otherwise you would be left with a live endpoint signing with a secret this response never
disclosed and no endpoint can ever show you.

There is **no rotation endpoint**, deliberately. Silently re-keying would break your endpoint
with no way for you to notice except failing verification; doing it properly needs an overlap
window where both the old and new secret verify, which is a feature, not a field. If a secret is
lost or leaked: delete the subscription and register it again.

Unlike an API key — which is verified against an argon2 hash, so the platform never needs the
original — a webhook signature must be *produced*, which requires the secret itself. It is
therefore stored as-is. See `docs/KNOWN_LIMITATIONS.md` for the full statement of that
asymmetry.

## Managing subscriptions

`PATCH /webhooks/{id}` is a partial update: send only what changes. Pausing (`active: false`)
keeps the subscription and its delivery history, so silencing a noisy endpoint does not mean
re-keying it later. `POST /webhooks/{id}/test` works on a paused endpoint — verifying one before
resuming it is exactly when that is useful.

`DELETE /webhooks/{id}` removes the subscription and its delivery log (the log has no reader
without it). The audit trail independently records `webhook.created`, `webhook.updated` and
`webhook.deleted` — who pointed a webhook where, and when — so the deletion remains accountable.
A test send is **not** audited: it changes nothing.
