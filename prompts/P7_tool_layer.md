# Phase P7: Tool layer

**Before you start:** read `prompts/00_CORE.md` (rules, locked decisions, architecture). Previous phases must already pass their gates.

## Task
Write a short plan and task list, then implement this phase completely, including its tests. Resolve ambiguities yourself and log each in `docs/DECISIONS.md`. Never weaken or skip a safety or security test.

## Deliverables
Pydantic schemas, tool registry with role and consent checks, all read, calc and propose tools, calculators (BMR, macros, hydration, `price_diff`, progression)

## Gate (must pass before you stop)
`pytest tests/tools -q`: **registry scan test** (no tool accepts `user_id` or a recipient, no write tool exists, every tool declares roles), consent gating, allergen fail-closed, calculator unit tests

## When the gate passes
Update `README.md` and `docs/PROGRESS.md`, commit once, and stop. Do not start Phase P8.

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

### 8.5 Schemas

```python
# app/agents/schemas.py
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Any

Status = Literal["OK","NEEDS_INPUT","NEEDS_CONFIRMATION","REFUSED","ESCALATE","ERROR"]
Flag = Literal["PROMPT_INJECTION","RED_FLAG_SYMPTOM","CRISIS","MINOR","PREGNANCY","ALLERGY_CONSTRAINT",
               "EATING_DISORDER_SIGNAL","MEDICAL_CONDITION","CROSS_USER_REQUEST","OUT_OF_SCOPE",
               "PRIVILEGE_ESCALATION","EMAIL_TARGET_REFUSED"]

class Confirmation(BaseModel):
    action_id: str | None = None
    summary: str | None = None
    expires_at: str | None = None

class Safety(BaseModel):
    flags: list[Flag] = []
    escalation: str | None = None

class Envelope(BaseModel):
    agent: str
    schema_version: Literal["1.0", "2.0", "3.0"]
    status: Status
    data: dict[str, Any]
    projected_effects: dict[str, Any] | None = None
    user_message: str = Field(max_length=700)
    missing_fields: list[str] = []
    confirmation: Confirmation = Confirmation()
    safety: Safety = Safety()
    citations: list[dict] = []
    confidence: float = Field(ge=0, le=1)

    @field_validator("user_message")
    @classmethod
    def word_limit(cls, v):
        if len(v.split()) > 90:           # 80 in the prompt + tolerance
            raise ValueError("user_message too long")
        return v

class MacroSet(BaseModel):
    protein_g: int; carbs_g: int; fats_g: int

class NutritionData(BaseModel):
    daily_calories: int | None
    macros: MacroSet | None
    meals: list[dict] = []

class CommsData(BaseModel):
    template_id: str | None
    channel: str | None
    to_masked: str | None
    attach_calendar: bool = False
    requires_step: int | None = None

class SupportData(BaseModel):
    operation: Literal["COLLECT","PROPOSE_REPORT","REFUSE"]
    class_id: str | None = None
    category: str | None = None
    severity_hint: Literal["LOW","MEDIUM","HIGH","URGENT"] | None = None
    neutral_summary: str | None = Field(default=None, max_length=300)

DATA_MODELS = {"NUTRITION": NutritionData, "COMMS": CommsData, "SUPPORT": SupportData}   # one Pydantic model per agent
```

---

### 8.6 Tool registry

```python
# app/tools/registry.py
from dataclasses import dataclass
from typing import Callable, Awaitable, Type
from pydantic import BaseModel

@dataclass(frozen=True)
class Tool:
    name: str
    args_model: Type[BaseModel]
    fn: Callable[..., Awaitable[dict]]
    roles: frozenset[str]             # who may call it
    kind: str                         # "read" | "propose" | "calc"
    needs_health_consent: bool = False
    blocked_in_cooling_off: bool = False

TOOLS: dict[str, Tool] = {}

def tool(name, args_model, roles, kind="read", needs_health_consent=False, blocked_in_cooling_off=False):
    def deco(fn):
        TOOLS[name] = Tool(name, args_model, fn, frozenset(roles), kind, needs_health_consent, blocked_in_cooling_off)
        return fn
    return deco

async def dispatch(name: str, raw_args: dict, ctx: "RunContext") -> dict:
    t = TOOLS.get(name)
    if not t or name not in ctx.allowed_tools:                      # per-agent allowlist
        return {"ok": False, "error": "TOOL_NOT_ALLOWED"}
    if ctx.session.role not in t.roles:
        return {"ok": False, "error": "FORBIDDEN"}
    if t.needs_health_consent and not ctx.session.health_consent:
        return {"ok": False, "error": "CONSENT_REQUIRED"}
    if t.blocked_in_cooling_off and ctx.session.cooling_off_active:
        return {"ok": False, "error": "COOLING_OFF_ACTIVE"}
    try:
        args = t.args_model.model_validate(raw_args)                # extra="forbid": unknown fields rejected
    except Exception as e:
        return {"ok": False, "error": "BAD_ARGS", "detail": str(e)[:300]}
    # user_id is injected from the session; args models have NO user_id field for member-scoped tools
    # and NO recipient field for propose_send_email.
    return await t.fn(args, ctx)                                    # ctx.db already has SET LOCAL app.user_id / app.role
```

All argument models inherit from a base with `model_config = ConfigDict(extra="forbid")`. A test iterates over `TOOLS` and fails the build if any args model has a field named `user_id`, `email`, `to`, `recipient`, `role` or `password`.

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

---

### 7.3 Common output envelope (Pydantic / JSON Schema)

```json
{
  "agent": "SCHEDULE",
  "schema_version": "1.0",
  "status": "OK",
  "data": {},
  "projected_effects": null,
  "user_message": "string, max 80 words",
  "missing_fields": [],
  "confirmation": {
    "action_id": "uuid or null",
    "summary": "string or null",
    "expires_at": "ISO-8601 or null"
  },
  "safety": {
    "flags": [],
    "escalation": null
  },
  "citations": [{"source": "tool|kb", "ref": "string"}],
  "confidence": 0.92
}
```

`projected_effects` is non-null only when the agent's proposal changes state that later steps depend on. Example from MEMBERSHIP: `{"plan_after":"PLATINUM","effective":"on_confirm","entitlements_after":{"classes_remaining":null,"pt_remaining":5}}`.

`safety.flags` is a closed set: `PROMPT_INJECTION`, `RED_FLAG_SYMPTOM`, `CRISIS`, `MINOR`, `PREGNANCY`, `ALLERGY_CONSTRAINT`, `EATING_DISORDER_SIGNAL`, `MEDICAL_CONDITION`, `CROSS_USER_REQUEST`, `OUT_OF_SCOPE`, `PRIVILEGE_ESCALATION`, `EMAIL_TARGET_REFUSED`.
