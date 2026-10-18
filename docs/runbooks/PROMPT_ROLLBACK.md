# Runbook: One-Click Prompt Rollback

## Severity: MEDIUM / HIGH (P1 / P2)
**Primary Symptoms:**
- Validator-failure spike or safety-label drift detected in agent runs.
- Sudden drop in multi-intent planning accuracy (<90%) or tool-selection accuracy (<95%).
- Unintended agent behavior or hallucinations reported following a prompt release.

---

## Architectural Immutability & Prompt Versioning
GymPro AI adheres to strict prompt version immutability (Spec 8 / Spec 14):
1. **Prompt Files & Versions Table:**
   - Every agent prompt file (`backend/prompts/agents/{agent}.md`) has a semantic version specified in YAML front-matter (`version: "1.1.0"`).
   - The database maintains an append-only `prompt_versions` table tracking `(agent_name, version, prompt_hash, git_commit, is_active, created_at)`.
2. **Deterministic Canary & Rollback:**
   - Traffic can be routed by version flag or instantly reverted to the previous known-good active version without rebuilding container images.

---

## Diagnostic Steps
1. **Identify Failing Agent & Version:**
   - Check Prometheus metrics `/metrics` for `agent_runs_total{status="ERROR"}` grouped by `agent`.
   - Check `agent_runs` table for recent error trends:
     ```sql
     SELECT prompt_versions, count(*), count(*) FILTER (WHERE final_status = 'ERROR') as errors
     FROM agent_runs
     WHERE created_at > NOW() - INTERVAL '1 hour'
     GROUP BY prompt_versions;
     ```
2. **Find Active vs Previous Known-Good Version:**
   ```sql
   SELECT id, agent_name, version, git_commit, is_active, created_at
   FROM prompt_versions
   WHERE agent_name = 'PLANNER' -- or target agent
   ORDER BY created_at DESC LIMIT 5;
   ```

---

## Rollback Procedure
1. **Revert Active Version in DB:**
   ```sql
   BEGIN;
   -- Deactivate buggy version
   UPDATE prompt_versions 
   SET is_active = FALSE 
   WHERE agent_name = :agent AND version = :bad_version;

   -- Reactivate previous stable version
   UPDATE prompt_versions 
   SET is_active = TRUE 
   WHERE agent_name = :agent AND version = :prev_stable_version;
   COMMIT;
   ```
2. **Revert Git Prompt File (if required for cold starts):**
   ```bash
   git checkout HEAD~1 -- backend/prompts/agents/<agent>.md
   # Or checkout specific known-good release commit
   ```
3. **Flush In-Memory Prompt Cache:**
   - Send SIGHUP to backend workers or restart the backend container:
     ```bash
     docker compose kill -s HUP backend
     ```
4. **Run Smoke Evals:**
   ```bash
   pytest backend/tests/evals/test_evals.py -k <agent> -q
   ```

---

## Post-Rollback
- Verify validator failure rate drops back below 1%.
- Analyze eval regression against new test cases in `backend/tests/evals/cases/`.
