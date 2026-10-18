# Runbook: RabbitMQ Broker Downtime & Outbox Relay Recovery

## Severity: HIGH (P1)
**Primary Symptoms:**
- Alert `RabbitMQ queue depth > threshold` or publisher connection timeouts.
- Outbox relay service logging `AMQPConnectionError` or unable to connect to `amqp://...`.
- Alert `outbox lag > 2 min` on Prometheus metrics.

---

## Architectural Resilience: The Transactional Outbox Pattern
GymPro AI is architected with a **Transactional Outbox**:
1. **Zero Message Loss:**
   - Application writes do NOT publish directly to RabbitMQ in the user request path.
   - All events (booking confirmations, emails, notifications, payment states) are written to the `outbox` table in PostgreSQL *in the exact same database transaction* as the state change.
2. **Persistence During Outage:**
   - While RabbitMQ is offline or unreachable, rows safely accumulate in PostgreSQL `outbox` with status `PENDING`.
   - The user API remains completely healthy, and users experience no errors or transaction aborts.
3. **Automatic Resumption:**
   - Once RabbitMQ comes back online, the outbox relay worker picks up pending rows in sequence, publishes them with publisher confirms, and marks them `PUBLISHED`.

---

## Diagnostic Steps
1. **Check RabbitMQ Service Status:**
   ```bash
   docker compose ps rabbitmq
   docker compose logs --tail 100 rabbitmq
   ```
2. **Check Outbox Lag and Backlog Count:**
   ```sql
   SELECT status, count(*), min(created_at) as oldest_pending
   FROM outbox
   GROUP BY status;
   ```
3. **Check Outbox Relay Process:**
   ```bash
   docker compose ps relay
   docker compose logs --tail 50 relay
   ```

---

## Recovery Steps
1. **Restart RabbitMQ Broker:**
   ```bash
   docker compose restart rabbitmq
   ```
2. **Verify Broker Management Web UI & Vhost:**
   - Browse to `http://localhost:15672` (default user/pass or production credentials).
   - Check exchange bindings: `events.exchange` (topic).
   - Check consumer queues: `email_notifications`, `payment_reconciliation`.
3. **Restart Relay Worker:**
   ```bash
   docker compose restart relay
   ```
4. **Monitor Backlog Draining:**
   - Run query every 30 seconds:
     ```sql
     SELECT count(*) FROM outbox WHERE status = 'PENDING';
     ```
   - Verify backlog steadily decreases to 0.

---

## Post-Incident
- Verify outbox lag drops below 5 seconds.
- Verify consumer idempotency (no duplicate emails or charges delivered).
