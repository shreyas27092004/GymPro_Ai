# Phase P6: Executors

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
`executor/single.py`, `executor/bundles.py`, `executor/handlers.py`, expiry jobs, `POST /api/actions/{id}/confirm`, `POST /api/bundles/{id}/confirm`

## Gate (must pass before you stop)
`pytest tests/executor -q`: 8 concurrent confirms for the last spot give exactly one booking; same-user overlap race gives one success; double-confirm replay is safe; bundle order, skip on failed dependency, independent step still runs, `PRICE_CHANGED`, expired action

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P6b.

---

# Spec sections for this phase (copied from the full spec)

### 8.1 Tool catalog (authorization lives in the registry, not in prompts)

`kind`: **read** (no state change), **calc** (deterministic calculator), **propose** (creates a `pending_actions` row only). **No agent has any write tool.**

| Agent | Tool | Kind | Roles | Needs health consent | Notes |
| :--- | :--- | :--- | :--- | :---: | :--- |
| SCHEDULE | `search_classes` | read | USER | | Filters by safety constraints |
| SCHEDULE | `match_class_name` | read | USER | | Fuzzy match (trigram plus token similarity) |
| SCHEDULE | `get_my_bookings` | read | USER | | Own rows only |
| SCHEDULE | `check_conflicts` | read | USER | | Overlap and buffer |
| SCHEDULE | `check_class_rules` | read | USER | | Level, age, plan, trial, cutoff, injury, status |
| SCHEDULE | `get_membership_entitlements` | read | USER | | `use_projected` reads server-validated handoff |
| SCHEDULE | `propose_booking`, `propose_cancellation`, `propose_waitlist` | propose | USER | | |
| MEMBERSHIP | `list_plans`, `get_highest_plan`, `get_my_membership`, `get_trial_status`, `get_usage_summary` | read | USER | | |
| MEMBERSHIP | `price_diff` | calc | USER | | Proration from dates |
| MEMBERSHIP | `propose_plan_change`, `propose_renewal` | propose | USER | | Upgrade replaces the old membership |
| FITNESS | `get_my_intake` | read | USER | Yes | |
| FITNESS | `search_exercise_kb`, `get_class_catalog_summary` | read | USER | | KB passages are untrusted data |
| FITNESS | `calc_progression` | calc | USER | | |
| WELLNESS | `get_my_health_profile` | read | USER | Yes | |
| WELLNESS | `calc_energy`, `calc_bmi`, `calc_hydration` | calc | USER | | Mifflin-St Jeor, caps in tool |
| WELLNESS | `get_injury_protocol`, `get_crisis_resources` | read | USER | | Protocols reviewed by a physio |
| NUTRITION | `get_my_nutrition_inputs` | read | USER | Yes | |
| NUTRITION | `compute_macros` | calc | USER | | 4/4/9, sums within 1% |
| NUTRITION | `search_nutrition_kb`, `find_foods` | read | USER | | `find_foods` excludes allergens |
| NUTRITION | `propose_save_plan` | propose | USER | | |
| TRAINER_INFO | `search_trainers`, `get_trainer_profile`, `get_trainer_review_summary`, `get_trainer_availability` | read | USER | | Verified credentials only |
| SUPPORT | `get_my_bookings`, `get_todays_classes_for_me`, `get_support_guidance` | read | USER | | |
| SUPPORT | `propose_issue_report` | propose | USER | | Severity floors, daily cap |
| COMMS | `list_templates`, `get_template`, `get_booking_for_email`, `get_weekly_summary_numbers`, `get_notification_prefs` | read | USER, SYSTEM | | |
| COMMS | `propose_send_email` | propose | USER | | **No recipient argument** |
| TRAINER_OPS | `get_my_availability`, `get_my_classes`, `get_class_roster`, `get_feedback_summary`, `preview_series` | read | TRAINER | | Own data, first names only |
| TRAINER_OPS | `propose_create_class`, `propose_create_series`, `propose_update_restrictions`, `propose_cancel_class`, `propose_set_availability`, `propose_set_time_off` | propose | TRAINER | | |
| ADMIN_INSIGHTS | `get_metric`, `compare_periods`, `get_data_quality_report`, `get_daily_digest_numbers`, `list_classes_below_fill`, `get_audience_preview` | read | ADMIN | | `gympro_analytics` role, k-anonymity |
| ADMIN_INSIGHTS | `get_issue_queue`, `get_issue`, `get_trainer_requests`, `get_trainer_request` | read | ADMIN | | Reporter shown as "a member" |
| ADMIN_INSIGHTS | `propose_decide_trainer_request`, `propose_verify_trainer`, `propose_update_issue`, `propose_message_user`, `propose_cancel_class`, `propose_grant_membership`, `propose_broadcast`, `propose_invite_staff` (trainer only) | propose | ADMIN (not in cooling-off for some) | | **No tool exists for admin-role requests** |

