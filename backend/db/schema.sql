-- 6. Complete PostgreSQL schema (DDL)
-- Generated from spec section 6

-- 6.1 Extensions, enums and settings
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- exclusion constraints on uuid + ranges
CREATE EXTENSION IF NOT EXISTS citext;       -- case-insensitive email

-- Enum types
CREATE TYPE user_role           AS ENUM ('USER', 'TRAINER', 'ADMIN');
CREATE TYPE account_status      AS ENUM ('PENDING_EMAIL','PENDING_APPROVAL','PENDING_ADMIN_CODE','ACTIVE','REJECTED','EXPIRED','SUSPENDED');
CREATE TYPE request_status      AS ENUM ('PENDING','APPROVED','REJECTED','EXPIRED','CANCELLED');
CREATE TYPE gender_type         AS ENUM ('MALE','FEMALE','OTHER','UNSPECIFIED');
CREATE TYPE fitness_goal_type   AS ENUM ('FAT_LOSS','MUSCLE_GAIN','ENDURANCE','REHABILITATION','MAINTENANCE');
CREATE TYPE fitness_level_type  AS ENUM ('BEGINNER','INTERMEDIATE','ADVANCED');
CREATE TYPE class_category      AS ENUM ('HIIT','YOGA','PILATES','SPIN','STRENGTH','ZUMBA','SWIMMING','RECOVERY');
CREATE TYPE class_status        AS ENUM ('DRAFT','SCHEDULED','IN_PROGRESS','COMPLETED','CANCELLED');
CREATE TYPE booking_status      AS ENUM ('CONFIRMED','WAITLISTED','CANCELLED','ATTENDED','NO_SHOW');
CREATE TYPE membership_status   AS ENUM ('ACTIVE','EXPIRED','PENDING','CANCELLED','REPLACED');
CREATE TYPE billing_cycle_type  AS ENUM ('MONTHLY','ANNUAL');
CREATE TYPE impact_level        AS ENUM ('LOW','MODERATE','HIGH');
CREATE TYPE action_type AS ENUM (
  -- USER
  'BOOK_CLASS','CANCEL_BOOKING','JOIN_WAITLIST','CHANGE_PLAN','RENEW_PLAN','SAVE_NUTRITION_PLAN',
  'SEND_BOOKING_EMAIL','SUBMIT_ISSUE_REPORT',
  -- TRAINER
  'CREATE_CLASS','CREATE_CLASS_SERIES','UPDATE_CLASS_RESTRICTIONS','CANCEL_CLASS','SET_AVAILABILITY','SET_TIME_OFF',
  -- ADMIN (note: there is deliberately NO action type for approving an admin-role request)
  'ADMIN_VERIFY_TRAINER','ADMIN_DECIDE_TRAINER_REQUEST','ADMIN_BROADCAST','ADMIN_MESSAGE_USER',
  'ADMIN_GRANT_MEMBERSHIP','ADMIN_INVITE_STAFF','ADMIN_UPDATE_ISSUE');
CREATE TYPE action_status       AS ENUM ('PENDING','CONFIRMED','AWAITING_PAYMENT','EXECUTED','EXPIRED','REJECTED','FAILED','SKIPPED','CANCELLED');
CREATE TYPE bundle_status       AS ENUM ('PENDING','CONFIRMING','AWAITING_PAYMENT','EXECUTED','PARTIAL','FAILED','EXPIRED','REJECTED');
CREATE TYPE payment_status      AS ENUM ('CREATED','PAID','FAILED','EXPIRED','NEEDS_REVIEW','REFUNDED','PARTIALLY_REFUNDED');
CREATE TYPE issue_category      AS ENUM ('CLASS_QUALITY','TRAINER_CONDUCT','FACILITY','SAFETY','HARASSMENT','INJURY','BILLING','OTHER');
CREATE TYPE issue_severity      AS ENUM ('LOW','MEDIUM','HIGH','URGENT');
CREATE TYPE issue_status        AS ENUM ('NEW','IN_REVIEW','ACTIONED','CLOSED');

