# Runbook: PostgreSQL Database Failover & Transient Lock Remediation

## Severity: CRITICAL (P0)
**Primary Symptoms:**
- Database connection pool exhaustion (`asyncpg.exceptions.TooManyConnectionsError` or pool timeout).
- Health probe `/health` or `/ready` failing.
- Transient deadlocks or lock wait timeouts during concurrent booking / waitlist promotions.

---

## Architecture & Protection Mechanisms
- **RLS & Role Isolation:**
  - Application queries run under `gympro_app` with connection-level RLS (`SET LOCAL app.user_id = ...`).
  - Schema migrations and seeds run strictly under `gympro_seed` or superuser.
- **Optimistic / Row Locking (`SELECT ... FOR UPDATE`):**
  - All critical inventory counters (`booked_count` on `fitness_classes`, `memberships`, `pending_actions`) use row-level locking to guarantee no double bookings or race conditions.

---

## Diagnostic Steps
1. **Check Connection Count & Active Queries:**
   ```sql
   SELECT state, count(*) FROM pg_stat_activity GROUP BY state;
   ```
2. **Find Blocking Queries and Locks:**
   ```sql
   SELECT pid, age(clock_timestamp(), query_start), usename, query 
   FROM pg_stat_activity 
   WHERE state != 'idle' AND query NOT ILIKE '%pg_stat_activity%' 
   ORDER BY query_start ASC;
   ```
3. **Check Replication Lag (if standby is active):**
   ```sql
   SELECT client_addr, state, sync_state, replay_lag FROM pg_stat_replication;
   ```

---

## Failover Procedure
1. **Initiate Managed Standby Promotion:**
   - In managed RDS / Aurora: trigger automatic failover via cloud CLI / console:
     ```bash
     aws rds reboot-db-instance --db-instance-identifier gympro-db --force-failover
     ```
   - In self-hosted Patroni / pgpool:
     ```bash
     patronictl failover gympro-cluster
     ```
2. **Update App DB Connection (if DNS not used):**
   - Update `DATABASE_URL` in `.env` or Kubernetes secret.
   - Restart backend instances to flush connection pool:
     ```bash
     docker compose restart backend
     ```
3. **Verify Pool Health & Occupancy Reconciliation:**
   - Run liveness probe: `curl -s http://localhost:8000/ready`
   - Trigger occupancy reconciliation job to ensure no invariant drift during failover:
     ```bash
     python -m app.jobs.reconcile_occupancy
     ```

---

## Post-Failover Verification
- Confirm 0 row discrepancies between `v_class_occupancy` view and `fitness_classes.booked_count`.
- Audit `audit_log` for any aborted transactions during failover window.
