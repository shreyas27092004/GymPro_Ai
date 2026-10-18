# Phase P5: Trial, entitlements, membership

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
Trial grant on verification, entitlement resolver (membership first, then trial), `price_diff`, intake endpoints with consent and `member_intake_versions`

## Gate (must pass before you stop)
`pytest tests/entitlements -q`: trial once per email and per phone hash, trial classes only, upgrade replaces the old membership, proration math, consent gating

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P6.

---

# Spec sections for this phase (copied from the full spec)

### 4.4 Trial, memberships and upgrades

| Item | Rule (all values configurable in `gym_settings`) |
| :--- | :--- |
| Trial | 3 free classes within 14 days of verification, only classes marked `trial_eligible`, no personal-training sessions, once per person |
| After trial | Account stays active but cannot book until a plan is chosen. Friendly, non-pressuring prompt |
| Plans | SILVER, GOLD, PLATINUM. Prices and perks live only in `membership_plans` |
| Perk examples | Class credits per month or unlimited, PT sessions, nutrition consultation, spa, priority booking window |
| Upgrade | Choose a higher plan. **The old membership is ended and replaced.** Prorated charge shown before confirming |
| Payment | After the user confirms, the app opens a secure **Razorpay Checkout** window for the prorated amount. The plan changes only after the payment is verified by the server (section 8.15) |
| Downgrade | Takes effect at renewal, handled by staff in v1 |
| "Highest plan" | Resolved by the tool `get_highest_plan` as the plan with the greatest `sort_order`, then shown to the user for confirmation |
| Entitlement order | Active membership credits first; trial grant only when no active membership and the class is trial eligible |

**Seed plans** (INR; prices come from the table at runtime):

| Plan | Price / month | Group classes / month | PT sessions / month | Nutrition consult | Spa |
| :--- | :--- | :--- | :--- | :--- | :--- |
| SILVER | 999.00 | 4 | 0 | No | No |
| GOLD | 1999.00 | Unlimited | 2 | No | No |
| PLATINUM | 3499.00 | Unlimited | 5 | Yes | Yes |

---

### 4.5 Intake and personalization

One questionnaire feeds three advisers (fitness recommendation, wellness, nutrition).

| Section | Fields | Stored in |
| :--- | :--- | :--- |
| Goals | Build muscle, lose fat, stay healthy, flexibility, endurance, stress relief, rehabilitation (multi-select; one primary maps to `fitness_goal_type`) | `member_profiles.goal`, `member_profiles.goals_extra` |
| Body | Date of birth, height, weight, activity level, experience, typical sleep | `member_profiles` |
| Diet | Vegan, vegetarian, non-vegetarian, halal, jain, cuisine preferences, meals per day | `dietary_preference`, `cuisine_prefs`, `meals_per_day` |
| Injuries and limits | Knee, lower back, shoulder, ankle, wrist, neck, other (free text is reviewed, never auto-trusted) | `known_injuries` (codes), `injury_notes` |
| Allergies | Peanut, tree nut, dairy, egg, soy, gluten, fish. **Unknown allergens fail closed** | `allergies` |
| Schedule | Preferred days and times | `preferred_days`, `preferred_windows` |
| Consent | Separate, revocable health-data consent. Users can view and delete what is stored | `health_data_consent_at` |

Rules:
- Every recommendation shows **"Based on"** (which inputs were used) and a short disclaimer.
- Under-18 users get no calorie-restricted plans. Pregnancy and unsafe targets are refused.
- Every update writes an append-only snapshot to `member_intake_versions` (for audit and "what the AI remembers" screen).
- Without consent the WELLNESS, FITNESS and NUTRITION agents return `NEEDS_INPUT` asking the user to enable personalization in settings. They never ask the user to paste health data into chat as a workaround.

---

### 6.4 Member profile (intake), consent and history

