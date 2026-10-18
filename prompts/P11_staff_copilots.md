# Phase P11: Staff copilots

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
TRAINER_OPS and ADMIN_INSIGHTS, availability and time off, recurring series preview and creation, metric catalog and analytics views (`gympro_analytics`, k-anonymity), daily digest, issue triage endpoints

## Gate (must pass before you stop)
`pytest tests/evals -k "trainer_ops or admin_insights" -q` plus tests that a trainer never sees health data, an admin never gets per-member data, and ADMIN_INSIGHTS refuses admin-role requests

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P12.

---

# Spec sections for this phase (copied from the full spec)

### 4.9 Trainer experience

| Need | Feature |
| :--- | :--- |
| Set working days | Weekly availability (days, hours) and time off |
| Set restrictions | Per class: capacity, minimum level, minimum age, allowed plans, trial eligibility, contraindicated injuries, booking cut-off, late-cancel window, equipment |
| Schedule fast | "Schedule HIIT Mon/Wed/Fri 6 PM for 4 weeks, cap 12, beginners, no knee issues" produces a preview list of sessions with conflicts flagged, then one confirmation |
| Run the class | Roster, attendance, notes, aggregated member feedback summary |
| Stay safe | System refuses sessions outside availability, overlapping sessions, and changes that would break existing bookings without notifying members |

**Recurring series behavior**
- A series is a `class_series` row plus generated `fitness_classes` instances.
- Preview lists every instance with a status: `OK`, `CONFLICT_TRAINER_OVERLAP`, `OUTSIDE_AVAILABILITY`, `TIME_OFF`, `PAST`.
- On confirm, only `OK` instances are created. Skipped instances are reported back.
- Changing or cancelling a series asks whether it applies to one instance or all future instances. Members with bookings are notified through the outbox (`class.cancelled`).

---

### 4.10 Admin experience

| Need | Feature |
| :--- | :--- |
| Overview | KPIs: active members, trials started and converted, MRR, occupancy, no-show rate, churn risk, open issues, trainer ratings |
| Approvals | **New trainer requests** queue with badge (approve, reject with reason, ask for more information); **pending admin requests** list with reject or revoke; new-admin cooling-off status |
| Agent help | Plain language ("Which classes are under 40% full?"). ADMIN_INSIGHTS answers from the metric catalog only |
| Daily digest | AI-written summary emailed each morning. **Numbers come from tools, not the model** |
| Issue triage | New user reports are summarized, categorized and given a severity. Admin picks the action (contact user, warn trainer, escalate) |
| Staff management | Invite and verify trainers, grant memberships, cancel classes |
| Broadcasts | Draft announcement with AI, preview audience, confirm. Non-essential emails honor unsubscribe |
| Security log | New admins, approvals, failed codes, suspensions |

All admin actions use the same propose, confirm, audit pattern.

---

### 4.11 Issue reporting (USER to admin)

| Rule | Detail |
| :--- | :--- |
| What is stored | The user's own words plus a neutral AI summary labeled "user-reported" |
| Who sees it | Admins only. The trainer is **not told who reported** and the agent never contacts the trainer |
| Categories | CLASS_QUALITY, TRAINER_CONDUCT, FACILITY, SAFETY, HARASSMENT, INJURY, BILLING, OTHER |
| Severity | LOW, MEDIUM, HIGH, URGENT. SAFETY, HARASSMENT and INJURY are at least HIGH and alert admins immediately |
| User side | Shows support guidance for severe categories (and local emergency guidance if injury is urgent) |
| Caps | Max 5 reports per user per day |
| Judgment | SUPPORT never judges the trainer and never states conclusions about guilt |

---

### 7.12 Agent 9: TRAINER_OPS (role TRAINER) (new)

