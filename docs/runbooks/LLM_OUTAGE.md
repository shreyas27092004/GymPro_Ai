# Runbook: LLM Provider Outage

## Severity: HIGH (P1)
**Primary Symptoms:**
- Spikes in chat orchestrator errors (HTTP 502/504 or fallback circuit breaker tripping).
- `agent_runs` logging repeated `LLM_PROVIDER_ERROR` or HTTP 429/500 from provider API.
- Error rate alert `ERROR rate > 3%` triggered on Prometheus metrics.

---

## Architecture & Circuit Breaker Behavior
GymPro AI is built with resilience against external LLM provider downtime:
1. **Fallback Path:**
   - When the LLM provider fails repeatedly or circuit breaker opens, the system switches to deterministic fallback rules (`rules_fast_path`).
   - The user receives an informative notification:
     > *"Our AI assistant is currently experiencing an upstream connection disruption. You can still browse and book classes directly using the Class Schedule tab."*
2. **Deterministic Confirmations Unaffected:**
   - Class bookings, cancellations, bundle confirmations, and payment verifications (`/api/actions/{id}/confirm`, `/api/bundles/{id}/confirm`, `/api/payments/razorpay/verify`) do NOT use LLMs. All deterministic mutation paths continue to operate 100% normally.

---

## Diagnostic Steps
1. **Verify Provider Status:**
   - Check upstream status page (e.g. OpenAI / Anthropic / Google Vertex status dashboard).
   - Inspect Prometheus `/metrics` for `agent_runs_total{status="ERROR"}` and provider latency spikes.
2. **Review Recent Logs:**
   ```bash
   grep "LLM_PROVIDER_ERROR" logs/app.log | tail -n 50
   ```
3. **Check API Health Probe:**
   ```bash
   curl -s http://localhost:8000/ready | jq .llm_provider
   ```

---

## Mitigation & Escalation
1. **Switch Model or Provider:**
   - Update `.env`:
     ```bash
     LLM_PROVIDER=openai # or anthropic / fallback-local
     LLM_MODEL=gpt-4o
     ```
   - Reload workers with zero downtime or restart app container:
     ```bash
     docker compose restart backend
     ```
2. **Temporarily Lower Agent Concurrency:**
   - If rate limits (HTTP 429) are causing the outage, lower concurrency limits or enable exponential backoff jitter in `settings.py`.
3. **Notify Users:**
   - Admin broadcast or banner on frontend notifying members of temporary AI chat degraded mode while deterministic scheduling remains active.

---

## Post-Incident
- Verify provider recovery and ensure circuit breaker returns to closed state.
- Audit `agent_runs` table for failed runs during outage window.
- File incident post-mortem using `INCIDENT_REVIEW_TEMPLATE.md`.
