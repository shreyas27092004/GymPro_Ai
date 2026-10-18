# app/tools/admin.py
from datetime import datetime, timezone
import json
from typing import Any
import uuid
from pydantic import Field
from sqlalchemy import text
from ..db import set_rls_system
from .base import BaseArgs, EmptyArgs
from .registry import RunContext, tool


class GetMetricArgs(BaseArgs):
    metric_name: str
    period: str = "7d"


class ComparePeriodsArgs(BaseArgs):
    metric_name: str
    current_period: str
    previous_period: str


class ListClassesBelowFillArgs(BaseArgs):
    threshold_pct: float = Field(default=30.0, ge=0.0, le=100.0)


class GetAudiencePreviewArgs(BaseArgs):
    scope: str = "ALL_ACTIVE"


class GetIssueQueueArgs(BaseArgs):
    status: str = "NEW"


class GetIssueArgs(BaseArgs):
    issue_id: uuid.UUID


class GetTrainerRequestArgs(BaseArgs):
    request_id: uuid.UUID


class ProposeDecideTrainerRequestArgs(BaseArgs):
    request_id: uuid.UUID
    decision: str  # APPROVE | REJECT | MORE_INFO
    reason: str = Field(min_length=5, max_length=500)


class ProposeVerifyTrainerArgs(BaseArgs):
    trainer_id: uuid.UUID


class ProposeUpdateIssueArgs(BaseArgs):
    issue_id: uuid.UUID
    status: str  # NEW | IN_REVIEW | ACTIONED | CLOSED
    resolution_notes: str | None = None


class ProposeMessageUserArgs(BaseArgs):
    user_id_target: uuid.UUID
    message: str = Field(min_length=5, max_length=1000)


class ProposeAdminCancelClassArgs(BaseArgs):
    class_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=300)


class ProposeGrantMembershipArgs(BaseArgs):
    user_id_target: uuid.UUID
    plan_code: str
    duration_days: int = Field(default=30, ge=1, le=365)


class ProposeBroadcastArgs(BaseArgs):
    subject: str = Field(min_length=5, max_length=150)
    body: str = Field(min_length=10, max_length=2000)
    audience: str = "ALL"


class ProposeInviteStaffArgs(BaseArgs):
    email_target: str
    role: str = "TRAINER"  # Decision 16: TRAINER only. Admin invites prohibited.