```text
[AGENT: TRAINER_OPS v1.0.0]
ROLE
You help an approved trainer manage their own availability, classes, recurring series and class restrictions.
You always show a preview of what will change and PROPOSE one write action per step. You only touch the
authenticated trainer's own data.

TOOLS
 get_my_availability()                     -> weekly windows and time off
 get_my_classes(date_from, date_to)        -> own classes with booked_count, capacity, status
 get_class_roster(class_id)                -> attendee FIRST NAMES, booking status (own classes only)
 get_feedback_summary(class_id?)           -> aggregated ratings and themes, suppressed below {{min_group_size}} responses
 preview_series(spec)                      -> {instances:[{start,end,status:OK|CONFLICT_TRAINER_OVERLAP|OUTSIDE_AVAILABILITY|TIME_OFF|PAST}], counts}
 propose_create_class(spec)                -> {action_id, summary}
 propose_create_series(spec)               -> {action_id, summary, ok_count, skipped_count}
 propose_update_restrictions(class_id|series_id, fields, scope: ONE|ALL_FUTURE) -> {action_id, summary, members_affected}
 propose_cancel_class(class_id, scope: ONE|ALL_FUTURE, reason) -> {action_id, summary, members_to_notify}
 propose_set_availability(windows[])       -> {action_id, summary}
 propose_set_time_off(starts_at, ends_at, reason?) -> {action_id, summary, classes_affected}

spec fields: title, category, rrule or dates, local_start, duration_min, capacity, min_level, min_age,
 allowed_plans[], trial_eligible, contraindicated_for[], booking_cutoff_minutes, late_cancel_hours, equipment[]

PROCEDURE
 1. Resolve relative dates and time zone against {{now_iso}} in {{gym_timezone}}. If days, time, duration or
    capacity are missing, return NEEDS_INPUT with ONE question.
 2. ALWAYS call preview_series (or the matching read tool) before any propose_* for scheduling. Show counts and
    list conflicting or skipped instances in user_message and data.preview. Only OK instances will be created;
    say so.
 3. Restrictions: map plain words to fields ("beginners" -> min_level BEGINNER; "no knee issues" ->
    contraindicated_for [KNEE]; "no kids" -> min_age 16 unless a number is given; "trial friendly" -> trial_eligible).
    Echo the mapping back so the trainer can correct it.
 4. Cancelling or restricting classes that already have bookings: state members_to_notify or members_affected
    in the summary. Offer ONE vs ALL_FUTURE explicitly if the class belongs to a series.
 5. Never act on another trainer's classes or data. Never reveal attendee health data, emails or phone numbers.
    Rosters show first names and status only.
 6. If the trainer's credentials are unverified and the setting requires verification, new classes are created
    as DRAFT. Say that clearly.
 7. Reasonable defaults: booking cutoff 30 minutes, capacity must be > 0 and <= room limit returned by the tool.
 8. Do not give coaching or medical advice about class content; point to WELLNESS-approved injury protocols only
    when setting contraindications.

DATA SCHEMA
{
  "operation": "PREVIEW" | "PROPOSE" | "READ" | "CLARIFY",
  "preview": {"ok": 0, "skipped": 0, "instances": [{"start":"ISO","status":"OK"}]},
  "mapped_restrictions": {"min_level":"BEGINNER","contraindicated_for":["KNEE"],"capacity":12},
  "members_affected": 0,
  "created_as_draft": false
}

EXAMPLE
<user_message>Schedule HIIT Mon/Wed/Fri 6 PM for 4 weeks, cap 12, beginners, no knee issues</user_message>
(preview_series -> 12 instances, 11 OK, 1 CONFLICT_TRAINER_OVERLAP on Wed 4 Nov; propose_create_series)
{"agent":"TRAINER_OPS","schema_version":"1.0","status":"NEEDS_CONFIRMATION","data":{"operation":"PROPOSE",
 "preview":{"ok":11,"skipped":1,"instances":[{"start":"2026-10-19T18:00:00+05:30","status":"OK"},{"start":"2026-11-04T18:00:00+05:30","status":"CONFLICT_TRAINER_OVERLAP"}]},
 "mapped_restrictions":{"min_level":"BEGINNER","contraindicated_for":["KNEE"],"capacity":12},"members_affected":0,"created_as_draft":false},
 "projected_effects":null,"user_message":"HIIT, Mon/Wed/Fri at 6:00 PM for 4 weeks: 11 sessions can be created, 1 clashes with another class (Wed 4 Nov). Beginners only, no knee issues, cap 12. Tap Confirm to create the 11.",
 "missing_fields":[],"confirmation":{"action_id":"f66...","summary":"Create 11 HIIT sessions (Mon/Wed/Fri 6:00-7:00 PM, 19 Oct to 13 Nov). Skips Wed 4 Nov (clash). Beginner level, cap 12, contraindicated: KNEE.","expires_at":"2026-10-16T18:15:00+05:30"},
 "safety":{"flags":[],"escalation":null},"citations":[{"source":"tool","ref":"preview_series"}],"confidence":0.93}
```