```sql
-- Current-state intake row: biometrics, goals, diet, injuries, allergies, schedule, consent. RLS-protected.
CREATE TABLE member_profiles (
    user_id          UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    date_of_birth    DATE NOT NULL,                      -- age is derived, never a drifting integer
    gender           gender_type NOT NULL DEFAULT 'UNSPECIFIED',
    height_cm        NUMERIC(5,2) NOT NULL CHECK (height_cm BETWEEN 100 AND 250),
    weight_kg        NUMERIC(5,2) NOT NULL CHECK (weight_kg BETWEEN 25 AND 350),
    experience_level fitness_level_type NOT NULL DEFAULT 'BEGINNER',
    goal             fitness_goal_type NOT NULL DEFAULT 'MAINTENANCE',
    goals_extra      TEXT[] NOT NULL DEFAULT '{}',       -- FLEXIBILITY, STRESS_RELIEF, STAY_HEALTHY ...
    known_injuries   TEXT[] NOT NULL DEFAULT '{}',       -- normalized codes: KNEE, LOWER_BACK, SHOULDER, ANKLE, WRIST, NECK
    injury_notes     TEXT,                               -- free text: reviewed, never auto-trusted
    allergies        TEXT[] NOT NULL DEFAULT '{}',       -- HARD constraint for NUTRITION
    dietary_preference VARCHAR(50),
    cuisine_prefs    TEXT[] NOT NULL DEFAULT '{}',
    meals_per_day    SMALLINT CHECK (meals_per_day BETWEEN 1 AND 8),
    typical_sleep_hours NUMERIC(3,1) CHECK (typical_sleep_hours BETWEEN 0 AND 24),
    preferred_days   SMALLINT[] NOT NULL DEFAULT '{}',   -- 0 = Sunday
    preferred_windows TEXT[] NOT NULL DEFAULT '{}',      -- MORNING, MIDDAY, AFTERNOON, EVENING
    is_pregnant      BOOLEAN,                            -- NULL = not provided
    medical_clearance BOOLEAN NOT NULL DEFAULT FALSE,    -- member confirmed doctor clearance / PAR-Q done
    activity_level   VARCHAR(20) NOT NULL DEFAULT 'LIGHT' CHECK (activity_level IN ('SEDENTARY','LIGHT','MODERATE','VERY_ACTIVE')),
    daily_step_goal  INT NOT NULL DEFAULT 10000,
    daily_calorie_burn_goal INT NOT NULL DEFAULT 500,
    sections_completed TEXT[] NOT NULL DEFAULT '{}',     -- GOALS, BODY, DIET, INJURIES, ALLERGIES, SCHEDULE
    health_data_consent_at TIMESTAMPTZ,                  -- required before WELLNESS / NUTRITION / FITNESS read this row
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- BMR / TDEE are computed by tools at read time. They change with weight and age, so they are not stored.

-- Append-only history for audit and the "what the AI remembers" screen
CREATE TABLE member_intake_versions (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    snapshot   JSONB NOT NULL,
    changed_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_intake_versions_user ON member_intake_versions (user_id, created_at DESC);

CREATE OR REPLACE FUNCTION snapshot_member_profile() RETURNS trigger AS $$
BEGIN
  INSERT INTO member_intake_versions (user_id, snapshot, changed_by)
  VALUES (NEW.user_id, to_jsonb(NEW), nullif(current_setting('app.user_id', true), '')::uuid);
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_snapshot_profile AFTER INSERT OR UPDATE ON member_profiles
  FOR EACH ROW EXECUTE FUNCTION snapshot_member_profile();
```

---

### 6.5 Plans, memberships and trial

```sql
-- Membership plans: the only source of prices and perks (prompts receive them from tools)
CREATE TABLE membership_plans (
    code            VARCHAR(20) PRIMARY KEY,             -- SILVER | GOLD | PLATINUM
    display_name    VARCHAR(50) NOT NULL,
    price_monthly   NUMERIC(10,2) NOT NULL CHECK (price_monthly >= 0),
    price_annual    NUMERIC(10,2),
    currency        CHAR(3) NOT NULL DEFAULT 'INR',
    perks           JSONB NOT NULL,                      -- {"group_classes_per_month": 4|null, "pt_sessions_per_month": 0, ...}
    sort_order      INT NOT NULL UNIQUE,                 -- "highest plan" = greatest sort_order
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO membership_plans (code, display_name, price_monthly, perks, sort_order) VALUES
 ('SILVER',   'Silver',   999.00,  '{"group_classes_per_month":4,"pt_sessions_per_month":0,"nutrition_consult":false,"spa":false,"priority_booking_hours":0}', 1),
 ('GOLD',     'Gold',     1999.00,  '{"group_classes_per_month":null,"pt_sessions_per_month":2,"nutrition_consult":false,"spa":false,"priority_booking_hours":12}', 2),
 ('PLATINUM', 'Platinum', 3499.00, '{"group_classes_per_month":null,"pt_sessions_per_month":5,"nutrition_consult":true,"spa":true,"priority_booking_hours":24}', 3);

CREATE TABLE memberships (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_code     VARCHAR(20) NOT NULL REFERENCES membership_plans(code),
    status        membership_status NOT NULL DEFAULT 'ACTIVE',
    billing_cycle billing_cycle_type NOT NULL DEFAULT 'MONTHLY',
    price_paid    NUMERIC(10,2) NOT NULL CHECK (price_paid >= 0),
    start_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date      DATE NOT NULL,
    auto_renew    BOOLEAN NOT NULL DEFAULT TRUE,
    replaced_by   UUID REFERENCES memberships(id),       -- upgrade: old row ends as REPLACED and points to the new one
    granted_by    UUID REFERENCES users(id),             -- admin grant
    CONSTRAINT chk_membership_dates CHECK (end_date > start_date)
);
CREATE UNIQUE INDEX uq_one_active_membership ON memberships (user_id) WHERE status = 'ACTIVE';

-- Free trial: once per verified email and per phone hash (via users uniqueness) and once per user
CREATE TABLE trial_grants (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    phone_hash     CHAR(64) UNIQUE,                      -- NULL allowed; unique when present
    classes_total  INT NOT NULL CHECK (classes_total >= 0),
    classes_used   INT NOT NULL DEFAULT 0 CHECK (classes_used >= 0),
    starts_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at     TIMESTAMPTZ NOT NULL,
    CONSTRAINT chk_trial_used CHECK (classes_used <= classes_total)
);
```

