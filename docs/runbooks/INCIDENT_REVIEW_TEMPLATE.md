# Incident Review: [INCIDENT TITLE]

**Incident Date:** YYYY-MM-DD  
**Severity:** P0 (Critical) / P1 (High) / P2 (Medium)  
**Incident Commander:** [Name]  
**Lead Investigator:** [Name]  
**Status:** [Open / Under Review / Resolved]  

---

## 1. Summary
*Provide a concise 2-3 sentence overview of what occurred, the impact on members and gym operations, and how it was ultimately contained.*

---

## 2. Impact Analysis
- **User Impact:** Number of members affected, disrupted class bookings, failed payment checkouts.
- **Data / Privacy Impact:** Any PII exposure, cross-tenant data leaks, or RLS bypasses (Confirmed / None).
- **Financial Impact:** Erroneous charges, refunded transactions, or missed membership renewals.
- **Downtime / Service Degradation:** Total duration of degraded service or full outage (minutes/hours).

---

## 3. Timeline of Events (UTC)
| Timestamp | Event / Observation / Action Taken | Actor / System |
| :--- | :--- | :--- |
| `HH:MM` | Initial alert triggered (e.g. `ERROR rate > 3%` or `DLQ not empty`) | Prometheus Alertmanager |
| `HH:MM` | On-call engineer acknowledged incident | On-Call Lead |
| `HH:MM` | Mitigation action initiated (e.g. runbook executed, provider switched) | Incident Team |
| `HH:MM` | Service restored and confirmed healthy | Incident Team |
| `HH:MM` | Incident closed, monitoring period commenced | Incident Commander |

---

## 4. Root Cause Analysis (5 Whys)
1. **Why did the failure occur?**  
   *Answer:* ...
2. **Why was that condition present?**  
   *Answer:* ...
3. **Why did earlier checks or gates not detect it?**  
   *Answer:* ...
4. **Why was the fallback or retry insufficient?**  
   *Answer:* ...
5. **Why was the architecture susceptible to this root cause?**  
   *Answer:* ...

---

## 5. What Went Well
- *Example: Transactional outbox prevented message loss while downstream broker was unreachable.*
- *Example: OpenTelemetry traces identified the failing tool call within 2 minutes.*

---

## 6. What Went Poorly / Gaps Identified
- *Example: Alert threshold was too loose, delaying on-call notification by 5 minutes.*
- *Example: Missing automated DLQ replay required manual script execution.*

---

## 7. Action Items & Preventive Measures
| Action Item | Type (Prevent / Detect / Mitigate) | Owner | Target Date | Tracking Ticket |
| :--- | :--- | :--- | :--- | :--- |
| Add new red-team eval case in `tests/evals/` | Prevent | Security Team | YYYY-MM-DD | SEC-101 |
| Adjust Prometheus alert threshold | Detect | SRE Team | YYYY-MM-DD | OPS-202 |
| Update operational runbook | Mitigate | Engineering | YYYY-MM-DD | DOC-303 |