**Executors (run only from the confirm endpoints, no LLM)**

| Action type | Executor checks at execution time |
| :--- | :--- |
| `BOOK_CLASS` | Per-user advisory lock, class row lock, status and time, conflicts, entitlements (membership first, trial second), class rules, capacity. Consumes a credit or a trial class. Enqueues `email.booking` |
| `CANCEL_BOOKING` | Ownership, late-cancel rule, refunds the credit or trial class if not late, promotes the oldest eligible waitlisted member in the same transaction |
| `JOIN_WAITLIST` | Active-booking uniqueness, FIFO sequence |
| `CHANGE_PLAN` | Plan active, price re-computed (must equal the confirmed price within 0.01 or fail with `PRICE_CHANGED`), payment through the provider adapter (`mock`: instant; `razorpay`: order created and the step pauses as `AWAITING_PAYMENT` until the payment is verified, section 8.15), old membership set to `REPLACED`, new membership `ACTIVE` |
| `SEND_BOOKING_EMAIL` | `requires_step` executed, recipient equals the account email (read at execution), daily cap, enqueues outbox |
| `SUBMIT_ISSUE_REPORT` | Ownership of the class booking, daily cap, severity floor, inserts `issue_reports`, alerts admins (immediately for SAFETY, HARASSMENT, INJURY) |
| `CREATE_CLASS`, `CREATE_CLASS_SERIES` | Trainer owns it, availability, time off, overlap constraint, creates only OK instances |
| `UPDATE_CLASS_RESTRICTIONS`, `CANCEL_CLASS` | Ownership (or admin), notifies affected members, handles waitlist and credits |
| `ADMIN_DECIDE_TRAINER_REQUEST` | Actor is ADMIN, not in cooling-off, request still PENDING and of type TRAINER, sets role in the same transaction that marks the request APPROVED (trigger satisfied), emails the trainer |
| `ADMIN_BROADCAST` | Not in cooling-off, audience recomputed, unsubscribe respected, per-admin daily cap |

---

### 8.9 Deterministic executors

```python
# app/executor/single.py   POST /api/actions/{action_id}/confirm   (no LLM anywhere in this path)
@router.post("/api/actions/{action_id}/confirm")
async def confirm_action(action_id: UUID, s: SessionContext = Depends(get_session), db=Depends(get_db)):
    async with db.begin():
        await set_rls(db, s.user_id, s.role)                              # SET LOCAL app.user_id / app.role
        action = (await db.execute(select(PendingAction).where(PendingAction.id == action_id)
                  .with_for_update())).scalar_one_or_none()
        if not action or str(action.user_id) != s.user_id:
            raise HTTPException(404)
        if action.bundle_id:
            raise HTTPException(409, "This action belongs to a bundle; confirm the bundle")
        if action.status == "EXECUTED":
            return action.result                                           # idempotent replay
        if action.status != "PENDING" or action.expires_at < utcnow():
            raise HTTPException(409, "ACTION_EXPIRED")
        return await run_action(db, s, action)

async def run_action(db, s, action) -> dict:
    handler = HANDLERS[action.type]                                       # one function per action type
    if action.type in ADMIN_ONLY and (s.role != "ADMIN" or s.cooling_off_active):
        result = {"ok": False, "error": "FORBIDDEN"}
    else:
        result = await handler(db, s, action)                             # may return a business error
    if result.get("awaiting"):                                            # payment pending: neither executed nor failed
        action.status, action.result = "AWAITING_PAYMENT", result
        return result
    action.status = "EXECUTED" if result["ok"] else "FAILED"
    action.result, action.executed_at = result, utcnow()
    db.add(AuditLog(actor_id=s.user_id, action=f"EXEC_{action.type}", entity="pending_actions", entity_id=action.id))
    return result
```

