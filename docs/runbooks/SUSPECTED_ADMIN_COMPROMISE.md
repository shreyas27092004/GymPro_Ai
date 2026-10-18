# Runbook: Suspected Administrator Compromise & Token Invalidation

## Severity: CRITICAL (P0 - Security Incident)
**Primary Symptoms:**
- Unrecognized admin logins or anomalous IP / geographic access.
- Unauthorized role escalations or unexpected broadcast notifications.
- Alert `admin-code failures > threshold` or `new admin created` alert triggering outside normal business operations.

---

## Containment Protocol (Execute Immediately)

### 1. Revoke Compromised Admin User Sessions
Invalidate all existing JWT access and refresh tokens for the compromised admin account by bumping `token_version` and setting `account_status = 'SUSPENDED'`:
```sql
UPDATE users 
SET account_status = 'SUSPENDED',
    token_version = token_version + 1,
    updated_at = NOW()
WHERE email = 'compromised_admin@gympro.com';
```

### 2. Global Token Invalidation (If System-Wide Compromise Suspected)
If administrator signing keys or application secrets were compromised, revoke all active sessions across the entire system:
1. **Rotate `JWT_SECRET` and `TOKEN_HMAC_SECRET` in environment variables:**
   ```bash
   # Generate fresh 256-bit cryptographic secrets
   NEW_JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
   NEW_HMAC_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
   ```
2. **Update `.env` / Cloud Secret Manager:**
   ```env
   JWT_SECRET=<NEW_JWT_SECRET>
   TOKEN_HMAC_SECRET=<NEW_HMAC_SECRET>
   ```
3. **Invalidate all refresh tokens in DB:**
   ```sql
   UPDATE refresh_tokens 
   SET revoked_at = NOW() 
   WHERE revoked_at IS NULL;
   ```
4. **Restart Backend Service:**
   ```bash
   docker compose restart backend
   ```

### 3. Expire Pending Role Requests and Unused Admin Activation Codes
Neutralize any pending or active activation codes:
```sql
-- Expire all pending role requests
UPDATE role_requests 
SET status = 'REJECTED',
    decided_at = NOW(),
    rejection_reason = 'EMERGENCY_SECURITY_REVOCATION'
WHERE status = 'PENDING';

-- Expire all active admin activation codes
UPDATE admin_activation_codes 
SET used_at = NOW() 
WHERE used_at IS NULL;
```

---

## Forensic Investigation
1. **Review Audit Log for Actor Actions:**
   ```sql
   SELECT created_at, action, entity, entity_id, details
   FROM audit_log
   WHERE actor_id = :compromised_user_id
   ORDER BY created_at DESC;
   ```
2. **Audit Recent Role Changes:**
   ```sql
   SELECT id, user_id, requested_role, status, decided_by, created_at
   FROM role_requests
   WHERE created_at > NOW() - INTERVAL '48 hours';
   ```
3. **Check Outbox for Unauthorized Broadcasts or Emails:**
   ```sql
   SELECT id, event_type, payload, status, created_at
   FROM outbox
   WHERE event_type = 'ADMIN_BROADCAST' AND created_at > NOW() - INTERVAL '48 hours';
   ```

---

## Recovery & Post-Incident
- Re-verify all trainer and admin accounts.
- Enforce mandatory MFA (TOTP) reactivation for all administrative personnel.
- Complete Incident Review using `INCIDENT_REVIEW_TEMPLATE.md`.
