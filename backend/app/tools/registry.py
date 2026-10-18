# app/tools/registry.py
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Type
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext


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

    def handoff_projected_plan(self) -> str | None:
        """Returns projected plan code if validated during prior bundle steps."""
        return self.handoff.get("projected_plan")


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