```python
# app/executor/handlers.py
async def exec_book(db, s, action):
    p = BookPayload.model_validate(action.payload)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:u, 0))"), {"u": s.user_id})  # no overlapping double-book races
    cls = (await db.execute(select(FitnessClass).where(FitnessClass.id == p.class_id).with_for_update())).scalar_one_or_none()
    if not cls or cls.status != "SCHEDULED" or cls.start_time <= utcnow():
        return {"ok": False, "error": "CLASS_UNAVAILABLE"}
    if not (await class_rules(db, s, cls)).ok:
        return {"ok": False, "error": "RULE_FAILED"}
    if await find_conflicts(db, s.user_id, cls):
        return {"ok": False, "error": "CONFLICT"}
    ent = await entitlements(db, s.user_id, cls)                          # real state now (an upgrade step has already run)
    if not ent.can_book:
        return {"ok": False, "error": "NO_ENTITLEMENT", "detail": ent.reason}
    if cls.booked_count >= cls.capacity:
        return {"ok": False, "error": "CLASS_FULL", "hint": "offer_waitlist"}
    try:
        booking = Booking(user_id=s.user_id, class_id=cls.id, status="CONFIRMED", idempotency_key=action.id,
                          used_trial_grant=ent.trial_grant_id)
        db.add(booking); cls.booked_count += 1
        if ent.source == "TRIAL":
            await db.execute(text("UPDATE trial_grants SET classes_used = classes_used + 1 WHERE id = :g"), {"g": ent.trial_grant_id})
        await db.flush()                                                   # partial unique index catches duplicates
    except IntegrityError:
        return {"ok": False, "error": "ALREADY_BOOKED"}
    await enqueue(db, user_id=s.user_id, routing_key="email.booking", template="CLASS_CONFIRMED",
                  params={"class_id": str(cls.id), "booking_id": str(booking.id)}, dedupe_key=f"confirm:{booking.id}")
    return {"ok": True, "booking_id": str(booking.id), "class_id": str(cls.id)}

async def exec_change_plan(db, s, action):
    p = ChangePlanPayload.model_validate(action.payload)                   # to_plan, cycle, confirmed_total
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:u, 1))"), {"u": s.user_id})
    plan = await get_plan(db, p.to_plan)
    if not plan or not plan.is_active:
        return {"ok": False, "error": "PLAN_UNAVAILABLE"}
    quote = await price_diff(db, s.user_id, p.to_plan, p.cycle)            # recomputed now
    if abs(quote.prorated_today - p.confirmed_total) > Decimal("0.01"):
        return {"ok": False, "error": "PRICE_CHANGED", "new_total": quote.prorated_today}
    pay = await payments.begin(db, s, action, quote)                        # section 8.15
    if pay.state == "AWAITING":                                             # Razorpay: the browser must pay first
        return {"ok": None, "awaiting": pay.checkout}                       # action -> AWAITING_PAYMENT, bundle pauses
    if pay.state != "PAID":
        return {"ok": False, "error": pay.error}                            # PAYMENT_PROVIDER_REQUIRED and similar
    return await activate_plan(db, s, p, quote, pay.id)

async def activate_plan(db, s, p, quote, payment_id):
    """Swap the membership. Shared by the mock path and finalize_paid, so there is exactly one implementation."""
    old = await active_membership(db, s.user_id, for_update=True)
    if (old.plan_code if old else None) != quote.from_plan:                 # the user's plan changed since the quote
        return {"ok": False, "error": "CONFLICT"}
    new = Membership(user_id=s.user_id, plan_code=p.to_plan, status="ACTIVE", billing_cycle=p.cycle,
                     price_paid=quote.prorated_today, end_date=quote.next_billing_date)
    if old:
        old.status = "REPLACED"; old.end_date = today(); await db.flush()   # frees uq_one_active_membership
    db.add(new); await db.flush()
    if old:
        old.replaced_by = new.id
    await link_payment_to_membership(db, payment_id, new.id)
    await enqueue(db, user_id=s.user_id, routing_key="email.plan", template="PLAN_CHANGED",
                  params={"plan": p.to_plan}, dedupe_key=f"plan:{new.id}")
    return {"ok": True, "membership_id": str(new.id), "plan": p.to_plan}

async def exec_send_booking_email(db, s, action):
    p = SendEmailPayload.model_validate(action.payload)                    # template_id, params, attach_calendar, requires_step
    to_email = await account_email(db, s.user_id)                          # read at execution: the user's OWN address
    if not await email_cap_ok(db, s.user_id):
        return {"ok": False, "error": "EMAIL_CAP_REACHED"}
    params = dict(p.params)
    if p.requires_step is not None:
        prior = await step_result(db, action.bundle_id, p.requires_step)   # bundle executor guarantees it is EXECUTED
        params["booking_id"] = prior["booking_id"]
    await enqueue(db, user_id=s.user_id, routing_key="email.booking", template=p.template_id,
                  params={**params, "attach_calendar": p.attach_calendar},
                  dedupe_key=f"email:{action.id}")                          # worker resolves the address again from users
    return {"ok": True, "to_masked": mask(to_email)}

async def exec_issue_report(db, s, action):
    p = IssuePayload.model_validate(action.payload)
    if await reports_today(db, s.user_id) >= settings_int(db, "issue_reports_per_day"):
        return {"ok": False, "error": "REPORT_LIMIT_REACHED"}
    if p.class_id and not await user_attended_or_booked(db, s.user_id, p.class_id):
        return {"ok": False, "error": "CLASS_NOT_YOURS"}
    severity = max_severity(p.severity_hint, FLOOR[p.category])            # SAFETY/HARASSMENT/INJURY >= HIGH
    row = IssueReport(reporter_id=s.user_id, class_id=p.class_id, trainer_id=await trainer_of(db, p.class_id),
                      category=p.category, severity=severity, user_words=p.user_words, ai_summary=p.neutral_summary)
    db.add(row); await db.flush()
    key = "issue.urgent" if severity in ("HIGH", "URGENT") else "issue.created"
    await enqueue(db, user_id=None, routing_key=key, template="ISSUE_ADMIN_ALERT", params={"issue_id": str(row.id)},
                  dedupe_key=f"issue:{row.id}")
    await enqueue(db, user_id=s.user_id, routing_key="email.issue", template="ISSUE_RECEIVED", params={}, dedupe_key=f"issue-ack:{row.id}")
    return {"ok": True, "issue_id": str(row.id), "severity": severity}

async def exec_decide_trainer_request(db, s, action):
    p = DecidePayload.model_validate(action.payload)                       # request_id, decision, reason
    req = await get_role_request(db, p.request_id, for_update=True)
    if not req or req.requested_role != "TRAINER" or req.status != "PENDING":   # admin requests never reach here
        return {"ok": False, "error": "REQUEST_NOT_PENDING"}
    req.decided_by, req.decided_at, req.reason = s.user_id, utcnow(), p.reason
    if p.decision == "APPROVE":
        req.status = "APPROVED"; await db.flush()
        await db.execute(text("UPDATE users SET role='TRAINER', account_status='ACTIVE' WHERE id=:u"), {"u": req.user_id})  # trigger satisfied
        await ensure_trainer_profile(db, req)
    elif p.decision == "REJECT":
        req.status = "REJECTED"
        await db.execute(text("UPDATE users SET account_status='REJECTED' WHERE id=:u"), {"u": req.user_id})
    else:
        req.info_requested = p.reason                                        # ASK_INFO keeps the request PENDING
    await enqueue(db, user_id=req.user_id, routing_key="email.trainer_decision", template="TRAINER_DECISION",
                  params={"decision": p.decision, "reason": p.reason}, dedupe_key=f"trainer-decision:{req.id}:{p.decision}")
    return {"ok": True, "decision": p.decision}

HANDLERS = {"BOOK_CLASS": exec_book, "CHANGE_PLAN": exec_change_plan, "SEND_BOOKING_EMAIL": exec_send_booking_email,
            "SUBMIT_ISSUE_REPORT": exec_issue_report, "ADMIN_DECIDE_TRAINER_REQUEST": exec_decide_trainer_request,
            # ... CANCEL_BOOKING, JOIN_WAITLIST, RENEW_PLAN, SAVE_NUTRITION_PLAN, CREATE_CLASS, CREATE_CLASS_SERIES,
            # UPDATE_CLASS_RESTRICTIONS, CANCEL_CLASS, SET_AVAILABILITY, SET_TIME_OFF, ADMIN_* follow the same shape
            }
ADMIN_ONLY = {"ADMIN_VERIFY_TRAINER", "ADMIN_DECIDE_TRAINER_REQUEST", "ADMIN_BROADCAST", "ADMIN_MESSAGE_USER",
              "ADMIN_GRANT_MEMBERSHIP", "ADMIN_INVITE_STAFF", "ADMIN_UPDATE_ISSUE"}
# Note: no handler and no action type exists for approving an admin-role request.
```

