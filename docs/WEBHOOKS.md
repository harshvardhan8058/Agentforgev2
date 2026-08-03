# Webhooks

AgentForge POSTs a signed JSON event to an HTTPS endpoint you register when something happens in
your organization: a run finishes, a document is ingested, a guardrail refuses a request, or you
cross a spend threshold.

This document is the consumer's contract. Everything in it is exercised by the test suite —
including the verification recipe below, which is the platform's own
`agentforge.webhooks.security.verify_signature`.

---

## 1. Register an endpoint

Requires the `manage_webhooks` permission (granted from **admin** upwards), or use the
**Webhooks** page in the console.

```bash
curl -sS -X POST https://your-agentforge/webhooks \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "url": "https://hooks.example.com/agentforge",
        "events": ["run.completed", "run.failed", "budget.threshold_crossed"],
        "description": "Ops alerting",
        "active": true
      }'
```

```json
{
  "webhook": {
    "webhook_id": "0f9c…",
    "url": "https://hooks.example.com/agentforge",
    "events": ["run.completed", "run.failed", "budget.threshold_crossed"],
    "description": "Ops alerting",
    "active": true,
    "created_at": "2026-08-03T09:12:44.201Z",
    "updated_at": "2026-08-03T09:12:44.201Z"
  },
  "secret": "whsec_…",
  "secret_note": "Store this now: the signing secret is shown once and cannot be retrieved again."
}
```

**Store `secret` now.** It is returned by this response and by nothing else — no list, no
detail, no update, no log line. If you lose it, delete the subscription and register a new one
(there is no rotation endpoint; adding one would need its own response shape).

### What URLs are accepted

A webhook URL is an address *the server* then fetches, so admission is strict. Every rule below
is applied at registration **and again immediately before each delivery**, because a hostname
that pointed somewhere public last week can point inside the network today.

| Rule | Why |
| --- | --- |
| `https` only | Deliveries are signed, not encrypted by the signature. `http` is accepted only for loopback, and only outside the production profile, so a developer can test locally. |
| No credentials in the URL (`user:pass@`) | The request is authenticated by its signature. Credentials in a URL also make the address a reviewer reads differ from the one dialled. |
| No fragment | Never sent, and a way to hide the real target. |
| No scheme/port contradiction (`https://…:80`, `http://…:443`) | Far more likely a mistake or a smuggling attempt than a real endpoint. Other ports, including `:8443`, are fine. |
| Every resolved address must be **globally routable** | This is the SSRF defence. It excludes loopback, RFC1918, link-local (`169.254.0.0/16`, so cloud metadata is unreachable), CGNAT `100.64.0.0/10`, IPv4-mapped IPv6, and the documentation/benchmarking ranges — as an allow-list, so a range nobody enumerated is still excluded. |
| Redirects are **not followed** | Otherwise a public URL could hand off to a private one after admission. |
| At most 2048 characters | A URL is stored, rendered, and logged. |

A refusal is `400 invalid_webhook_url` with the rule that was broken. It never names the address
your hostname resolved to — that would make the endpoint a scanner for the deployment's private
network.

---

## 2. Verify the signature

Every delivery carries these headers:

| Header | Meaning |
| --- | --- |
| `X-AgentForge-Signature` | `t=<unix seconds>,v1=<hex hmac-sha256>` |
| `X-AgentForge-Event` | The event name, e.g. `run.completed` |
| `X-AgentForge-Delivery` | Delivery id — stable across every retry of this queued event |
| `X-AgentForge-Attempt` | Which attempt this is, 1-based |
| `X-AgentForge-Idempotency-Key` | **The value to deduplicate on.** Absent for events with no natural identity |
| `X-AgentForge-Webhook-Id` | Which of your subscriptions this is |

The signed material is `"<t>." + <raw request body>`. The timestamp is inside it, so a captured
request cannot be replayed later without the signature also being wrong.

```python
import hashlib
import hmac
import time


def verify(secret: str, body: bytes, header: str, tolerance_seconds: int = 300) -> bool:
    fields = dict(
        part.strip().split("=", 1) for part in header.split(",") if "=" in part
    )
    timestamp, provided = fields.get("t"), fields.get("v1")
    if not timestamp or not provided:
        return False
    if abs(int(time.time()) - int(timestamp)) > tolerance_seconds:
        return False  # too old (or too far in the future) to accept
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)  # not `==`
```

Three details that are easy to get wrong:

