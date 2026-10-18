# Phase P3: Messaging

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
Outbox helper, topology script, relay with publisher confirms, email worker (Jinja2 auto-escape), notify worker, digest/scheduler worker, `email_log`, DLQ and retry queues, all templates from 9.5

## Gate (must pass before you stop)
`pytest tests/messaging -q` including the **SMTP outage drill** (stop Mailpit, enqueue, restart: no lost and no duplicate emails) and idempotent redelivery

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P4.

---

# Spec sections for this phase (copied from the full spec)

### 6.10 Outbox, notifications, email log, preferences and feedback

```sql
-- Transactional outbox: business code inserts a row in the same transaction; the relay publishes it
CREATE TABLE notification_outbox (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,         -- NULL for system or broadcast fan-out
    channel     VARCHAR(20) NOT NULL DEFAULT 'IN_APP',               -- IN_APP | EMAIL | PUSH | SMS
    routing_key VARCHAR(60) NOT NULL,                                -- email.verify, email.booking, notify.inapp ...
    template    VARCHAR(60) NOT NULL,
    params      JSONB NOT NULL,
    send_after  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at     TIMESTAMPTZ,
    attempts    INT NOT NULL DEFAULT 0,
    dedupe_key  VARCHAR(120) UNIQUE
);
CREATE INDEX idx_outbox_due ON notification_outbox (send_after) WHERE sent_at IS NULL;

CREATE TABLE notifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(150) NOT NULL,
    message    TEXT NOT NULL,
    is_read    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent consumers and delivery audit
CREATE TABLE processed_messages (
    message_id  UUID NOT NULL,
    consumer    VARCHAR(40) NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (message_id, consumer)
);
CREATE TABLE email_log (
    id           BIGSERIAL PRIMARY KEY,
    message_id   UUID NOT NULL,
    user_id      UUID,
    to_hash      CHAR(64) NOT NULL,                      -- hash of recipient, never the address in logs
    template     VARCHAR(60) NOT NULL,
    status       VARCHAR(20) NOT NULL,                   -- SENT | FAILED | BOUNCED | COMPLAINED | SUPPRESSED
    error        VARCHAR(200),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Marketing consent is separate from transactional email
CREATE TABLE notification_prefs (
    user_id        UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    channels       TEXT[] NOT NULL DEFAULT '{IN_APP,EMAIL}',
    quiet_start    TIME,
    quiet_end      TIME,
    marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE unsubscribes (
    email_hash   CHAR(64) PRIMARY KEY,
    scope        VARCHAR(20) NOT NULL DEFAULT 'MARKETING',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Quality loop: one per user per item
CREATE TABLE feedback (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type  VARCHAR(20) NOT NULL CHECK (item_type IN ('CLASS','TRAINER','AGENT_ANSWER')),
    item_id    UUID NOT NULL,
    rating     SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    reason     VARCHAR(300),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, item_type, item_id)
);
```

---

## 9. Messaging design (RabbitMQ) and SMTP

### 9.1 Topology

| Item | Design |
| :--- | :--- |
| Exchange | `gympro.events` (topic, durable). Dead-letter exchange `gympro.dlx` |
| Routing keys | `email.verify`, `email.reset`, `email.password_changed`, `email.already_registered`, `email.booking`, `email.plan`, `email.issue`, `email.trainer_decision`, `email.admin_code`, `email.admin_added`, `email.digest`, `email.broadcast`, `notify.inapp`, `issue.created`, `issue.urgent`, `class.cancelled`, `digest.daily` |
| Queues and bindings | `q.email` binds `email.#`; `q.notify` binds `notify.#`, `issue.#`, `class.cancelled`; `q.digest` binds `digest.#`; `q.agent.async` binds `agent.#` |
| Retry | Retry queues with TTL 30 s, 5 min, 30 min that dead-letter back to the work queue. After the third retry the message goes to `q.dlq` |
| Publishing | **Transactional outbox:** business code inserts a `notification_outbox` row in the same DB transaction; the relay publishes with publisher confirms and sets `sent_at`. Nothing is published before commit |
| Consuming | Manual acknowledgements, prefetch limit (10), idempotency by `message_id` in `processed_messages`, bounded retries then DLQ, correlation id and trace id in headers |
| Messages | Versioned JSON (`v: 1`). Never contain passwords or raw tokens in logs. Links inside email params are the only place a raw token appears and are removed from stored params after sending |
| Ordering | Not assumed. Consumers are idempotent and state-checking (for example the booking email worker skips if the booking is no longer CONFIRMED) |