Waitlist promotion on cancellation (same transaction as the cancel): lock the class, decrement `booked_count`, pick the oldest `WAITLISTED` booking by `waitlist_seq` with `FOR UPDATE SKIP LOCKED`, re-check that member's entitlement and conflicts (skip ineligible members), promote, increment `booked_count`, enqueue `WAITLIST_PROMOTED`.

---

### 8.10 Bundle builder and bundle executor

```python
# app/orchestrator/bundle.py
async def build_bundle(db, ctx, plan, outputs) -> dict | None:
    steps = []
    for intent in plan["intents"]:                                         # already in topological order
        env = outputs.get(intent["id"])
        if env and env.status == "NEEDS_CONFIRMATION" and env.confirmation.action_id:
            steps.append((intent, env))
    if not steps:
        return None
    if len(steps) > settings_int(db, "bundle_max_steps"):
        raise PlanTooLarge()
    actions = {a.id: a for a in await load_actions(db, [e.confirmation.action_id for _, e in steps])}
    for _, env in steps:                                                    # verify ownership, state and expiry
        a = actions.get(UUID(env.confirmation.action_id))
        assert a and str(a.user_id) == ctx.session.user_id and a.status == "PENDING" and a.expires_at > utcnow()
    if len(steps) == 1:
        a = actions[UUID(steps[0][1].confirmation.action_id)]
        return {"action_id": str(a.id), "summary": a.summary, "expires_at": a.expires_at.isoformat()}
    step_no = {intent["id"]: i + 1 for i, (intent, _) in enumerate(steps)}
    bundle = ActionBundle(user_id=ctx.session.user_id, run_id=ctx.run_id, summary=headline(steps),
                          expires_at=min(actions[UUID(e.confirmation.action_id)].expires_at for _, e in steps))
    db.add(bundle); await db.flush()
    cards = []
    for intent, env in steps:
        a = actions[UUID(env.confirmation.action_id)]
        deps = sorted(step_no[d] for d in intent["depends_on"] if d in step_no)   # only dependencies that are write steps
        a.bundle_id, a.step_no, a.depends_on = bundle.id, step_no[intent["id"]], deps
        cards.append({"step_no": a.step_no, "type": a.type, "summary": a.summary, "depends_on": deps})
    questions = [{"agent": i["agent"], "text": e.user_message}
                 for i, e in ((i, outputs.get(i["id"])) for i in plan["intents"]) if e and e.status == "NEEDS_INPUT"]
    return {"bundle_id": str(bundle.id), "headline": bundle.summary, "expires_at": bundle.expires_at.isoformat(),
            "steps": cards, "questions": questions}
```