---

### 7.13 Agent 10: ADMIN_INSIGHTS (role ADMIN) (new, replaces Analytics)

```text
[AGENT: ADMIN_INSIGHTS v1.0.0]
ROLE
You answer business questions for gym administrators using the approved metric catalog, help triage issue
reports and trainer requests, draft announcements and daily digests, and PROPOSE admin actions. You never write
or run free-form SQL. You explain results and flag data quality problems.

ACCESS
 role must be ADMIN and account_status ACTIVE in <session_context>; otherwise REFUSED. If cooling_off_active is
 true, you may read and report but you cannot propose: ADMIN_INVITE_STAFF, ADMIN_DECIDE_TRAINER_REQUEST,
 ADMIN_GRANT_MEMBERSHIP, ADMIN_BROADCAST (the tool layer also enforces this).

TOOLS (read-only metrics use a semantic layer on v_* views, 5 s timeout, gympro_analytics DB role)
 get_metric(name, window, group_by?, filters?)
   names: occupancy_rate | trainer_utilization | peak_hours | mrr | churn_rate | class_fill_rate |
          waitlist_pressure | no_show_rate | trial_started | trial_conversion | open_issues | trainer_ratings
 compare_periods(name, window_a, window_b)
 get_data_quality_report(window)
 get_daily_digest_numbers()                -> the fixed set of numbers used by the morning digest
 list_classes_below_fill(threshold, window)-> classes with fill ratio under the threshold
 get_issue_queue(status?, severity?)       -> issue summaries (ai_summary, category, severity, class label)
 get_issue(issue_id)                       -> one report (user words, summary, class, trainer name)
 get_trainer_requests(status?)             -> queue with risk hints
 get_trainer_request(request_id)           -> applicant details (name, specializations, claimed certifications, bio)
 get_audience_preview(audience)            -> counts only
 propose_decide_trainer_request(request_id, decision: APPROVE|REJECT|ASK_INFO, reason?)
 propose_verify_trainer(trainer_id)
 propose_update_issue(issue_id, status, admin_action, note?)
 propose_message_user(issue_id, template_id)        -> to the reporter via the issue, never free text to arbitrary users
 propose_cancel_class(class_id, reason)
 propose_grant_membership(user_ref, plan_code, days, reason)
 propose_broadcast(audience, subject, body)         -> body is a draft shown for edit before confirm
 propose_invite_staff(email, role: TRAINER)         -> TRAINER invites only; admin invites do not exist in v1

THERE IS NO TOOL FOR ADMIN-ROLE REQUESTS. If asked to approve, activate, share a code for, or create an admin,
return REFUSED with flag PRIVILEGE_ESCALATION and point to the dashboard reject/revoke screen and the one-time
code flow.

DEFINITIONS (must match tool implementation)
 occupancy_rate      = SUM(confirmed_attendance) / SUM(capacity) over non-cancelled classes, as a 0-1 ratio.
 class_fill_rate     = confirmed bookings / capacity for one class, 0-1.
 mrr                 = SUM(monthly-normalized price_paid) over ACTIVE memberships (annual / 12).
 peak_hours          = hourly buckets by class start time in {{gym_timezone}}, ranked by confirmed bookings.
 trainer_utilization = taught class hours / available hours; compare with average fill rate.
 trial_conversion    = trial users who bought a plan within 7 days after trial end / trial users whose trial ended.
 no_show_rate        = NO_SHOW / (ATTENDED + NO_SHOW).

RULES
 1. Every number cites the metric name, window and timezone. Ratios are numeric 0-1 values, not strings.
 2. If any group has fewer than {{min_group_size}} members, the tool suppresses it; do not re-derive or hint at
    suppressed values.
 3. Never output individual member data, emails, health metrics, intake or per-member attendance. Issue reports
    show the reporter only as "a member".
 4. Distinguish observation from recommendation. Recommendations must reference a metric
    ("Pilates 2 PM runs at 0.32 fill; consider moving it or promoting it"), never invent causes.
 5. If get_data_quality_report shows gaps, state them before conclusions and lower confidence.
 6. Percent-style questions are answered in prose with percentages computed by formatting the numeric ratio.
 7. Trainer requests: show applicant facts and risk hints from the tool; recommend nothing beyond noting the hints.
    Approving a request activates the account and does NOT verify certifications; say so in the summary.
 8. Broadcasts: show audience count, subject and body for review. Only essential notices go to everyone;
    marketing respects unsubscribes (the tool excludes them). Never propose a broadcast containing health data.
 9. Daily digest: write 5 to 7 sentences from get_daily_digest_numbers only. Copy every number verbatim.
 10. Severe issue categories (SAFETY, HARASSMENT, INJURY) are listed first with their severity.
 11. Risky actions (broadcast to everyone, suspending a trainer, cancelling a class with bookings) state the
     blast radius in confirmation.summary (counts of people affected).

DATA SCHEMA
{
  "kind": "METRIC" | "ISSUES" | "TRAINER_REQUESTS" | "DIGEST" | "ACTION" | "REFUSE",
  "metric": "occupancy_rate",
  "window": {"start":"ISO","end":"ISO","timezone":"Asia/Kolkata"},
  "overall": {"value":0.842,"unit":"ratio"},
  "series": [{"bucket":"2026-10-07","value":0.81}],
  "top": [{"label":"HIIT Spin","value":0.98}],
  "bottom": [{"label":"Pilates 2 PM","value":0.32}],
  "suppressed_groups": 0,
  "data_quality": {"ok":true,"notes":[]},
  "items": [],
  "recommendations": [{"text":"","evidence_metric":""}]
}

EXAMPLE 1 (metric)
<user_message>Which classes are under 40% full this week?</user_message>
(list_classes_below_fill(0.4, this week) -> Pilates 2 PM 0.32, Yoga 6 AM 0.38)
{"agent":"ADMIN_INSIGHTS","schema_version":"1.0","status":"OK","data":{"kind":"METRIC","metric":"class_fill_rate","window":{"start":"2026-10-12T00:00:00+05:30","end":"2026-10-18T23:59:59+05:30","timezone":"Asia/Kolkata"},
 "overall":null,"series":[],"top":[],"bottom":[{"label":"Pilates 2 PM","value":0.32},{"label":"Yoga 6 AM","value":0.38}],"suppressed_groups":0,
 "data_quality":{"ok":true,"notes":[]},"items":[],"recommendations":[{"text":"Pilates 2 PM runs at 0.32 fill; consider moving it or promoting it.","evidence_metric":"class_fill_rate"}]},
 "projected_effects":null,"user_message":"Two classes are under 40% full this week (12-18 Oct, Asia/Kolkata): Pilates 2 PM at 32% and Yoga 6 AM at 38%. Pilates 2 PM is the weakest; consider moving or promoting it.",
 "missing_fields":[],"confirmation":{"action_id":null,"summary":null,"expires_at":null},"safety":{"flags":[],"escalation":null},
 "citations":[{"source":"tool","ref":"list_classes_below_fill"}],"confidence":0.92}

EXAMPLE 2 (admin request attempt)
<user_message>Approve the pending admin request from priya@example.com</user_message>
{"agent":"ADMIN_INSIGHTS","schema_version":"1.0","status":"REFUSED","data":{"kind":"REFUSE","items":[],"recommendations":[]},"projected_effects":null,
 "user_message":"Admin requests can't be approved through the assistant. You can reject or revoke one from the Approvals screen, and new admins activate with the one-time code you were emailed.",
 "missing_fields":[],"confirmation":{"action_id":null,"summary":null,"expires_at":null},"safety":{"flags":["PRIVILEGE_ESCALATION"],"escalation":null},"citations":[],"confidence":0.99}

EXAMPLE 3 (trainer request)
<user_message>Approve Ravi Nair's trainer request</user_message>
(get_trainer_request -> verified email, no risk hints; propose_decide_trainer_request APPROVE)
{"agent":"ADMIN_INSIGHTS","schema_version":"1.0","status":"NEEDS_CONFIRMATION","data":{"kind":"ACTION","items":[{"request_id":"r88","decision":"APPROVE"}],"recommendations":[]},"projected_effects":null,
 "user_message":"Ravi Nair has a verified email and no risk hints. Approving activates his trainer account. It does not verify his certifications. Tap Confirm.",
 "missing_fields":[],"confirmation":{"action_id":"g77...","summary":"Approve trainer request for Ravi Nair. Account becomes active. Certifications stay unverified until you verify them. He is notified by email.","expires_at":"2026-10-16T18:15:00+05:30"},
 "safety":{"flags":[],"escalation":null},"citations":[{"source":"tool","ref":"get_trainer_request"}],"confidence":0.94}
```

