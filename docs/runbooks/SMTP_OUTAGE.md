# Runbook: SMTP Outage, Retry Queues & Dead-Letter Queue (DLQ) Replay

## Severity: MEDIUM (P2)
**Primary Symptoms:**
- Alert `DLQ not empty` or `email failed / bounced spike`.
- Messaging worker logs showing connection refused or 4xx/5xx SMTP errors from upstream relay (SES / SendGrid / Mailgun).
- Users not receiving verification OTPs or booking receipts.

---

## Architectural Resilience: Phased Retry & Dead-Letter Queues
The messaging consumer implements a 3-tier backoff and DLQ routing:
1. **Immediate Retry (30s):**
   - Transient network glitches or temporary SMTP rate limits retry after 30 seconds.
2. **Intermediate Retry (5m):**
   - Secondary failure moves the message to the 5-minute delayed queue.
3. **Tertiary Retry (30m):**
   - Sustained outages route message to 30-minute queue.
4. **Dead-Letter Queue (DLQ):**
   - After maximum retry attempts (default: 5), the message is safely diverted to `email_notifications_dlq` without dropping the message.

---

## Diagnostic Steps
1. **Check Downstream SMTP Provider Status:**
   - Inspect upstream SMTP status page (SendGrid / AWS SES / Mailgun).
   - Check local Mailpit in dev/staging: `http://localhost:8025`.
2. **Inspect DLQ Backlog:**
   ```bash
   rabbitmqctl list_queues name messages messages_ready | grep dlq
   ```
3. **Inspect Failed Email Payloads in DB Outbox:**
   ```sql
   SELECT id, event_type, payload, status, retry_count, last_error
   FROM outbox
   WHERE event_type = 'EMAIL_NOTIFICATION' AND status = 'FAILED'
   ORDER BY created_at DESC LIMIT 20;
   ```

---

## Remediation Steps
1. **Restore SMTP Connectivity:**
   - If credentials expired or IP blocked, rotate `SMTP_USER` / `SMTP_PASSWORD` in `.env`.
   - If primary SMTP is unrecoverable, switch to fallback SMTP provider in `.env` and restart messaging workers:
     ```bash
     docker compose restart worker_messaging
     ```
2. **Replay Dead-Letter Queue (DLQ):**
   - Run the DLQ replay tool:
     ```bash
     python -m app.messaging.dlq_replay --queue email_notifications_dlq --batch 50
     ```
   - Or via RabbitMQ Shovel plugin:
     ```bash
     rabbitmqctl set_parameter shovel dlq_replay '{"src-uri": "amqp://", "src-queue": "email_notifications_dlq", "dest-uri": "amqp://", "dest-queue": "email_notifications"}'
     ```
3. **Verify Delivery:**
   - Check logs of `worker_messaging` for successful `250 Message queued for delivery`.
   - Confirm DLQ message count drops to 0.

---

## Post-Incident
- Verify all pending customer notifications and password reset tokens have been delivered.
- Check recipient bounce rate to prevent domain reputation damage.