**Message shape**

```json
{
  "v": 1,
  "message_id": "uuid (= outbox.id)",
  "routing_key": "email.booking",
  "template": "BOOKING_DETAILS",
  "user_id": "uuid|null",
  "params": {"booking_id": "uuid", "attach_calendar": true},
  "created_at": "2026-10-16T18:05:00+05:30",
  "trace_id": "string"
}
```

### 9.2 Outbox helper and relay

```python
# app/messaging/outbox.py
async def enqueue(db, *, user_id, routing_key, template, params, dedupe_key, send_after=None, channel="EMAIL"):
    await db.execute(insert(NotificationOutbox).values(
        user_id=user_id, routing_key=routing_key, template=template, params=params,
        channel=channel, dedupe_key=dedupe_key, send_after=send_after or utcnow()
    ).on_conflict_do_nothing(index_elements=["dedupe_key"]))             # same transaction as the business change

# outbox-relay process
async def relay_loop(sessionmaker, channel):                              # channel opened with confirm_delivery()
    exchange = await channel.get_exchange("gympro.events")
    while True:
        async with sessionmaker() as db, db.begin():
            await set_rls_system(db)
            rows = (await db.execute(text("""
                SELECT * FROM notification_outbox WHERE sent_at IS NULL AND send_after <= now()
                ORDER BY send_after LIMIT 100 FOR UPDATE SKIP LOCKED"""))).mappings().all()
            for r in rows:
                msg = aio_pika.Message(json.dumps(to_message(r)).encode(), content_type="application/json",
                                       delivery_mode=aio_pika.DeliveryMode.PERSISTENT, message_id=str(r["id"]),
                                       headers={"trace_id": r["params"].get("trace_id", "")})
                try:
                    await exchange.publish(msg, routing_key=r["routing_key"])    # waits for the broker confirm
                    await db.execute(text("UPDATE notification_outbox SET sent_at=now() WHERE id=:i"), {"i": r["id"]})
                except Exception:
                    await db.execute(text("UPDATE notification_outbox SET attempts=attempts+1 WHERE id=:i"), {"i": r["id"]})
        await asyncio.sleep(1.0)
```

### 9.3 Email worker

```python
# app/messaging/workers/email.py
async def handle(message: aio_pika.IncomingMessage):
    async with message.process(requeue=False):                            # ack on success; exception routes via DLX to retry
        body = json.loads(message.body)
        async with sessionmaker() as db, db.begin():
            await set_rls_system(db)
            if not await claim(db, body["message_id"], "email"):          # INSERT ... ON CONFLICT DO NOTHING on processed_messages
                return                                                     # duplicate delivery: do nothing
            user = await get_user(db, body["user_id"]) if body["user_id"] else None
            to = user.email if user else body["params"].get("email")       # the address always comes from the users row, never from an agent
            if await is_suppressed(db, to, body["template"]):              # marketing only; transactional ignores unsubscribes
                return await log_email(db, body, to, "SUPPRESSED")
            if not await still_valid(db, body):                            # state check (booking still confirmed, request still pending)
                return await log_email(db, body, to, "SUPPRESSED")
            subject, html, text_part = render(body["template"], body["params"], locale=user.locale if user else "en")  # Jinja2 autoescape
            msg = build_mime(settings.mail_from, to, subject, html, text_part,
                             ics=make_ics(body["params"]) if body["params"].get("attach_calendar") else None)
            await aiosmtplib.send(msg, hostname=settings.smtp_host, port=settings.smtp_port,
                                  username=settings.smtp_user, password=settings.smtp_password, start_tls=bool(settings.smtp_user))
            await log_email(db, body, to, "SENT")
```

**Retry flow:** a raised exception rejects the message without requeue. `q.email` has `x-dead-letter-exchange = gympro.dlx` and routing to `q.email.retry.30s`; each retry queue has `x-message-ttl` and dead-letters back to `q.email`. A header counter selects the next retry queue and after the third attempt the message is routed to `q.dlq` for manual review.

### 9.4 SMTP rules

