# app/tools/registry.py
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Type
import uuid
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext


AGENT_TOOLS: dict[str, set[str]] = {
    "SCHEDULE": {
        "search_classes",
        "match_class_name",
        "get_my_bookings",
        "check_conflicts",
        "get_membership_entitlements",
        "check_class_rules",
        "propose_booking",
        "propose_cancellation",
        "propose_waitlist",
    },
    "MEMBERSHIP": {
        "list_plans",
        "get_highest_plan",
        "get_my_membership",
        "get_trial_status",
        "price_diff",
        "get_usage_summary",
        "propose_plan_change",
        "propose_renewal",
    },
    "FITNESS": {
        "get_my_intake",
        "search_exercise_kb",
        "get_class_catalog_summary",
        "calc_progression",
    },
    "WELLNESS": {
        "get_my_health_profile",
        "calc_energy",
        "calc_bmi",
        "calc_hydration",
        "get_injury_protocol",
        "get_crisis_resources",
    },
    "NUTRITION": {
        "get_my_nutrition_inputs",
        "calc_energy",
        "compute_macros",
        "search_nutrition_kb",
        "find_foods",
        "propose_save_plan",
    },
    "TRAINER_INFO": {
        "search_trainers",
        "get_trainer_profile",
        "get_trainer_review_summary",
        "get_trainer_availability",
    },
    "SUPPORT": {
        "get_todays_classes_for_me",
        "get_support_guidance",
        "propose_issue_report",
    },
    "COMMS": {
        "list_templates",
        "get_template",
        "get_booking_for_email",
        "get_weekly_summary_numbers",
        "get_notification_prefs",
        "propose_send_email",
    },
    "TRAINER_OPS": {
        "get_my_availability",
        "get_my_classes",
        "get_class_roster",
        "get_feedback_summary",
        "preview_series",
        "propose_create_class",
        "propose_create_series",
        "propose_update_restrictions",
        "propose_cancel_class",
        "propose_set_availability",
        "propose_set_time_off",
    },
    "ADMIN_INSIGHTS": {
        "get_metric",
        "compare_periods",
        "get_data_quality_report",
        "get_daily_digest_numbers",
        "list_classes_below_fill",
        "get_audience_preview",
        "get_issue_queue",
        "get_issue",
        "get_trainer_requests",
        "get_trainer_request",
        "propose_decide_trainer_request",
        "propose_verify_trainer",
        "propose_update_issue",
        "propose_message_user",
        "propose_cancel_class",
        "propose_grant_membership",
        "propose_broadcast",
        "propose_invite_staff",
    },
}


@dataclass(frozen=True)
class Tool:
    name: str
    args_model: Type[BaseModel]
    fn: Callable[..., Awaitable[dict[str, Any]]]
    roles: frozenset[str]             # who may call it: USER, TRAINER, ADMIN, SYSTEM
    kind: str                         # "read" | "calc" | "propose"
    needs_health_consent: bool = False
    blocked_in_cooling_off: bool = False


@dataclass
class RunContext:
    session: SessionContext
    db: AsyncSession
    allowed_tools: set[str] = field(default_factory=set)
    handoff: dict[str, Any] = field(default_factory=dict)
    agent_handoffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    tokens_used: int = 0
    now_iso: str | None = None
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def handoff_projected_plan(self) -> str | None:
        """Returns projected plan code if validated during prior bundle steps."""
        if "projected_state" in self.handoff and isinstance(self.handoff["projected_state"], dict):
            return self.handoff["projected_state"].get("plan_after")
        return self.handoff.get("projected_plan")

    def set_handoff(self, agent: str, handoff: dict[str, Any]) -> None:
        self.handoff = handoff or {}
        self.agent_handoffs[agent] = handoff or {}

    def allowed_tools_for(self, agent: str) -> set[str]:
        base = AGENT_TOOLS.get(agent.upper(), set())
        if self.allowed_tools:
            return base & self.allowed_tools
        return base

    def meter(self, usage: Any) -> None:
        if not usage:
            return
        total = getattr(usage, "total_tokens", 0) or 0
        self.tokens_used += total
        from ..settings import settings
        if self.tokens_used > settings.run_token_budget:
            raise RuntimeError(f"Token budget exceeded: {self.tokens_used} > {settings.run_token_budget}")

    def post_validate(self, agent: str, env: Any) -> None:
        from ..agents.validators import validate_envelope
        validate_envelope(agent, env, self)


TOOLS: dict[str, Tool] = {}


def tool(
    name: str,
    args_model: Type[BaseModel],
    roles: set[str] | list[str] | frozenset[str],
    kind: str = "read",
    needs_health_consent: bool = False,
    blocked_in_cooling_off: bool = False,
):
    """Decorator to register a tool in the catalog with declarative authorization."""
    if kind not in ("read", "calc", "propose"):
        raise ValueError(f"Invalid tool kind: '{kind}'. Must be 'read', 'calc', or 'propose'.")

    def decorator(fn: Callable[..., Awaitable[dict[str, Any]]]):
        TOOLS[name] = Tool(
            name=name,
            args_model=args_model,
            fn=fn,
            roles=frozenset(roles),
            kind=kind,
            needs_health_consent=needs_health_consent,
            blocked_in_cooling_off=blocked_in_cooling_off,
        )
        return fn

    return decorator


def openai_tool_specs(allowed_tool_names: set[str] | list[str] | None = None) -> list[dict[str, Any]]:
    specs = []
    names = allowed_tool_names if allowed_tool_names is not None else list(TOOLS.keys())
    for name in sorted(names):
        t = TOOLS.get(name)
        if not t:
            continue
        schema = t.args_model.model_json_schema()
        desc = (t.fn.__doc__ or f"Execute tool {name}").strip().split("\n")[0]
        specs.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": schema,
            },
        })
    return specs


async def dispatch(name: str, raw_args: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """
    Dispatches tool execution with registry-level authorization:
    1. Tool must exist and be in agent's allowlist (ctx.allowed_tools)
    2. Caller role must be in tool.roles
    3. Health consent must be granted if required
    4. Cooling-off restrictions must be respected
    5. Arguments must pass strict Pydantic model validation (extra='forbid')
    """
    t = TOOLS.get(name)
    if not t or (ctx.allowed_tools and name not in ctx.allowed_tools):
        return {"ok": False, "error": "TOOL_NOT_ALLOWED"}

    if ctx.session.role not in t.roles:
        return {"ok": False, "error": "FORBIDDEN"}

    if t.needs_health_consent and not ctx.session.health_consent:
        return {"ok": False, "error": "CONSENT_REQUIRED"}

    if t.blocked_in_cooling_off and ctx.session.cooling_off_active:
        return {"ok": False, "error": "COOLING_OFF_ACTIVE"}

    try:
        args = t.args_model.model_validate(raw_args or {})
    except Exception as e:
        return {"ok": False, "error": "BAD_ARGS", "detail": str(e)[:300]}

    return await t.fn(args, ctx)