```python
# app/executor/bundles.py   POST /api/bundles/{bundle_id}/confirm   (no LLM)
@router.post("/api/bundles/{bundle_id}/confirm")
async def confirm_bundle(bundle_id: UUID, s: SessionContext = Depends(get_session), db=Depends(get_db)):
    async with db.begin():                                                 # lock the bundle row only, to serialize double taps
        await set_rls(db, s.user_id, s.role)
        bundle = (await db.execute(select(ActionBundle).where(ActionBundle.id == bundle_id).with_for_update())).scalar_one_or_none()
        if not bundle or str(bundle.user_id) != s.user_id:
            raise HTTPException(404)
        if bundle.status != "PENDING":
            return await stored_results(db, bundle)                          # idempotent replay; for AWAITING_PAYMENT it returns the open checkout
        if bundle.expires_at < utcnow():
            bundle.status = "EXPIRED"
            raise HTTPException(409, "ACTION_EXPIRED")
        bundle.status = "CONFIRMING"                                         # transient guard (set via a short commit in real code)
    return await run_bundle_steps(db, s, bundle_id)

async def run_bundle_steps(db, s, bundle_id):
    """Runs or RESUMES a bundle in step order. Steps already finished are not repeated."""
    steps = await load_steps(db, bundle_id)                                  # ordered by step_no
    done = {st.step_no: st.status for st in steps if st.status in ("EXECUTED", "FAILED", "SKIPPED")}
    for st in steps:
        if st.step_no in done:
            continue
        if any(done.get(d) != "EXECUTED" for d in st.depends_on):
            await mark(db, st.id, "SKIPPED", {"ok": False, "error": "DEPENDENCY_FAILED"})
            done[st.step_no] = "SKIPPED"; continue
        async with db.begin():                                               # one transaction per step
            await set_rls(db, s.user_id, s.role)
            action = await lock_action(db, st.id)
            result = await run_action(db, s, action)                         # re-validates everything inside
        if result.get("awaiting"):                                           # pause: finalize_paid / finalize_unpaid will resume
            await set_bundle_status(db, bundle_id, "AWAITING_PAYMENT")
            return {"status": "AWAITING_PAYMENT", "payment": result["awaiting"], "steps": await step_results(db, bundle_id)}
        done[st.step_no] = "EXECUTED" if result["ok"] else "FAILED"
    statuses = set(done.values())
    final = "EXECUTED" if statuses == {"EXECUTED"} else "FAILED" if "EXECUTED" not in statuses else "PARTIAL"
    await finish_bundle(db, bundle_id, final)
    return {"status": final, "steps": await step_results(db, bundle_id)}

async def resume_bundle(db, bundle_id, s):
    await set_bundle_status(db, bundle_id, "CONFIRMING")
    return await run_bundle_steps(db, s, bundle_id)

async def set_bundle_status(db, bundle_id, status):
    await db.execute(update(ActionBundle).where(ActionBundle.id == bundle_id).values(status=status))
```

---

### 6.8 Pending actions and bundles (the confirmation boundary)

```sql
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
```