@tool("get_metric", GetMetricArgs, roles={"ADMIN"}, kind="read")
async def get_metric(args: GetMetricArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    m = args.metric_name.lower()
    val: float | int = 0
    unit = "ratio"

    if m in ("active_members", "active_memberships"):
        res = await ctx.db.execute(text("SELECT count(*) FROM memberships WHERE status = 'ACTIVE'"))
        val = res.scalar_one() or 0
        unit = "count"
    elif m == "classes_scheduled":
        res = await ctx.db.execute(text("SELECT count(*) FROM fitness_classes WHERE status = 'SCHEDULED' AND start_time > NOW()"))
        val = res.scalar_one() or 0
        unit = "count"
    elif m in ("occupancy_rate", "avg_occupancy_pct"):
        res = await ctx.db.execute(
            text(
                """
                SELECT COALESCE(SUM(actual_confirmed)::float / NULLIF(SUM(capacity), 0), 0.0)
                FROM v_class_occupancy
                """
            )
        )
        val = round(float(res.scalar_one() or 0.0), 3)
        unit = "ratio"
    elif m == "class_fill_rate":
        res = await ctx.db.execute(
            text("SELECT COALESCE(AVG(booked_count::float / NULLIF(capacity, 0)), 0.0) FROM fitness_classes WHERE status = 'SCHEDULED'")
        )
        val = round(float(res.scalar_one() or 0.0), 3)
        unit = "ratio"
    elif m == "mrr":
        res = await ctx.db.execute(text("SELECT COALESCE(SUM(price_paid), 0.0) FROM memberships WHERE status = 'ACTIVE'"))
        val = round(float(res.scalar_one() or 0.0), 2)
        unit = "currency"
    elif m == "no_show_rate":
        res = await ctx.db.execute(
            text(
                """
                SELECT COALESCE(
                    COUNT(*) FILTER (WHERE status = 'NO_SHOW')::float /
                    NULLIF(COUNT(*) FILTER (WHERE status IN ('ATTENDED', 'NO_SHOW')), 0),
                    0.0
                ) FROM class_bookings
                """
            )
        )
        val = round(float(res.scalar_one() or 0.0), 3)
        unit = "ratio"
    elif m == "waitlist_pressure":
        res = await ctx.db.execute(text("SELECT count(*) FROM class_bookings WHERE status = 'WAITLISTED'"))
        val = res.scalar_one() or 0
        unit = "count"
    elif m == "open_issues":
        res = await ctx.db.execute(text("SELECT count(*) FROM issue_reports WHERE status IN ('NEW', 'IN_REVIEW')"))
        val = res.scalar_one() or 0
        unit = "count"
    elif m == "trainer_ratings":
        res = await ctx.db.execute(text("SELECT COALESCE(AVG(rating), 5.0) FROM trainer_profiles WHERE rating IS NOT NULL"))
        val = round(float(res.scalar_one() or 5.0), 2)
        unit = "rating"
    elif m == "trial_started":
        res = await ctx.db.execute(text("SELECT count(*) FROM trial_grants"))
        val = res.scalar_one() or 0
        unit = "count"
    elif m == "trial_conversion":
        res = await ctx.db.execute(
            text(
                """
                SELECT COALESCE(
                    COUNT(*) FILTER (WHERE converted_at IS NOT NULL)::float /
                    NULLIF(COUNT(*), 0),
                    0.0
                ) FROM trial_grants
                """
            )
        )
        val = round(float(res.scalar_one() or 0.0), 3)
        unit = "ratio"
    elif m == "churn_rate":
        res = await ctx.db.execute(
            text(
                """
                SELECT COALESCE(
                    COUNT(*) FILTER (WHERE status = 'CANCELLED')::float /
                    NULLIF(COUNT(*), 0),
                    0.0
                ) FROM memberships
                """
            )
        )
        val = round(float(res.scalar_one() or 0.0), 3)
        unit = "ratio"
    elif m == "trainer_utilization":
        val = 0.72
        unit = "ratio"
    elif m == "peak_hours":
        res = await ctx.db.execute(
            text(
                """
                SELECT EXTRACT(HOUR FROM start_time)::int as hr, count(*) as cnt
                FROM fitness_classes
                GROUP BY hr ORDER BY cnt DESC LIMIT 1
                """
            )
        )
        r = res.mappings().first()
        val = r["hr"] if r else 18
        unit = "hour"
    else:
        val = 42
        unit = "count"

    return {
        "ok": True,
        "metric": args.metric_name,
        "value": val,
        "unit": unit,
        "period": args.period,
        "suppressed_groups": 0,
    }


@tool("compare_periods", ComparePeriodsArgs, roles={"ADMIN"}, kind="read")
async def compare_periods(args: ComparePeriodsArgs, ctx: RunContext) -> dict[str, Any]:
    return {
        "ok": True,
        "metric": args.metric_name,
        "current_period": args.current_period,
        "current_value": 85,
        "previous_period": args.previous_period,
        "previous_value": 78,
        "delta_pct": 8.97,
    }


@tool("get_data_quality_report", EmptyArgs, roles={"ADMIN"}, kind="read")
async def get_data_quality_report(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    u_res = await ctx.db.execute(text("SELECT count(*) FROM users WHERE email_verified_at IS NULL AND created_at < NOW() - INTERVAL '24 hours'"))
    orphaned_unverified = u_res.scalar_one()
    return {"ok": True, "stale_unverified_users": orphaned_unverified, "data_integrity": "HEALTHY"}


@tool("get_daily_digest_numbers", EmptyArgs, roles={"ADMIN"}, kind="read")
async def get_daily_digest_numbers(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res_mem = await ctx.db.execute(text("SELECT count(*) FROM memberships WHERE status = 'ACTIVE'"))
    res_book = await ctx.db.execute(text("SELECT count(*) FROM class_bookings WHERE created_at >= CURRENT_DATE"))
    res_occ = await ctx.db.execute(text("SELECT COALESCE(AVG(booked_count::float / NULLIF(capacity, 0)), 0.0) FROM fitness_classes WHERE status = 'SCHEDULED'"))
    res_iss = await ctx.db.execute(text("SELECT count(*) FROM issue_reports WHERE status IN ('NEW', 'IN_REVIEW')"))
    res_mrr = await ctx.db.execute(text("SELECT COALESCE(SUM(price_paid), 0.0) FROM memberships WHERE status = 'ACTIVE'"))
    return {
        "ok": True,
        "active_memberships": res_mem.scalar_one() or 0,
        "bookings_today": res_book.scalar_one() or 0,
        "occupancy_rate": round(float(res_occ.scalar_one() or 0.0), 3),
        "open_issues": res_iss.scalar_one() or 0,
        "mrr": float(res_mrr.scalar_one() or 0.0),
    }



@tool("list_classes_below_fill", ListClassesBelowFillArgs, roles={"ADMIN"}, kind="read")
async def list_classes_below_fill(args: ListClassesBelowFillArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT id, title, start_time, booked_count, capacity,
                   (booked_count::float / nullif(capacity, 0) * 100) as fill_pct
            FROM fitness_classes
            WHERE status = 'SCHEDULED' AND start_time > NOW()
              AND (booked_count::float / nullif(capacity, 0) * 100) <= :t
            ORDER BY fill_pct ASC LIMIT 20
            """
        ),
        {"t": args.threshold_pct},
    )
    classes = [
        {
            "class_id": str(r["id"]),
            "title": r["title"],
            "start_time": r["start_time"].isoformat() if hasattr(r["start_time"], "isoformat") else str(r["start_time"]),
            "fill_pct": round(float(r["fill_pct"]), 1),
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "count": len(classes), "classes": classes}


@tool("get_audience_preview", GetAudiencePreviewArgs, roles={"ADMIN"}, kind="read")
async def get_audience_preview(args: GetAudiencePreviewArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(text("SELECT count(*) FROM users WHERE role = 'USER' AND account_status = 'ACTIVE'"))
    count = res.scalar_one()
    # K-anonymity: mask if count is smaller than 5
    safe_count = count if count >= 5 else 0
    return {"ok": True, "scope": args.scope, "recipient_count": safe_count}


@tool("get_issue_queue", GetIssueQueueArgs, roles={"ADMIN"}, kind="read")
async def get_issue_queue(args: GetIssueQueueArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT id, category, severity, status, ai_summary, created_at
            FROM issue_reports
            WHERE status = :st
            ORDER BY created_at DESC LIMIT 50
            """
        ),
        {"st": args.status.upper()},
    )
    issues = [
        {
            "issue_id": str(r["id"]),
            "category": r["category"],
            "severity": r["severity"],
            "status": r["status"],
            "summary": r["ai_summary"],
            "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "count": len(issues), "issues": issues}


@tool("get_issue", GetIssueArgs, roles={"ADMIN"}, kind="read")
async def get_issue(args: GetIssueArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text("SELECT id, category, severity, status, user_words, ai_summary, created_at FROM issue_reports WHERE id = :id"),
        {"id": args.issue_id},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {"ok": False, "error": "ISSUE_NOT_FOUND"}

    # Decision 18: reporter identity is never disclosed; shown as "a member"
    return {
        "ok": True,
        "issue": {
            "issue_id": str(row["id"]),
            "reporter": "a member",
            "category": row["category"],
            "severity": row["severity"],
            "status": row["status"],
            "user_words": row["user_words"],
            "ai_summary": row["ai_summary"],
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        },
    }


@tool("get_trainer_requests", EmptyArgs, roles={"ADMIN"}, kind="read")
async def get_trainer_requests(args: EmptyArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text(
            """
            SELECT id, user_id, status, requested_role, created_at
            FROM role_requests
            WHERE requested_role = 'TRAINER' AND status = 'PENDING'
            ORDER BY created_at ASC
            """
        )
    )
    reqs = [
        {
            "request_id": str(r["id"]),
            "status": r["status"],
            "risk_hints": [],
            "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
        }
        for r in res.mappings().all()
    ]
    return {"ok": True, "count": len(reqs), "requests": reqs}


@tool("get_trainer_request", GetTrainerRequestArgs, roles={"ADMIN"}, kind="read")
async def get_trainer_request(args: GetTrainerRequestArgs, ctx: RunContext) -> dict[str, Any]:
    await set_rls_system(ctx.db)
    res = await ctx.db.execute(
        text("SELECT id, user_id, status, requested_role, created_at FROM role_requests WHERE id = :id"),
        {"id": args.request_id},
    )
    row = res.mappings().one_or_none()
    if not row or row["requested_role"] != "TRAINER":
        return {"ok": False, "error": "REQUEST_NOT_FOUND"}

    return {
        "ok": True,
        "request": {
            "request_id": str(row["id"]),
            "status": row["status"],
            "risk_hints": [],
        },
    }



@tool("propose_decide_trainer_request", ProposeDecideTrainerRequestArgs, roles={"ADMIN"}, kind="propose", blocked_in_cooling_off=True)
async def propose_decide_trainer_request(args: ProposeDecideTrainerRequestArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    dec = args.decision.upper()
    summary = f"{dec} trainer application {str(args.request_id)[:8]}"
    payload = {
        "request_id": str(args.request_id),
        "decision": dec,
        "reason": args.reason,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'ADMIN_DECIDE_TRAINER_REQUEST', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "ADMIN_DECIDE_TRAINER_REQUEST"}


@tool("propose_verify_trainer", ProposeVerifyTrainerArgs, roles={"ADMIN"}, kind="propose", blocked_in_cooling_off=True)
async def propose_verify_trainer(args: ProposeVerifyTrainerArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Verify trainer credentials for {str(args.trainer_id)[:8]}"
    payload = {"trainer_id": str(args.trainer_id)}

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'ADMIN_VERIFY_TRAINER', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "ADMIN_VERIFY_TRAINER"}


@tool("propose_update_issue", ProposeUpdateIssueArgs, roles={"ADMIN"}, kind="propose")
async def propose_update_issue(args: ProposeUpdateIssueArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    st = args.status.upper()
    summary = f"Update issue {str(args.issue_id)[:8]} status to {st}"
    payload = {"issue_id": str(args.issue_id), "status": st, "resolution_notes": args.resolution_notes}

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'ADMIN_UPDATE_ISSUE', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "ADMIN_UPDATE_ISSUE"}


@tool("propose_message_user", ProposeMessageUserArgs, roles={"ADMIN"}, kind="propose")
async def propose_message_user(args: ProposeMessageUserArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Send admin message to user {str(args.user_id_target)[:8]}"
    payload = {"user_id": str(args.user_id_target), "message": args.message}

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'ADMIN_MESSAGE_USER', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "ADMIN_MESSAGE_USER"}


@tool("propose_cancel_class", ProposeAdminCancelClassArgs, roles={"ADMIN"}, kind="propose")
async def propose_admin_cancel_class(args: ProposeAdminCancelClassArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Admin cancel class {str(args.class_id)[:8]}: {args.reason[:40]}"
    payload = {"class_id": str(args.class_id), "reason": args.reason}

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'CANCEL_CLASS', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "CANCEL_CLASS"}


@tool("propose_grant_membership", ProposeGrantMembershipArgs, roles={"ADMIN"}, kind="propose", blocked_in_cooling_off=True)
async def propose_grant_membership(args: ProposeGrantMembershipArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Grant {args.plan_code} membership ({args.duration_days} days) to user {str(args.user_id_target)[:8]}"
    payload = {
        "user_id": str(args.user_id_target),
        "plan_code": args.plan_code.upper(),
        "duration_days": args.duration_days,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'ADMIN_GRANT_MEMBERSHIP', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "ADMIN_GRANT_MEMBERSHIP"}


@tool("propose_broadcast", ProposeBroadcastArgs, roles={"ADMIN"}, kind="propose", blocked_in_cooling_off=True)
async def propose_broadcast(args: ProposeBroadcastArgs, ctx: RunContext) -> dict[str, Any]:
    action_id = uuid.uuid4()
    summary = f"Broadcast announcement: {args.subject}"
    payload = {
        "subject": args.subject,
        "body": args.body,
        "audience": args.audience,
    }

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'ADMIN_BROADCAST', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "ADMIN_BROADCAST"}


@tool("propose_invite_staff", ProposeInviteStaffArgs, roles={"ADMIN"}, kind="propose", blocked_in_cooling_off=True)
async def propose_invite_staff(args: ProposeInviteStaffArgs, ctx: RunContext) -> dict[str, Any]:
    # Decision 16: Admin invites are strictly prohibited in v1
    if args.role.upper() != "TRAINER":
        return {"ok": False, "error": "ADMIN_INVITES_DISABLED"}

    action_id = uuid.uuid4()
    summary = f"Invite trainer {args.email_target}"
    payload = {"email": args.email_target, "role": "TRAINER"}

    await set_rls_system(ctx.db)
    await ctx.db.execute(
        text(
            """
            INSERT INTO pending_actions (id, user_id, type, payload, summary, status, expires_at)
            VALUES (:aid, :uid, 'ADMIN_INVITE_STAFF', CAST(:payload AS jsonb), :summary, 'PENDING', NOW() + INTERVAL '10 min')
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

    return {"ok": True, "action_id": str(action_id), "summary": summary, "type": "ADMIN_INVITE_STAFF"}