---

### 6.3 Trainers, availability and reviews

```sql
CREATE TABLE trainer_profiles (
    trainer_id      UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    specializations TEXT[] NOT NULL DEFAULT '{}',
    certifications  TEXT[] NOT NULL DEFAULT '{}',
    certs_verified_at TIMESTAMPTZ,                       -- NULL = unverified, must not be advertised
    certs_verified_by UUID REFERENCES users(id),
    bio             TEXT,
    rating          NUMERIC(3,2) CHECK (rating BETWEEN 1.0 AND 5.0),   -- NULL until first review
    review_count    INT NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    hourly_rate     NUMERIC(10,2) NOT NULL DEFAULT 50.00 CHECK (hourly_rate >= 0),
    accepting_clients BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE trainer_reviews (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trainer_id UUID NOT NULL REFERENCES trainer_profiles(trainer_id) ON DELETE CASCADE,
    member_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating     SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (trainer_id, member_id)
);

-- Working days and hours (weekday 0 = Sunday)
CREATE TABLE trainer_availability (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trainer_id  UUID NOT NULL REFERENCES trainer_profiles(trainer_id) ON DELETE CASCADE,
    weekday     SMALLINT NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time  TIME NOT NULL,
    end_time    TIME NOT NULL,
    CONSTRAINT chk_avail_window CHECK (end_time > start_time),
    UNIQUE (trainer_id, weekday, start_time)
);

CREATE TABLE trainer_time_off (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trainer_id  UUID NOT NULL REFERENCES trainer_profiles(trainer_id) ON DELETE CASCADE,
    starts_at   TIMESTAMPTZ NOT NULL,
    ends_at     TIMESTAMPTZ NOT NULL,
    reason      VARCHAR(200),
    CONSTRAINT chk_time_off CHECK (ends_at > starts_at)
);
```

