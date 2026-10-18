# app/prompts.py
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from .db import set_rls_system
from .settings import settings


@dataclass
class Prompt:
    agent: str
    version: str
    text: str
    sha256: str
    tools: list[str]
    roles: list[str]
    model_min: str = "gpt-4o"
    owner: str = "system"


def get_prompts_dir() -> Path:
    # 1. backend/prompts
    d1 = Path(__file__).resolve().parent.parent / "prompts"
    if d1.exists() and (d1 / "base_policy.md").exists():
        return d1
    # 2. root prompts
    d2 = Path(__file__).resolve().parent.parent.parent / "prompts"
    if d2.exists() and (d2 / "base_policy.md").exists():
        return d2
    return d1


def parse_front_matter(content: str) -> tuple[dict[str, Any], str]:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            metadata = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            return metadata, body
    return {}, content.strip()


def render_template(template: str, variables: dict[str, Any]) -> str:
    res = template
    for k, v in variables.items():
        res = res.replace(f"{{{{{k}}}}}", str(v))
    return res


def load_prompt(agent: str, ctx: Any = None) -> Prompt:
    prompts_dir = get_prompts_dir()
    base_policy_file = prompts_dir / "base_policy.md"
    agent_file = prompts_dir / "agents" / f"{agent.lower()}.md"
    supervisor_file = prompts_dir / f"{agent.lower()}.md"

    if agent_file.exists():
        if not base_policy_file.exists():
            raise FileNotFoundError(f"Base policy not found at {base_policy_file}")
        _, base_body = parse_front_matter(base_policy_file.read_text(encoding="utf-8"))
        agent_meta, agent_body = parse_front_matter(agent_file.read_text(encoding="utf-8"))
        has_base = True
    elif supervisor_file.exists():
        base_body = ""
        agent_meta, agent_body = parse_front_matter(supervisor_file.read_text(encoding="utf-8"))
        has_base = False
    else:
        raise FileNotFoundError(f"Prompt file not found for agent '{agent}' at {agent_file} or {supervisor_file}")

    # Runtime variables
    now_iso = getattr(ctx, "now_iso", None) if ctx else None
    if not now_iso:
        # Default frozen test clock if not provided
        now_iso = "2026-10-16T18:05:00+05:30"

    variables = {
        "now_iso": now_iso,
        "gym_timezone": settings.gym_timezone,
        "buffer_minutes": settings.booking_buffer_minutes,
        "late_cancel_hours": settings.late_cancel_hours,
        "pending_ttl_min": settings.pending_action_ttl_min,
        "trial_classes": settings.trial_classes,
        "trial_days": settings.trial_days,
        "bundle_max_steps": settings.bundle_max_steps,
    }

    rendered_base = render_template(base_body, variables)
    rendered_agent = render_template(agent_body, variables)

    # Allowed tools appendix if ctx provides allowed_tools_for
    tools_section = ""
    if ctx and hasattr(ctx, "allowed_tools_for"):
        allowed = ctx.allowed_tools_for(agent)
        if allowed:
            tools_section = "\n\n[AVAILABLE_TOOLS_FOR_RUN]\n" + "\n".join(f"- {t}" for t in sorted(allowed))

    full_text = f"{rendered_base}\n\n{rendered_agent}{tools_section}".strip()
    sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

    return Prompt(
        agent=agent_meta.get("agent", agent.upper()),
        version=str(agent_meta.get("version", "1.0.0")),
        text=full_text,
        sha256=sha256,
        tools=agent_meta.get("tools", []),
        roles=agent_meta.get("roles", ["USER"]),
        model_min=agent_meta.get("model_min", "gpt-4o"),
        owner=agent_meta.get("owner", "system"),
    )


async def sync_prompt_versions(
    db: AsyncSession,
    agent: str,
    version: str,
    sha256: str,
    eval_score: float | None = None,
) -> None:
    await set_rls_system(db)
    await db.execute(
        text(
            """
            INSERT INTO prompt_versions (agent, version, sha256, eval_score, released_at)
            VALUES (:agent, :version, :sha256, :eval_score, NOW())
            ON CONFLICT (agent, version)
            DO UPDATE SET sha256 = EXCLUDED.sha256,
                          eval_score = EXCLUDED.eval_score,
                          released_at = NOW()
            """
        ),
        {
            "agent": agent.upper(),
            "version": version,
            "sha256": sha256,
            "eval_score": eval_score,
        },
    )
    await db.commit()