-- Global settings: single source of truth for prompts, rules and limits
CREATE TABLE gym_settings (
    key        VARCHAR(80) PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO gym_settings (key, value) VALUES
  ('timezone',                     '"Asia/Kolkata"'),
  ('booking_buffer_minutes',       '15'),
  ('late_cancel_hours',            '2'),
  ('pending_action_ttl_min',       '10'),
  ('min_group_size_reports',       '5'),
  ('trial_classes',                '3'),
  ('trial_days',                   '14'),
  ('verification_ttl_hours',       '24'),
  ('reset_ttl_min',                '30'),
  ('admin_code_ttl_min',           '30'),
  ('admin_code_max_attempts',      '5'),
  ('admin_pending_max',            '3'),
  ('admin_cooling_off_hours',      '24'),
  ('trainer_request_expiry_days',  '14'),
  ('trainer_reapply_days',         '7'),
  ('issue_reports_per_day',        '5'),
  ('bundle_max_steps',             '5'),
  ('email_daily_cap_per_user',     '10'),
  ('payment_order_ttl_min',        '15'),
  ('require_verified_trainer_for_publish', 'false');

-- 6.2 Users, authentication tables and role requests
CREATE TABLE users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email            CITEXT NOT NULL UNIQUE,
    password_hash    VARCHAR(255) NOT NULL,
    full_name        VARCHAR(100) NOT NULL,
    role             user_role NOT NULL DEFAULT 'USER',
    requested_role   user_role,                          -- what the person asked for at sign-up (no privileges yet)
    account_status   account_status NOT NULL DEFAULT 'PENDING_EMAIL',
    email_verified_at TIMESTAMPTZ,
    phone            VARCHAR(20),
    phone_hash       CHAR(64),                           -- HMAC of normalized phone, for trial uniqueness
    locale           VARCHAR(10) NOT NULL DEFAULT 'en',
    timezone         VARCHAR(64),                        -- NULL = gym default
    failed_logins    INT NOT NULL DEFAULT 0,
    locked_until     TIMESTAMPTZ,
    token_version    INT NOT NULL DEFAULT 0,             -- bump to revoke all access tokens
    terms_accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cooling_off_until TIMESTAMPTZ,                       -- new admins: restricted actions until then
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at       TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_users_phone_hash ON users (phone_hash) WHERE phone_hash IS NOT NULL AND deleted_at IS NULL;

-- Single-use tokens. Only SHA-256 hashes are stored, never the token itself.
CREATE TABLE email_verifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX uq_one_active_verification ON email_verifications (user_id) WHERE used_at IS NULL;

CREATE TABLE password_resets (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX uq_one_active_reset ON password_resets (user_id) WHERE used_at IS NULL;

-- Refresh tokens: rotation with reuse detection
CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id   UUID NOT NULL,                           -- all rotations of one login share a family
    token_hash  CHAR(64) NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    rotated_at  TIMESTAMPTZ,                             -- set when exchanged; reuse after this revokes the family
    revoked_at  TIMESTAMPTZ,
    ip_hash     CHAR(64),
    user_agent  VARCHAR(200),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_refresh_family ON refresh_tokens (family_id);

-- Role requests: trainer approvals and admin one-time-code activation
CREATE TABLE role_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requested_role  user_role NOT NULL CHECK (requested_role IN ('TRAINER','ADMIN')),
    status          request_status NOT NULL DEFAULT 'PENDING',
    code_hmac       CHAR(64),                            -- ADMIN only; HMAC-SHA256 of the 8-char code
    code_expires_at TIMESTAMPTZ,
    attempts        INT NOT NULL DEFAULT 0,
    decided_by      UUID REFERENCES users(id),
    decided_at      TIMESTAMPTZ,
    reason          TEXT,
    info_requested  TEXT,                                -- "ask for more information" note
    request_ip_hash CHAR(64),
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_admin_code CHECK (requested_role <> 'ADMIN' OR code_hmac IS NOT NULL)
);
CREATE UNIQUE INDEX uq_one_pending_request ON role_requests (user_id) WHERE status = 'PENDING';
CREATE INDEX idx_role_requests_queue ON role_requests (requested_role, status, created_at);

CREATE TABLE trainer_applications (
    request_id      UUID PRIMARY KEY REFERENCES role_requests(id) ON DELETE CASCADE,
    specializations TEXT[] NOT NULL DEFAULT '{}',
    claimed_certifications TEXT[] NOT NULL DEFAULT '{}',
    bio             TEXT,
    document_refs   TEXT[] NOT NULL DEFAULT '{}',        -- optional uploads
    risk_hints      JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {"duplicate_phone":false,"disposable_email":false}
    review_notes    TEXT
);

-- Optional trainer-invite shortcut: skips the approval step because an admin already decided
CREATE TABLE staff_invites (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       CITEXT NOT NULL,
    role        user_role NOT NULL CHECK (role = 'TRAINER'),          -- v1: trainer invites only; there are no admin invites
    token_hash  CHAR(64) NOT NULL UNIQUE,
    invited_by  UUID NOT NULL REFERENCES users(id),
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Privilege escalation guard: role can become TRAINER or ADMIN only via an approved request or the seed role
CREATE OR REPLACE FUNCTION guard_role_change() RETURNS trigger AS $$
BEGIN
  IF NEW.role IN ('TRAINER','ADMIN') AND (TG_OP = 'INSERT' OR NEW.role IS DISTINCT FROM OLD.role) THEN
    IF current_user = 'gympro_seed' THEN
      RETURN NEW;                                         -- first admin and test fixtures only
    END IF;
    IF TG_OP = 'INSERT' OR NOT EXISTS (
         SELECT 1 FROM role_requests rr
          WHERE rr.user_id = NEW.id AND rr.requested_role = NEW.role
            AND rr.status = 'APPROVED' AND rr.decided_at > NOW() - INTERVAL '5 minutes') THEN
      RAISE EXCEPTION 'role change to % requires an approved role_request', NEW.role USING ERRCODE = '42501';
    END IF;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_guard_role BEFORE INSERT OR UPDATE OF role ON users
  FOR EACH ROW EXECUTE FUNCTION guard_role_change();
-- Invite acceptance and approved requests set the role inside the same transaction that marks the request APPROVED.
-- Accepting a trainer invite first inserts an APPROVED role_requests row (decided_by = inviter, decided_at = now()).

-- 6.3 Trainers, availability and reviews
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

-- 6.4 Member profile (intake), consent and history
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

-- 6.5 Plans, memberships and trial
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

-- 6.6 Classes, series, restrictions and bookings
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

-- 6.7 Telemetry and nutrition
CREATE TABLE daily_health_logs (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date               DATE NOT NULL,
    steps_walked           INT NOT NULL DEFAULT 0 CHECK (steps_walked >= 0),
    active_calories_burned INT NOT NULL DEFAULT 0 CHECK (active_calories_burned >= 0),
    water_intake_ml        INT NOT NULL DEFAULT 0 CHECK (water_intake_ml >= 0),
    hours_slept            NUMERIC(3,1) CHECK (hours_slept BETWEEN 0 AND 24),   -- NULL = not logged (no fake default)
    wearable_data          JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (user_id, log_date)
);

CREATE TABLE nutrition_plans (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dietary_preference VARCHAR(50) NOT NULL,
    target_calories    INT NOT NULL CHECK (target_calories BETWEEN 800 AND 6000),
    protein_grams      INT NOT NULL CHECK (protein_grams >= 0),
    carb_grams         INT NOT NULL CHECK (carb_grams >= 0),
    fat_grams          INT NOT NULL CHECK (fat_grams >= 0),
    meal_plan_details  JSONB NOT NULL,
    prompt_version     VARCHAR(20) NOT NULL,             -- reproducibility
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6.8 Pending actions and bundles (the confirmation boundary)
CREATE TABLE action_bundles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_id      UUID,
    status      bundle_status NOT NULL DEFAULT 'PENDING',
    summary     TEXT NOT NULL,                            -- card headline
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at TIMESTAMPTZ
);

CREATE TABLE pending_actions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- the actor (any role)
    run_id        UUID,
    bundle_id     UUID REFERENCES action_bundles(id) ON DELETE CASCADE,
    step_no       SMALLINT,                                -- 1-based order inside a bundle
    depends_on    SMALLINT[] NOT NULL DEFAULT '{}',        -- step numbers that must be EXECUTED first
    type          action_type NOT NULL,
    payload       JSONB NOT NULL,                          -- validated by Pydantic before insert
    projected     JSONB,                                   -- effects used by later steps (plan after upgrade, etc.)
    summary       TEXT NOT NULL,                           -- human-readable, shown on the confirm card
    status        action_status NOT NULL DEFAULT 'PENDING',
    result        JSONB,
    expires_at    TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at   TIMESTAMPTZ,
    CONSTRAINT chk_bundle_step CHECK ((bundle_id IS NULL AND step_no IS NULL) OR (bundle_id IS NOT NULL AND step_no IS NOT NULL)),
    UNIQUE (bundle_id, step_no)
);
CREATE INDEX idx_pending_user ON pending_actions (user_id, status, expires_at);

-- Payments (Razorpay). Money in minor units (paise for INR). No card or UPI data is ever stored.
CREATE TABLE payments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,   -- financial records are kept; accounts are soft-deleted
    action_id           UUID NOT NULL UNIQUE REFERENCES pending_actions(id),     -- one payment per confirmed action
    provider            VARCHAR(12) NOT NULL CHECK (provider IN ('RAZORPAY','MOCK','NONE')),
    purpose             VARCHAR(20) NOT NULL DEFAULT 'PLAN_CHANGE',              -- PLAN_CHANGE | PLAN_RENEWAL
    amount_minor        BIGINT NOT NULL CHECK (amount_minor >= 0),
    currency            CHAR(3) NOT NULL,
    status              payment_status NOT NULL DEFAULT 'CREATED',
    razorpay_order_id   VARCHAR(40) UNIQUE,
    razorpay_payment_id VARCHAR(40) UNIQUE,
    quote               JSONB NOT NULL,                                          -- from_plan, to_plan, cycle, prorated total, next_billing_date
    membership_id       UUID REFERENCES memberships(id),                         -- set when activated
    attempts            INT NOT NULL DEFAULT 0,                                  -- payment.failed events seen
    refunded_minor      BIGINT NOT NULL DEFAULT 0 CHECK (refunded_minor >= 0),
    failure_code        VARCHAR(40),
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at             TIMESTAMPTZ,
    CONSTRAINT chk_refund_le_amount CHECK (refunded_minor <= amount_minor)
);
CREATE INDEX idx_payments_open ON payments (status, created_at) WHERE status = 'CREATED';
CREATE INDEX idx_payments_user ON payments (user_id, created_at DESC);