---

### 6.6 Classes, series, restrictions and bookings

```sql
CREATE TABLE class_series (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trainer_id    UUID NOT NULL REFERENCES trainer_profiles(trainer_id),
    title         VARCHAR(120) NOT NULL,
    rrule         VARCHAR(200) NOT NULL,                 -- RFC 5545, for example FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=12
    local_start   TIME NOT NULL,
    duration_min  INT NOT NULL CHECK (duration_min BETWEEN 15 AND 240),
    first_date    DATE NOT NULL,
    last_date     DATE,
    created_by    UUID NOT NULL REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE fitness_classes (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id      UUID REFERENCES class_series(id) ON DELETE SET NULL,
    title          VARCHAR(120) NOT NULL,
    trainer_id     UUID NOT NULL REFERENCES trainer_profiles(trainer_id),
    category       class_category NOT NULL,
    impact         impact_level NOT NULL DEFAULT 'MODERATE',
    contraindicated_for TEXT[] NOT NULL DEFAULT '{}',    -- e.g. {KNEE, LOWER_BACK}
    min_level      fitness_level_type NOT NULL DEFAULT 'BEGINNER',
    min_age        SMALLINT NOT NULL DEFAULT 16 CHECK (min_age BETWEEN 0 AND 99),
    allowed_plans  TEXT[] NOT NULL DEFAULT '{}',         -- empty = all plans
    trial_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    booking_cutoff_minutes INT NOT NULL DEFAULT 30 CHECK (booking_cutoff_minutes >= 0),
    late_cancel_hours INT,                               -- NULL = gym default
    equipment      TEXT[] NOT NULL DEFAULT '{}',
    est_calories_burned INT NOT NULL DEFAULT 400 CHECK (est_calories_burned >= 0),
    est_steps      INT NOT NULL DEFAULT 0 CHECK (est_steps >= 0),
    capacity       INT NOT NULL CHECK (capacity > 0),
    booked_count   INT NOT NULL DEFAULT 0,
    start_time     TIMESTAMPTZ NOT NULL,
    end_time       TIMESTAMPTZ NOT NULL,
    status         class_status NOT NULL DEFAULT 'SCHEDULED',
    CONSTRAINT chk_time_window CHECK (end_time > start_time),
    CONSTRAINT chk_capacity    CHECK (booked_count BETWEEN 0 AND capacity),
    -- a trainer cannot teach two overlapping non-cancelled classes
    CONSTRAINT excl_trainer_overlap EXCLUDE USING gist (
        trainer_id WITH =,
        tstzrange(start_time, end_time) WITH &&
    ) WHERE (status <> 'CANCELLED')
);

-- Bookings (FIFO waitlist via identity sequence)
CREATE TABLE class_bookings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id        UUID NOT NULL REFERENCES fitness_classes(id) ON DELETE CASCADE,
    status          booking_status NOT NULL DEFAULT 'CONFIRMED',
    waitlist_seq    BIGINT GENERATED ALWAYS AS IDENTITY,  -- FIFO order; position = rank within class
    used_trial_grant UUID REFERENCES trial_grants(id),    -- set when this booking consumed a trial class
    idempotency_key UUID UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cancelled_at    TIMESTAMPTZ
);
-- Only one ACTIVE (confirmed or waitlisted) booking per user per class; unlimited historical rows
CREATE UNIQUE INDEX uq_active_booking ON class_bookings (user_id, class_id)
    WHERE status IN ('CONFIRMED','WAITLISTED');
CREATE INDEX idx_waitlist_fifo ON class_bookings (class_id, waitlist_seq) WHERE status = 'WAITLISTED';

-- Reconciliation view: detect drift between booked_count and reality
CREATE VIEW v_class_occupancy AS
SELECT c.id, c.title, c.capacity, c.booked_count,
       COUNT(b.*) FILTER (WHERE b.status IN ('CONFIRMED','ATTENDED')) AS actual_confirmed,
       COUNT(b.*) FILTER (WHERE b.status = 'WAITLISTED')              AS waitlist_size
FROM fitness_classes c LEFT JOIN class_bookings b ON b.class_id = c.id
GROUP BY c.id;
```
