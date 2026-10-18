# app/tools/membership.py
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from ..entitlements.membership import price_diff as calc_price_diff
from ..entitlements.trial import get_active_trial
from .base import BaseArgs, EmptyArgs
from .registry import RunContext, tool


class PriceDiffArgs(BaseArgs):
    to_plan: str
    cycle: str = "MONTHLY"


class ProposePlanChangeArgs(BaseArgs):
    to_plan: str
    cycle: str = "MONTHLY"
    confirmed_total: float = Field(ge=0)


class ProposeRenewalArgs(BaseArgs):
    cycle: str = "MONTHLY"


@tool("list_plans", EmptyArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def list_plans(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text("SELECT code, name, description, price_monthly, price_annual, perks, sort_order FROM membership_plans WHERE is_active = true ORDER BY sort_order ASC")
    )
    plans = [
        {
            "code": r["code"],
            "name": r["name"],
            "description": r["description"],
            "price_monthly": float(r["price_monthly"]),
            "price_annual": float(r["price_annual"]),
            "perks": r["perks"],
            "sort_order": r["sort_order"],
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "plans": plans}


@tool("get_highest_plan", EmptyArgs, roles={"USER", "TRAINER", "ADMIN"}, kind="read")
async def get_highest_plan(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text("SELECT code, name, price_monthly, price_annual, perks FROM membership_plans WHERE is_active = true ORDER BY sort_order DESC LIMIT 1")
    )
    row = res.mappings().one_or_none()
    if not row:
        return {"ok": False, "error": "NO_PLANS_AVAILABLE"}
    return {
        "ok": True,
        "plan": {
            "code": row["code"],
            "name": row["name"],
            "price_monthly": float(row["price_monthly"]),
            "price_annual": float(row["price_annual"]),
            "perks": row["perks"],
        },
    }


@tool("get_my_membership", EmptyArgs, roles={"USER"}, kind="read")
async def get_my_membership(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT m.id, m.plan_code, m.status, m.billing_cycle, m.start_date, m.end_date, p.name, p.perks
            FROM memberships m
            JOIN membership_plans p ON m.plan_code = p.code
            WHERE m.user_id = :uid AND m.status = 'ACTIVE'
            """
        ),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {"ok": True, "has_membership": False, "membership": None}
    return {
        "ok": True,
        "has_membership": True,
        "membership": {
            "id": str(row["id"]),
            "plan_code": row["plan_code"],
            "plan_name": row["name"],
            "status": row["status"],
            "billing_cycle": row["billing_cycle"],
            "start_date": str(row["start_date"]),
            "end_date": str(row["end_date"]),
            "perks": row["perks"],
        },
    }


@tool("get_trial_status", EmptyArgs, roles={"USER"}, kind="read")
async def get_trial_status(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    trial = await get_active_trial(ctx.db, uuid.UUID(ctx.session.user_id))
    if not trial:
        return {"ok": True, "has_active_trial": False, "trial": None}
    return {
        "ok": True,
        "has_active_trial": True,
        "trial": {
            "classes_total": trial["classes_total"],
            "classes_used": trial["classes_used"],
            "remaining": trial["classes_remaining"],
            "expires_at": trial["expires_at"].isoformat() if hasattr(trial["expires_at"], "isoformat") else str(trial["expires_at"]),
        },
    }


@tool("get_usage_summary", EmptyArgs, roles={"USER"}, kind="read")
async def get_usage_summary(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    m_res = await ctx.db.execute(
        text("SELECT plan_code, start_date, end_date FROM memberships WHERE user_id = :uid AND status = 'ACTIVE'"),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    m = m_res.mappings().one_or_none()
    if not m:
        return {"ok": True, "classes_used_this_cycle": 0, "cap": None}

    u_res = await ctx.db.execute(
        text(
            """
            SELECT count(*) FROM class_bookings
            WHERE user_id = :uid AND status != 'CANCELLED'
              AND created_at >= :st AND created_at < :et
            """
        ),
        {"uid": uuid.UUID(ctx.session.user_id), "st": m["start_date"], "et": m["end_date"]},
    )
    used = u_res.scalar_one()

    p_res = await ctx.db.execute(
        text("SELECT perks FROM membership_plans WHERE code = :p"),
        {"p": m["plan_code"]},
    )
    perks = p_res.scalar_one_or_none() or {}
    cap = perks.get("group_classes_per_month")

    return {
        "ok": True,
        "plan_code": m["plan_code"],
        "classes_used_this_cycle": used,
        "cap": cap,
        "unlimited": cap is None,
    }


@tool("price_diff", PriceDiffArgs, roles={"USER"}, kind="calc")
async def price_diff_tool(args: PriceDiffArgs, ctx: RunContext) -> dict[str, Any]:
    try:
        quote = await calc_price_diff(ctx.db, uuid.UUID(ctx.session.user_id), args.to_plan, args.cycle)
        return {
            "ok": True,
            "from_plan": quote.from_plan,
            "to_plan": quote.to_plan,
            "cycle": quote.cycle,
            "delta_per_cycle": float(quote.delta_per_cycle),
            "prorated_today": float(quote.prorated_today),
            "next_billing_date": str(quote.next_billing_date),
            "currency": quote.currency,
        }
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@tool("propose_plan_change", ProposePlanChangeArgs, roles={"USER"}, kind="propose")
async def propose_plan_change(args: ProposePlanChangeArgs, ctx: RunContext) -> dict[str, Any]:
    try:
        quote = await calc_price_diff(ctx.db, uuid.UUID(ctx.session.user_id), args.to_plan, args.cycle)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    # Ensure price hasn't drifted
    if abs(quote.prorated_today - Decimal(str(args.confirmed_total))) > Decimal("0.01"):
        return {"ok": False, "error": "PRICE_CHANGED", "new_total": float(quote.prorated_today)}

    action_id = uuid.uuid4()
    summary = f"Upgrade membership to {args.to_plan} ({args.cycle}) for INR {args.confirmed_total:.2f}"
    payload = {
        "to_plan": args.to_plan,
        "cycle": args.cycle,
        "confirmed_total": float(args.confirmed_total),
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'CHANGE_PLAN', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
            """
        ),
        {
            "aid": action_id,
            "uid": uuid.UUID(ctx.session.user_id),
            "payload": json.dumps(payload),
            "summary": summary,
        },
    )
    await ctx.db.commit()

    return {
        "ok": True,
        "action_id": str(action_id),
        "summary": summary,
        "type": "CHANGE_PLAN",
    }


@tool("propose_renewal", ProposeRenewalArgs, roles={"USER"}, kind="propose")
async def propose_renewal(args: ProposeRenewalArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    m_res = await ctx.db.execute(
        text("SELECT plan_code FROM memberships WHERE user_id = :uid AND status = 'ACTIVE'"),
        {"uid": uuid.UUID(ctx.session.user_id)},
    )
    m = m_res.mappings().one_or_none()
    if not m:
        return {"ok": False, "error": "NO_ACTIVE_MEMBERSHIP"}

    action_id = uuid.uuid4()
    summary = f"Renew membership for {m['plan_code']} ({args.cycle})"
    payload = {"plan_code": m["plan_code"], "cycle": args.cycle}

    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'RENEW_PLAN', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
            """
        ),
        {
            "aid": action_id,
            "uid": uuid.UUID(ctx.session.user_id),
            "payload": json.dumps(payload),
            "summary": summary,
        },
    )
    await ctx.db.commit()

    return {
        "ok": True,
        "action_id": str(action_id),
        "summary": summary,
        "type": "RENEW_PLAN",
    }