-- Webhook deduplication: Razorpay sends a unique event id header with every delivery
CREATE TABLE payment_events (
    event_id    VARCHAR(80) PRIMARY KEY,
    event       VARCHAR(60) NOT NULL,
    order_id    VARCHAR(40),
    payload     JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6.9 Issue reports
CREATE TABLE issue_reports (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    class_id      UUID REFERENCES fitness_classes(id) ON DELETE SET NULL,
    trainer_id    UUID REFERENCES trainer_profiles(trainer_id) ON DELETE SET NULL,
    category      issue_category NOT NULL,
    severity      issue_severity NOT NULL,
    user_words    TEXT NOT NULL,                          -- the member's own words, stored verbatim
    ai_summary    TEXT,                                   -- neutral, labeled "user-reported" in the UI
    status        issue_status NOT NULL DEFAULT 'NEW',
    admin_action  VARCHAR(40),                            -- CONTACT_USER | WARN_TRAINER | ESCALATE | NONE
    handled_by    UUID REFERENCES users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    handled_at    TIMESTAMPTZ
);
CREATE INDEX idx_issues_queue ON issue_reports (status, severity, created_at);

-- 6.10 Outbox, notifications, email log, preferences and feedback
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

-- 6.11 Agent observability, prompt registry and audit
CREATE TABLE prompt_versions (
    agent       VARCHAR(40) NOT NULL,
    version     VARCHAR(20) NOT NULL,                    -- semver
    sha256      CHAR(64) NOT NULL,
    eval_score  NUMERIC(5,2),                            -- last passing eval run
    released_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent, version)
);
CREATE TABLE agent_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID REFERENCES users(id) ON DELETE SET NULL,
    trace_id      VARCHAR(64) NOT NULL,
    query_redacted TEXT,                                 -- PII-scrubbed
    plan          JSONB,
    final_status  VARCHAR(20),
    prompt_versions JSONB,                               -- {"SCHEDULE":"1.0.0", ...}
    model         VARCHAR(80),
    tokens_in     INT, tokens_out INT, latency_ms INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE agent_tool_calls (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    agent       VARCHAR(40) NOT NULL,
    tool        VARCHAR(60) NOT NULL,
    args_redacted JSONB,
    ok          BOOLEAN NOT NULL,
    error_code  VARCHAR(40),
    latency_ms  INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE audit_log (
    id         BIGSERIAL PRIMARY KEY,
    actor_id   UUID, action VARCHAR(60) NOT NULL, entity VARCHAR(60), entity_id UUID,
    details    JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6.12 Indexes
CREATE INDEX idx_classes_schedule   ON fitness_classes (start_time, status);
CREATE INDEX idx_classes_trainer    ON fitness_classes (trainer_id, start_time);
CREATE INDEX idx_bookings_user      ON class_bookings (user_id, status);
CREATE INDEX idx_health_user_date   ON daily_health_logs (user_id, log_date DESC);
CREATE INDEX idx_runs_user_time     ON agent_runs (user_id, created_at DESC);
CREATE INDEX idx_audit_entity       ON audit_log (entity, entity_id, created_at DESC);
CREATE INDEX idx_users_status       ON users (account_status, role);

-- 6.13 Row-level security
ALTER TABLE member_profiles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE member_intake_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_health_logs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE class_bookings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE nutrition_plans       ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_actions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_bundles        ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications         ENABLE ROW LEVEL SECURITY;
ALTER TABLE trial_grants          ENABLE ROW LEVEL SECURITY;
ALTER TABLE issue_reports         ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback              ENABLE ROW LEVEL SECURITY;

-- Own rows (USER, and the actor of a pending action for any role)
CREATE POLICY own_rows ON member_profiles        USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_rows ON member_intake_versions USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_rows ON daily_health_logs      USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_rows ON nutrition_plans        USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_rows ON pending_actions        USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_rows ON action_bundles         USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_rows ON trial_grants           USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_rows ON feedback               USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY own_rows ON notifications          USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid OR current_setting('app.role', true) = 'SYSTEM');
CREATE POLICY own_rows ON class_bookings         USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid OR current_setting('app.role', true) = 'SYSTEM');