1. **Verify against the raw body bytes.** Re-serialising the parsed JSON changes them.
2. **Use a constant-time comparison.** `==` on a hex digest leaks timing.
3. **Enforce the timestamp window** (300s is what the platform's own verifier defaults to).
   Without it the timestamp is decoration.

---

## 3. Events

The envelope is the same for every event:

```json
{
  "id": "3f6b…",
  "event": "run.completed",
  "created_at": "2026-08-03T09:14:02.881Z",
  "org_id": "8a21…",
  "data": { }
}
```

`id` equals the `X-AgentForge-Delivery` header. `idempotency_key` is the **logical identity of what
happened**, and it is the field to deduplicate on:

| | `id` / `X-AgentForge-Delivery` | `idempotency_key` |
| --- | --- | --- |
| Stable across retries of the same queued event | yes | yes |
| Stable across a *repeated occurrence that means the same thing* | no | yes |

The second row is why both exist. Delivery is **at-least-once**, and a repeat can reach you for
reasons that are not retries: a worker delivered and then died before recording the success, an
operator redelivered an abandoned event, a multi-agent run was re-streamed (which genuinely re-runs
it), or a budget threshold was re-announced after an outage. All of those carry the same
`idempotency_key` and a different `id`. Store the key and ignore what you have already processed.

Events with no natural identity — `guardrail.blocked`, which is a fact about a moment rather than
about an entity — carry `null`, deliberately, rather than a fabricated value that would suggest
deduplication is possible when it would lose information.

Payloads carry **identifiers and outcomes, never content.** A run's answer, a document's text
and a blocked prompt are all absent: a webhook crosses the trust boundary to an endpoint the
platform does not control, so its job is to tell you something happened. Come back through the
authenticated API for the details.

### `run.completed` / `run.failed`

`run.completed` means the run produced an accepted result. `run.failed` means it reached a
terminal state **without** one — an iteration or round bound, a critique past the revision
bound, or an abort. A request that *raised* emits nothing: it already told its caller, and
emission is deliberately off the request path.

```json
{
  "run_id": "…",
  "kind": "agent",
  "conversation_id": "…",
  "termination_reason": "final-answer",
  "citation_count": 3
}
```

`kind` is `agent` or `multi_agent`. Every key is always present, `null` where the fact does not
apply, so one parser handles the event whichever surface produced it.

### `document.ingested`

```json
{ "document_id": "…", "filename": "notes.md", "chunk_count": 12, "duplicate": false }
```

`duplicate: true` means those exact bytes were already in your corpus and `document_id` is the
document they matched. Reported rather than suppressed, because a consumer that indexes on
ingestion needs the difference.

### `guardrail.blocked`

```json
{ "surface": "query", "reason": "input matched a blocked term" }
```

`surface` is `query`, `agent.run`, or `multi_agent.run`. Only **input** guardrails on the
non-streaming endpoints emit: the streaming endpoints do not run input guardrails at all, and
output guardrails flag rather than block. `reason` is the guardrail's own explanation — the same
text the refused caller received — and never the content that was blocked.

### `budget.threshold_crossed`

```json
{
  "threshold_percent": 80,
  "spent": "84.51230000",
  "limit_amount": "100",
  "percent_used": "84.51",
  "period_start": "2026-08-01T00:00:00+00:00",
  "period_end": "2026-09-01T00:00:00+00:00",
  "blocked": false
}
```

Thresholds are **80** and **100** percent of the monthly ceiling, each announced separately, so
an organization that jumps from 40% to 120% in one request is told about both. `blocked`
distinguishes "you are being warned" from "your runs are being refused right now".

Monetary values are exact decimal **strings** — parse them as decimals, not floats. Two
behaviours worth designing around:

- **Deduplicate on `(period_start, threshold_percent)`, not only on the delivery id.** The claim
  that makes this once-per-period is released when a delivery demonstrably failed, so a
  consumer that processed a request whose response timed out can receive a second notification
  with a *different* delivery id. At-least-once is the deliberate choice: losing the alert is
  worse than repeating it.
- **A zero ceiling reports `percent_used: "100"` with `spent` and `limit_amount` both `"0"`.**
  A budget of zero means "spend nothing", so both thresholds fire on the first request. Do not
  recompute the percentage yourself — you would divide by zero.

### `webhook.ping`

Sent only by `POST /webhooks/{id}/test`. Not subscribable, because nothing else ever emits it.

---

## 4. Delivery behaviour

Deliveries are **durable**. An event is written to a queue in the same request that produced it,
before anything is dialled, and a worker drains that queue. So a deploy, a crash, or a consumer
that is down for an hour does not lose events — it delays them.

| Property | Value |
| --- | --- |
| Attempts | `WEBHOOK_MAX_ATTEMPTS` (default 8) |
| Per-attempt timeout | `WEBHOOK_TIMEOUT_SECONDS` (default 4) |
| Retry schedule | Exponential from `WEBHOOK_BACKOFF_SECONDS` (default 60s): 1m, 2m, 4m, 8m, 16m, 32m, 1h4m — capped at 6h |
| Total window | Roughly a day with the defaults |
| Success | Any `2xx` |
| Response body | **Never read.** Reply with an empty `2xx`; a body is ignored and not held in memory. |
| Subscriptions per org | `WEBHOOK_MAX_PER_ORG` (default 20) |
| Guarantee | **At-least-once.** Deduplicate on `idempotency_key`. |

Answer quickly and do the work asynchronously — the platform gives up on a single attempt in a few
seconds, and then simply tries again later.

Two behaviours that follow from durability:

- **Pausing a subscription holds its events rather than dropping them.** Resume it and what it
  missed is delivered (subject to the attempt window). Deleting it discards them, because there is
  then no endpoint and no secret to sign with.
- **After the schedule is exhausted an event is *abandoned*, not silently dropped.** It stays
  visible on `GET /webhooks/queue` and can be redelivered explicitly. Nothing disappears without
  somebody being able to see that it did.

---

## 5. The delivery log

```bash
curl -sS "https://your-agentforge/webhooks/$ID/deliveries?limit=25" \
  -H "Authorization: Bearer $TOKEN"
```

One row per event per subscription — the attempt *sequence*, not each HTTP attempt:

```json
[
  {
    "delivery_id": "…",
    "webhook_id": "…",
    "event": "run.completed",
    "status": "delivered",
    "attempts": 2,
    "response_status": 200,
    "error": null,
    "duration_ms": 173,
    "created_at": "2026-08-03T09:14:03.114Z"
  }
]
```

- `response_status: null` means no response was ever obtained (DNS failure, refused connection,
  timeout) — which is a different problem from "your endpoint said 500".
- `duration_ms` covers HTTP work only, **excluding** the backoff between retries, so it answers
  "how slow is my endpoint".
- Page with the keyset cursor: send both `before` (the last row's `created_at`) **and**
  `before_id` (its `delivery_id`). A timestamp alone cannot separate deliveries that share it,
  and one fan-out writes several in the same millisecond.

Deleting a subscription deletes its delivery log with it. That is also the only way to remove
that history.

---

## 5a. The delivery queue

What has not arrived yet, and what gave up trying.

```bash
curl -sS "https://your-agentforge/webhooks/queue?status=abandoned" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "pending": 12,
  "abandoned": 1,
  "entries": [
    {
      "entry_id": "…",
      "webhook_id": "…",
      "event": "run.completed",
      "status": "abandoned",
      "attempts": 8,
      "next_attempt_at": "2026-08-03T18:02:11.004Z",
      "last_error": "ConnectTimeout: the endpoint did not answer",
      "idempotency_key": "run.completed:abc:…",
      "created_at": "2026-08-03T09:14:02.881Z",
      "updated_at": "2026-08-03T18:02:11.004Z"
    }
  ]
}
```

`pending` and `abandoned` count the whole queue, not the returned page, so the totals stay honest
while you page through. Delivered events are **not** listed here — that is what each subscription's
delivery log is for, and answering "did it arrive" in two places invites the two answers to
disagree.

Put an abandoned event back in the queue, due immediately, with a fresh schedule:

```bash
curl -X POST "https://your-agentforge/webhooks/queue/$ENTRY_ID/redeliver" \
  -H "Authorization: Bearer $TOKEN"
```

Only **abandoned** entries can be redelivered; a pending one is already scheduled, so requeueing it
would ask for the same event twice, and the API says so with a `409 not_redeliverable`. Redeliveries
are audited (`webhook.redelivered`), because a human choosing to re-send something the platform gave
up on is exactly the kind of action somebody asks about later.

The **Webhooks** page in the console shows the same thing, with a Redeliver button on anything that
gave up.

---

## 6. Managing a subscription

```bash
# Pause without losing the secret your consumer already verifies against
curl -X PATCH …/webhooks/$ID -d '{"active": false}'

# Re-point, re-subscribe, clear the description (null clears; omitting leaves it alone)
curl -X PATCH …/webhooks/$ID -d '{"url": "https://new.example.com/h", "description": null}'

# Prove an endpoint works before real events depend on it (one attempt, works while paused)
curl -X POST …/webhooks/$ID/test

# Remove it and its delivery log
curl -X DELETE …/webhooks/$ID
```

`PATCH` applies only the fields present in the body. `POST /webhooks/{id}/test` returns the same
delivery shape as the log, synchronously — a non-2xx from your endpoint is reported as
`status: "failed"` in a `200` response, because the request succeeded and the bad news is what
you asked for.

---

## 7. Security notes worth knowing

- **The signing secret is stored recoverably**, unlike an API key (which is Argon2-hashed).
  A hash cannot sign an outgoing request. The once-only exposure is therefore an application
  guarantee, not a cryptographic one — the same trade-off Stripe and GitHub make, and it is
  written down in `docs/KNOWN_LIMITATIONS.md` rather than implied to be stronger.
- **The audit trail records the URL's origin only** (`https://hooks.example.com`), never its
  path or query, because a webhook URL's path routinely *is* a credential.
- **Delivery is at-least-once, not exactly-once.** Exactly-once would need a distributed
  transaction with an endpoint the platform does not control. Deduplicate on `idempotency_key`.
- **DNS rebinding is not closed.** Between the admission check and the connect, DNS can change.
  Closing it means connecting to a pinned, pre-validated IP with the hostname in SNI plus
  `Host`, which the HTTP client here cannot express.
- Reads of the delivery log require `manage_webhooks` rather than plain `read`, because a
  failure summary can quote a TLS error or an internal hostname from your own infrastructure.