| Rule | Detail |
| :--- | :--- |
| Development | Mailpit (single local binary, SMTP on 1025, web UI on 8025). No Docker |
| Production | Provider with SPF, DKIM and DMARC. TLS required |
| Templates | Jinja2 with auto-escaping. Plain-text alternative always included |
| Header safety | Header values are never taken from user input (prevents header injection). Subject comes from the template only |
| Links | Built from `FRONTEND_URL`, never from the request Host header |
| Transactional vs marketing | Separate templates and streams. Marketing honors `unsubscribes` and `notification_prefs.marketing_opt_in`; verification, reset and security emails always send |
| Caps | Per-user daily email cap from `gym_settings` |
| Bounces | Bounce and complaint webhooks write `email_log` and suppress future sends |
| Agent restriction | **Agents can only email the user's own verified account address.** The worker re-reads the address from `users` |
| Privacy | No health details in subjects or bodies. Logs store a hash of the recipient |

### 9.5 Email template catalog

| Template | Audience | Content (summary) |
| :--- | :--- | :--- |
| `VERIFY_EMAIL` | New user | Link valid 24 h |
| `RESET_PASSWORD` / `PASSWORD_CHANGED` | Any | Link valid 30 min / security notice with "not you?" help |
| `ALREADY_REGISTERED` | Existing email | "Someone tried to register; log in or reset" (keeps the API response identical) |
| `CLASS_CONFIRMED` / `BOOKING_DETAILS` | USER | Booking details, optional .ics |
| `WAITLIST_PROMOTED` / `CLASS_REMINDER` / `CLASS_CANCELLED` | USER | Short factual notices |
| `PLAN_CHANGED` | USER | New plan and effective date |
| `PAYMENT_RECEIPT` | USER | Amount, currency, plan, date, payment reference (no card or UPI data) |
| `PAYMENT_NEEDS_REVIEW` | Admins | Payment id and reason (late capture, plan changed); no user health or personal details |
| `ISSUE_RECEIVED` | Reporter | Acknowledgement only |
| `ISSUE_ADMIN_ALERT` | Admins | Severity, category, class label, link (no reporter identity in the email) |
| `TRAINER_DECISION` | Trainer applicant | Approved, rejected with reason, or more information requested |
| `ADMIN_CODE` | Every active admin | Who is asking, code, expiry, reject link |
| `NEW_ADMIN_ADDED` | Admins | Name, time, cooling-off notice, suspend link |
| `TRAINER_REQUESTS_DIGEST` | Admins | Batched count and link |
| `DAILY_DIGEST` | Admins | AI-written summary from tool numbers |
| `WEEKLY_SUMMARY` | USER (opt-in) | Numbers from tools |
| `BROADCAST` | Audience | Admin-approved announcement; honors unsubscribe unless essential |

---

## 14. Observability and operations

| Concern | Implementation |
| :--- | :--- |
| Tracing | One OpenTelemetry trace per chat request. Spans: guard, planner, each agent, each tool call, DB queries, bundle builder, synthesizer. Confirm endpoints and workers continue the trace through `trace_id` in message headers. Attributes: prompt versions, model, tokens, retries, validator outcomes |
| Metrics | Request rate, error rate, status distribution (OK/ESCALATE/REFUSED/ERROR), tool failure rate, retry rate, token usage, p50/p95 latency, confirmation conversion (proposed vs confirmed), bundle outcomes (EXECUTED/PARTIAL/FAILED), executor failure reasons, RabbitMQ queue depth and DLQ size, email sent/failed/bounced, login failures, pending role requests |
| Alerts | ERROR rate > 3%, validator-failure spike, safety-label drift, `booked_count` reconciliation mismatch > 0, LLM provider errors, cost anomaly, DLQ not empty, outbox lag > 2 min, refresh-token reuse spike, admin-code failures, new admin created |
| Reliability | Timeouts per agent, retry with jitter on 429/5xx, circuit breaker with graceful message, fallback to a deterministic "browse classes" path if the LLM is down, workers restart safely because consumers are idempotent |
| Data hygiene | Nightly jobs: expire pending actions and bundles, expire role requests and codes, reconcile `v_class_occupancy`, purge raw logs by retention policy, expire unverified accounts after 7 days |
| Rollout | Feature flag per agent, canary a new prompt version on 5% of traffic, one-click rollback to the previous prompt version (immutable files plus DB rows) |
| Feedback | Thumbs up or down with reason on each reply, stored with `run_id`; weekly review feeds new eval cases |
| Load | Booking executor and waitlist promotion load-tested with concurrent requests for the last spot (exactly one winner); relay and workers tested at 1,000 messages |

**Runbooks to write:** LLM outage, DB failover, RabbitMQ down (outbox keeps rows; relay resumes), SMTP outage (retry queues and DLQ replay), prompt rollback, suspected admin compromise (revoke sessions, suspend admin, rotate `token_hmac_secret`), incident review template.