-- Issue reports: reporter sees and creates own; ADMIN reads and updates all; trainers never see them
CREATE POLICY reporter_rows ON issue_reports USING (reporter_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY admin_all     ON issue_reports USING (current_setting('app.role', true) = 'ADMIN');

-- ADMIN SELECT exists only for aggregate queries. No REST endpoint and no tool may return per-member booking rows to ADMIN (enforced by the registry scan test and the admin data-access tests).
-- TRAINER reads bookings of own classes (first names resolved by a view)
CREATE POLICY admin_read   ON class_bookings FOR SELECT USING (current_setting('app.role', true) = 'ADMIN');
CREATE POLICY trainer_read ON class_bookings FOR SELECT USING (
    current_setting('app.role', true) = 'TRAINER'
    AND class_id IN (SELECT id FROM fitness_classes WHERE trainer_id = nullif(current_setting('app.user_id', true), '')::uuid));

-- SYSTEM (workers, executors, set only in server code) may act on any row inside a transaction
CREATE POLICY system_all ON member_profiles  USING (current_setting('app.role', true) = 'SYSTEM');
CREATE POLICY system_all ON pending_actions  USING (current_setting('app.role', true) = 'SYSTEM');
CREATE POLICY system_all ON action_bundles   USING (current_setting('app.role', true) = 'SYSTEM');
CREATE POLICY system_all ON nutrition_plans  USING (current_setting('app.role', true) = 'SYSTEM');
CREATE POLICY system_all ON daily_health_logs USING (current_setting('app.role', true) = 'SYSTEM');
CREATE POLICY system_all ON trial_grants     USING (current_setting('app.role', true) = 'SYSTEM');
CREATE POLICY system_all ON member_intake_versions USING (current_setting('app.role', true) = 'SYSTEM');
CREATE POLICY system_all ON issue_reports    USING (current_setting('app.role', true) = 'SYSTEM');

ALTER TABLE class_bookings         FORCE ROW LEVEL SECURITY;
ALTER TABLE member_profiles        FORCE ROW LEVEL SECURITY;
ALTER TABLE member_intake_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE daily_health_logs      FORCE ROW LEVEL SECURITY;
ALTER TABLE nutrition_plans        FORCE ROW LEVEL SECURITY;
ALTER TABLE pending_actions        FORCE ROW LEVEL SECURITY;
ALTER TABLE action_bundles         FORCE ROW LEVEL SECURITY;
ALTER TABLE notifications          FORCE ROW LEVEL SECURITY;
ALTER TABLE trial_grants           FORCE ROW LEVEL SECURITY;
ALTER TABLE issue_reports          FORCE ROW LEVEL SECURITY;
ALTER TABLE feedback               FORCE ROW LEVEL SECURITY;

-- Payments: owner reads own rows; ADMIN reads for the review queue; writes only as SYSTEM (executor, webhook, reconciler)
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments FORCE ROW LEVEL SECURITY;
CREATE POLICY own_rows   ON payments FOR SELECT USING (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
CREATE POLICY admin_read ON payments FOR SELECT USING (current_setting('app.role', true) = 'ADMIN');
CREATE POLICY system_all ON payments USING (current_setting('app.role', true) = 'SYSTEM');

-- 6.14 Roles and grants (least privilege)
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gympro_app') THEN
    CREATE ROLE gympro_app LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gympro_analytics') THEN
    CREATE ROLE gympro_analytics LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gympro_seed') THEN
    CREATE ROLE gympro_seed LOGIN PASSWORD 'change-me' NOSUPERUSER NOBYPASSRLS;   -- first admin only, used by the seed command
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO gympro_app, gympro_analytics, gympro_seed;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gympro_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO gympro_app;
REVOKE UPDATE, DELETE ON audit_log FROM gympro_app;
REVOKE UPDATE, DELETE ON member_intake_versions FROM gympro_app;
REVOKE UPDATE, DELETE ON email_log FROM gympro_app;
REVOKE DELETE ON payments, payment_events FROM gympro_app;

-- gympro_app : API, workers, executors
-- gympro_analytics : SELECT only on analytics views (v_*), statement_timeout = 5s, used by ADMIN_INSIGHTS tools
-- gympro_seed : INSERT/UPDATE on users only, used by `python -m app.seed_admin`
GRANT SELECT ON v_class_occupancy TO gympro_analytics;
GRANT SELECT, INSERT, UPDATE ON users TO gympro_seed;
GRANT INSERT ON audit_log TO gympro_seed;
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO gympro_seed;
ALTER ROLE gympro_analytics SET statement_timeout = '5s';