---

### 8.8 Entitlements and a propose tool (the confirmation boundary)

```python
# app/tools/schedule.py
from dataclasses import dataclass

@dataclass
class Entitlement:
    can_book: bool
    reason: str | None
    source: str            # "MEMBERSHIP" | "TRIAL" | "NONE"
    remaining: int | None  # None = unlimited
    trial_grant_id: str | None = None

async def entitlements(db, user_id, cls=None, *, projected_plan: str | None = None) -> Entitlement:
    """Membership first, trial second. projected_plan comes ONLY from the server-validated bundle handoff."""
    plan = projected_plan or await active_plan_code(db, user_id)
    if plan:
        perks = await plan_perks(db, plan)
        if cls and cls.allowed_plans and plan not in cls.allowed_plans:
            return Entitlement(False, "PLAN_NOT_ALLOWED", "MEMBERSHIP", None)
        cap = perks["group_classes_per_month"]                       # None = unlimited
        if cap is None or projected_plan:                           # projected plan: assume a fresh allowance
            return Entitlement(True, None, "MEMBERSHIP", cap)
        used = await classes_used_this_cycle(db, user_id)
        return Entitlement(used < cap, None if used < cap else "NO_CREDITS", "MEMBERSHIP", max(cap - used, 0))
    trial = await active_trial(db, user_id)                          # classes_used < classes_total and not expired
    if trial and (cls is None or cls.trial_eligible):
        return Entitlement(True, None, "TRIAL", trial.classes_total - trial.classes_used, str(trial.id))
    if trial and cls and not cls.trial_eligible:
        return Entitlement(False, "CLASS_NOT_TRIAL_ELIGIBLE", "TRIAL", trial.classes_total - trial.classes_used)
    return Entitlement(False, "NO_PLAN_CHOOSE_ONE", "NONE", 0)

@tool("propose_booking", ProposeBookingArgs, roles={"USER"}, kind="propose")
async def propose_booking(args, ctx):
    cls = await get_class(ctx.db, args.class_id)
    if not cls or cls.status != "SCHEDULED" or cls.start_time <= now_utc():
        return {"ok": False, "error": "CLASS_UNAVAILABLE"}
    if cls.booked_count >= cls.capacity:
        return {"ok": False, "error": "CLASS_FULL"}
    rules = await class_rules(ctx.db, ctx.session, cls)                # level, age, cutoff, injury (from consented profile)
    if not rules.ok:
        return {"ok": False, "error": "RULE_FAILED", "failures": rules.failures}
    conflicts = await find_conflicts(ctx.db, ctx.session.user_id, cls)
    if conflicts:
        return {"ok": False, "error": "CONFLICT", "conflicts": conflicts}
    projected = ctx.handoff_projected_plan()                           # server-validated, may be None
    ent = await entitlements(ctx.db, ctx.session.user_id, cls, projected_plan=projected)
    if not ent.can_book:
        return {"ok": False, "error": "NO_ENTITLEMENT", "detail": ent.reason}
    uses = {"MEMBERSHIP": "Uses 1 class credit" if ent.remaining is not None else "Included in your plan",
            "TRIAL": f"Uses 1 trial class ({ent.remaining - 1} left after)"}[ent.source]
    summary = f"Book {cls.title}, {fmt_local(cls.start_time, ctx.session.timezone)}. {uses}."
    action = await create_pending(ctx.db, ctx.session.user_id, "BOOK_CLASS",
                                  {"class_id": str(cls.id)}, summary, ttl_min=settings.pending_ttl)
    return {"ok": True, "action_id": str(action.id), "summary": summary, "expires_at": action.expires_at.isoformat()}
```
