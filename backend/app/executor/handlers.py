# app/executor/handlers.py
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from typing import Any
import uuid
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext
from ..db import set_rls_system
from ..entitlements.membership import price_diff
from ..entitlements.resolver import entitlements
from ..messaging.outbox import enqueue
from .payments_adapter import begin_payment
from .schemas import (
    BookPayload,
    CancelBookingPayload,
    ChangePlanPayload,
    DecidePayload,
    IssuePayload,
    JoinWaitlistPayload,
    SendEmailPayload,
)


ADMIN_ONLY = {
    "ADMIN_VERIFY_TRAINER",
    "ADMIN_DECIDE_TRAINER_REQUEST",
    "ADMIN_BROADCAST",
    "ADMIN_MESSAGE_USER",
    "ADMIN_GRANT_MEMBERSHIP",
    "ADMIN_INVITE_STAFF",
    "ADMIN_UPDATE_ISSUE",
}


def mask_email(email: str) -> str:
    parts = email.split("@")
    if len(parts) != 2:
        return "***"
    name, domain = parts
    masked_name = name[0] + "***" if len(name) > 1 else "*"
    return f"{masked_name}@{domain}"


async def find_conflicts(db: AsyncSession, user_id: uuid.UUID, cls: dict[str, Any]) -> bool:
    """
    Checks if user has any active booking that overlaps with the target class schedule.
    """
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT 1 FROM class_bookings cb
            JOIN fitness_classes c ON c.id = cb.class_id
            WHERE cb.user_id = :uid
              AND cb.status = 'CONFIRMED'
              AND c.status = 'SCHEDULED'
              AND c.id != :cid
              AND (c.start_time < :end_time AND c.end_time > :start_time)
            LIMIT 1
            """
        ),
        {
            "uid": user_id,
            "cid": cls["id"],
            "start_time": cls["start_time"],
            "end_time": cls["end_time"],
        },
    )
    return res.first() is not None


async def class_rules(db: AsyncSession, s: SessionContext, cls: dict[str, Any]) -> tuple[bool, str | None]:
    """Evaluates age and injury contraindication rules."""
    if s.age_years is not None and s.age_years < cls.get("min_age", 16):
        return False, "AGE_RESTRICTION"

    contra = cls.get("contraindicated_for", []) or []
    if contra:
        await set_rls_system(db)
        p_res = await db.execute(
            text("SELECT injuries FROM member_profiles WHERE user_id = :uid"),
            {"uid": uuid.UUID(s.user_id)},
        )
        row = p_res.mappings().one_or_none()
        user_injuries = set(row["injuries"]) if row and row["injuries"] else set()
        if user_injuries.intersection(set(contra)):
            return False, "CONTRAINDICATED"

    return True, None


async def exec_book(db: AsyncSession, s: SessionContext, action: Any) -> dict[str, Any]:
    p = BookPayload.model_validate(action.payload)
    # Advisory lock on user ID to serialize concurrent booking attempts for this user
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:u, 0))"),
        {"u": s.user_id},
    )

    # Lock target class row
    cls_res = await db.execute(
        text(
            """
            SELECT id, title, capacity, booked_count, status, start_time, end_time,
                   min_age, min_level, contraindicated_for, trial_eligible, allowed_plans
            FROM fitness_classes
            WHERE id = :cid
            FOR UPDATE
            """
        ),
        {"cid": p.class_id},
    )
    raw_cls = cls_res.mappings().one_or_none()
    if not raw_cls:
        return {"ok": False, "error": "CLASS_UNAVAILABLE"}
    cls = dict(raw_cls)

    now = datetime.now(timezone.utc)
    cls_start = cls["start_time"]
    if cls_start.tzinfo is None:
        cls_start = cls_start.replace(tzinfo=timezone.utc)

    if cls["status"] != "SCHEDULED" or cls_start <= now:
        return {"ok": False, "error": "CLASS_UNAVAILABLE"}

    # Class rules check (age, injuries)
    ok_rule, rule_reason = await class_rules(db, s, cls)
    if not ok_rule:
        return {"ok": False, "error": "RULE_FAILED", "detail": rule_reason}

    # Check already booked this exact class
    await set_rls_system(db)
    existing_chk = await db.execute(
        text(
            """
            SELECT id FROM class_bookings
            WHERE user_id = :uid AND class_id = :cid AND status IN ('CONFIRMED', 'WAITLISTED')
            """
        ),
        {"uid": uuid.UUID(s.user_id), "cid": p.class_id},
    )
    if existing_chk.first():
        return {"ok": False, "error": "ALREADY_BOOKED"}

    # Conflicts check (overlapping class bookings)
    if await find_conflicts(db, uuid.UUID(s.user_id), cls):
        return {"ok": False, "error": "CONFLICT"}

    # Entitlement check (real state at execution time)
    ent = await entitlements(db, uuid.UUID(s.user_id), cls=cls)
    if not ent.can_book:
        return {"ok": False, "error": "NO_ENTITLEMENT", "detail": ent.reason}

    # Capacity check (row locked)
    if cls["booked_count"] >= cls["capacity"]:
        return {"ok": False, "error": "CLASS_FULL", "hint": "offer_waitlist"}

    booking_id = uuid.uuid4()
    try:
        await set_rls_system(db)
        await db.execute(
            text(
                """
                INSERT INTO class_bookings (
                    id, user_id, class_id, status, used_trial_grant, idempotency_key
                ) VALUES (
                    :id, :uid, :cid, 'CONFIRMED', :tg, :idem
                )
                """
            ),
            {
                "id": booking_id,
                "uid": uuid.UUID(s.user_id),
                "cid": cls["id"],
                "tg": uuid.UUID(ent.trial_grant_id) if ent.trial_grant_id else None,
                "idem": action.id,
            },
        )
        await db.execute(
            text("UPDATE fitness_classes SET booked_count = booked_count + 1 WHERE id = :cid"),
            {"cid": cls["id"]},
        )
        if ent.source == "TRIAL" and ent.trial_grant_id:
            await db.execute(
                text("UPDATE trial_grants SET classes_used = classes_used + 1 WHERE id = :g"),
                {"g": uuid.UUID(ent.trial_grant_id)},
            )
    except IntegrityError:
        return {"ok": False, "error": "ALREADY_BOOKED"}

    await enqueue(
        db,
        user_id=s.user_id,
        routing_key="email.booking",
        template="CLASS_CONFIRMED",
        params={"class_id": str(cls["id"]), "booking_id": str(booking_id)},
        dedupe_key=f"confirm:{booking_id}",
    )
    return {"ok": True, "booking_id": str(booking_id), "class_id": str(cls["id"])}


async def activate_plan(
    db: AsyncSession,
    s: SessionContext,
    p: ChangePlanPayload,
    quote: Any,
    payment_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Atomic membership upgrade swap (frees uq_one_active_membership)."""
    await set_rls_system(db)
    old_res = await db.execute(
        text(
            """
            SELECT id, plan_code, status, billing_cycle, price_paid, start_date, end_date
            FROM memberships
            WHERE user_id = :uid AND status = 'ACTIVE'
            FOR UPDATE
            """
        ),
        {"uid": uuid.UUID(s.user_id)},
    )
    old = old_res.mappings().one_or_none()
    old_plan = old["plan_code"] if old else None
    if old_plan != getattr(quote, "from_plan", None):
        return {"ok": False, "error": "CONFLICT"}

    new_id = uuid.uuid4()
    if old:
        await db.execute(
            text(
                """
                UPDATE memberships
                SET status = 'REPLACED',
                    end_date = CASE WHEN start_date >= CURRENT_DATE THEN start_date + INTERVAL '1 day' ELSE CURRENT_DATE END
                WHERE id = :oid
                """
            ),
            {"oid": old["id"]},
        )

    await db.execute(
        text(
            """
            INSERT INTO memberships (
                id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date
            ) VALUES (
                :id, :uid, :p, 'ACTIVE', :cycle, :paid, CURRENT_DATE, :end_date
            )
            """
        ),
        {
            "id": new_id,
            "uid": uuid.UUID(s.user_id),
            "p": p.to_plan,
            "cycle": p.cycle,
            "paid": quote.prorated_today,
            "end_date": quote.next_billing_date,
        },
    )

    if old:
        await db.execute(
            text("UPDATE memberships SET replaced_by = :nid WHERE id = :oid"),
            {"nid": new_id, "oid": old["id"]},
        )

    if payment_id:
        await db.execute(
            text("UPDATE payments SET membership_id = :nid WHERE id = :pid"),
            {"nid": new_id, "pid": payment_id},
        )

    await enqueue(
        db,
        user_id=s.user_id,
        routing_key="email.plan",
        template="PLAN_CHANGED",
        params={"plan": p.to_plan},
        dedupe_key=f"plan:{new_id}",
    )
    return {"ok": True, "membership_id": str(new_id), "plan": p.to_plan}


async def exec_change_plan(db: AsyncSession, s: SessionContext, action: Any) -> dict[str, Any]:
    p = ChangePlanPayload.model_validate(action.payload)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:u, 1))"),
        {"u": s.user_id},
    )

    # Check plan active
    plan_res = await db.execute(
        text("SELECT code, price_monthly, price_annual, is_active FROM membership_plans WHERE code = :p"),
        {"p": p.to_plan},
    )
    plan = plan_res.mappings().one_or_none()
    if not plan or not plan["is_active"]:
        return {"ok": False, "error": "PLAN_UNAVAILABLE"}

    # Re-calculate proration quote
    try:
        quote = await price_diff(db, uuid.UUID(s.user_id), p.to_plan, p.cycle)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    # PRICE_CHANGED verification
    if abs(quote.prorated_today - p.confirmed_total) > Decimal("0.01"):
        return {"ok": False, "error": "PRICE_CHANGED", "new_total": float(quote.prorated_today)}

    # Payment initiation
    pay = await begin_payment(db, s, action, quote)
    if pay.state == "AWAITING":
        return {"ok": None, "awaiting": pay.checkout}
    if pay.state != "PAID":
        return {"ok": False, "error": pay.error or "PAYMENT_FAILED"}

    return await activate_plan(db, s, p, quote, pay.id)


async def exec_cancel_booking(db: AsyncSession, s: SessionContext, action: Any) -> dict[str, Any]:
    p = CancelBookingPayload.model_validate(action.payload)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:u, 0))"),
        {"u": s.user_id},
    )

    await set_rls_system(db)
    b_res = await db.execute(
        text(
            """
            SELECT id, user_id, class_id, status, used_trial_grant, created_at
            FROM class_bookings
            WHERE id = :bid
            FOR UPDATE
            """
        ),
        {"bid": p.booking_id},
    )
    b = b_res.mappings().one_or_none()
    if not b or (str(b["user_id"]) != s.user_id and s.role != "ADMIN"):
        return {"ok": False, "error": "NOT_OWNER"}
    if b["status"] != "CONFIRMED":
        return {"ok": False, "error": "NOT_CONFIRMED"}

    cls_res = await db.execute(
        text("SELECT id, start_time, booked_count FROM fitness_classes WHERE id = :cid FOR UPDATE"),
        {"cid": b["class_id"]},
    )
    cls = cls_res.mappings().one_or_none()
    if not cls:
        return {"ok": False, "error": "CLASS_UNAVAILABLE"}

    now = datetime.now(timezone.utc)
    cls_start = cls["start_time"]
    if cls_start.tzinfo is None:
        cls_start = cls_start.replace(tzinfo=timezone.utc)

    # Late cancel rule (2 hours cutoff)
    is_late = (cls_start - now).total_seconds() < 2 * 3600

    await db.execute(
        text("UPDATE class_bookings SET status = 'CANCELLED', cancelled_at = NOW() WHERE id = :bid"),
        {"bid": b["id"]},
    )
    await db.execute(
        text("UPDATE fitness_classes SET booked_count = GREATEST(0, booked_count - 1) WHERE id = :cid"),
        {"cid": cls["id"]},
    )

    # Refund trial if applicable and not late
    if not is_late and b["used_trial_grant"]:
        await db.execute(
            text("UPDATE trial_grants SET classes_used = GREATEST(0, classes_used - 1) WHERE id = :g"),
            {"g": b["used_trial_grant"]},
        )

    # Waitlist promotion in same transaction
    wl_res = await db.execute(
        text(
            """
            SELECT id, user_id
            FROM class_bookings
            WHERE class_id = :cid AND status = 'WAITLISTED'
            ORDER BY waitlist_seq ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"cid": cls["id"]},
    )
    wl_booking = wl_res.mappings().one_or_none()
    if wl_booking:
        promoted_uid = wl_booking["user_id"]
        # Verify promoted user's entitlement and conflicts
        promoted_ent = await entitlements(db, promoted_uid, cls=cls)
        promoted_conflict = await find_conflicts(db, promoted_uid, cls)
        if promoted_ent.can_book and not promoted_conflict:
            await db.execute(
                text(
                    """
                    UPDATE class_bookings
                    SET status = 'CONFIRMED',
                        used_trial_grant = :tg
                    WHERE id = :wid
                    """
                ),
                {
                    "wid": wl_booking["id"],
                    "tg": uuid.UUID(promoted_ent.trial_grant_id) if promoted_ent.trial_grant_id else None,
                },
            )
            await db.execute(
                text("UPDATE fitness_classes SET booked_count = booked_count + 1 WHERE id = :cid"),
                {"cid": cls["id"]},
            )
            if promoted_ent.source == "TRIAL" and promoted_ent.trial_grant_id:
                await db.execute(
                    text("UPDATE trial_grants SET classes_used = classes_used + 1 WHERE id = :tg"),
                    {"tg": uuid.UUID(promoted_ent.trial_grant_id)},
                )
            await enqueue(
                db,
                user_id=promoted_uid,
                routing_key="email.booking",
                template="WAITLIST_PROMOTED",
                params={"class_id": str(cls["id"]), "booking_id": str(wl_booking["id"])},
                dedupe_key=f"promote:{wl_booking['id']}",
            )

    return {"ok": True, "cancelled": str(b["id"]), "refunded": not is_late}


async def exec_join_waitlist(db: AsyncSession, s: SessionContext, action: Any) -> dict[str, Any]:
    p = JoinWaitlistPayload.model_validate(action.payload)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:u, 0))"),
        {"u": s.user_id},
    )

    await set_rls_system(db)
    # Check active booking uniqueness
    chk = await db.execute(
        text(
            """
            SELECT id FROM class_bookings
            WHERE user_id = :uid AND class_id = :cid AND status IN ('CONFIRMED', 'WAITLISTED')
            """
        ),
        {"uid": uuid.UUID(s.user_id), "cid": p.class_id},
    )
    if chk.first():
        return {"ok": False, "error": "ALREADY_BOOKED"}

    cls_res = await db.execute(
        text("SELECT id, status, start_time FROM fitness_classes WHERE id = :cid"),
        {"cid": p.class_id},
    )
    cls = cls_res.mappings().one_or_none()
    if not cls or cls["status"] != "SCHEDULED":
        return {"ok": False, "error": "CLASS_UNAVAILABLE"}

    bid = uuid.uuid4()
    ins_res = await db.execute(
        text(
            """
            INSERT INTO class_bookings (id, user_id, class_id, status, idempotency_key)
            VALUES (:id, :uid, :cid, 'WAITLISTED', :idem)
            RETURNING waitlist_seq
            """
        ),
        {"id": bid, "uid": uuid.UUID(s.user_id), "cid": p.class_id, "idem": action.id},
    )
    seq = ins_res.scalar_one()

    await enqueue(
        db,
        user_id=s.user_id,
        routing_key="email.booking",
        template="WAITLIST_JOINED",
        params={"class_id": str(p.class_id), "position": seq},
        dedupe_key=f"waitlist:{bid}",
    )
    return {"ok": True, "booking_id": str(bid), "status": "WAITLISTED", "position": seq}


async def exec_send_booking_email(db: AsyncSession, s: SessionContext, action: Any) -> dict[str, Any]:
    p = SendEmailPayload.model_validate(action.payload)
    await set_rls_system(db)
    u_res = await db.execute(
        text("SELECT email FROM users WHERE id = :uid"),
        {"uid": uuid.UUID(s.user_id)},
    )
    urow = u_res.mappings().one_or_none()
    to_email = urow["email"] if urow else s.account_email

    params = dict(p.params)
    if p.requires_step is not None and getattr(action, "bundle_id", None):
        step_res = await db.execute(
            text(
                """
                SELECT result FROM pending_actions
                WHERE bundle_id = :bid AND step_no = :sno
                """
            ),
            {"bid": action.bundle_id, "sno": p.requires_step},
        )
        row = step_res.mappings().one_or_none()
        if row and row["result"] and isinstance(row["result"], dict):
            if "booking_id" in row["result"]:
                params["booking_id"] = row["result"]["booking_id"]

    await enqueue(
        db,
        user_id=s.user_id,
        routing_key="email.booking",
        template=p.template_id,
        params={**params, "attach_calendar": p.attach_calendar},
        dedupe_key=f"email:{action.id}",
    )
    return {"ok": True, "to_masked": mask_email(to_email)}


async def exec_issue_report(db: AsyncSession, s: SessionContext, action: Any) -> dict[str, Any]:
    p = IssuePayload.model_validate(action.payload)
    await set_rls_system(db)

    # Daily cap check
    rep_chk = await db.execute(
        text(
            """
            SELECT count(*) FROM issue_reports
            WHERE reporter_id = :uid AND created_at >= CURRENT_DATE
            """
        ),
        {"uid": uuid.UUID(s.user_id)},
    )
    if (rep_chk.scalar_one() or 0) >= 5:
        return {"ok": False, "error": "REPORT_LIMIT_REACHED"}

    # Class booking verification if class_id provided
    trainer_id = None
    if p.class_id:
        b_chk = await db.execute(
            text("SELECT 1 FROM class_bookings WHERE user_id = :uid AND class_id = :cid"),
            {"uid": uuid.UUID(s.user_id), "cid": p.class_id},
        )
        if not b_chk.first():
            return {"ok": False, "error": "CLASS_NOT_YOURS"}

        tr_res = await db.execute(
            text("SELECT trainer_id FROM fitness_classes WHERE id = :cid"),
            {"cid": p.class_id},
        )
        tr_row = tr_res.mappings().one_or_none()
        if tr_row:
            trainer_id = tr_row["trainer_id"]

    severity = p.severity_hint.upper()
    if p.category in ("SAFETY", "HARASSMENT", "INJURY") and severity in ("LOW", "MEDIUM"):
        severity = "HIGH"

    row_id = uuid.uuid4()
    await db.execute(
        text(
            """
            INSERT INTO issue_reports (
                id, reporter_id, class_id, trainer_id, category, severity, user_words, ai_summary
            ) VALUES (
                :id, :uid, :cid, :tid, :cat, :sev, :uw, :ai
            )
            """
        ),
        {
            "id": row_id,
            "uid": uuid.UUID(s.user_id),
            "cid": p.class_id,
            "tid": trainer_id,
            "cat": p.category,
            "sev": severity,
            "uw": p.user_words,
            "ai": p.neutral_summary,
        },
    )

    alert_key = "issue.urgent" if severity in ("HIGH", "URGENT") else "issue.created"
    await enqueue(
        db,
        user_id=None,
        routing_key=alert_key,
        template="ISSUE_ADMIN_ALERT",
        params={"issue_id": str(row_id)},
        dedupe_key=f"issue:{row_id}",
    )
    await enqueue(
        db,
        user_id=s.user_id,
        routing_key="email.issue",
        template="ISSUE_RECEIVED",
        params={},
        dedupe_key=f"issue-ack:{row_id}",
    )
    return {"ok": True, "issue_id": str(row_id), "severity": severity}


async def exec_decide_trainer_request(db: AsyncSession, s: SessionContext, action: Any) -> dict[str, Any]:
    p = DecidePayload.model_validate(action.payload)
    await set_rls_system(db)
    req_res = await db.execute(
        text("SELECT id, user_id, requested_role, status FROM role_requests WHERE id = :rid FOR UPDATE"),
        {"rid": p.request_id},
    )
    req = req_res.mappings().one_or_none()
    if not req or req["requested_role"] != "TRAINER" or req["status"] != "PENDING":
        return {"ok": False, "error": "REQUEST_NOT_PENDING"}

    decided_at = datetime.now(timezone.utc)
    target_uid = req["user_id"]

    if p.decision == "APPROVE":
        await db.execute(
            text(
                """
                UPDATE role_requests
                SET status = 'APPROVED', decided_by = :aid, decided_at = :now, reason = :reason
                WHERE id = :rid
                """
            ),
            {"rid": p.request_id, "aid": uuid.UUID(s.user_id), "now": decided_at, "reason": p.reason},
        )
        await db.execute(
            text("UPDATE users SET role = 'TRAINER', account_status = 'ACTIVE' WHERE id = :uid"),
            {"uid": target_uid},
        )
        await db.execute(
            text("INSERT INTO trainer_profiles (trainer_id) VALUES (:uid) ON CONFLICT DO NOTHING"),
            {"uid": target_uid},
        )
    elif p.decision == "REJECT":
        await db.execute(
            text(
                """
                UPDATE role_requests
                SET status = 'REJECTED', decided_by = :aid, decided_at = :now, reason = :reason
                WHERE id = :rid
                """
            ),
            {"rid": p.request_id, "aid": uuid.UUID(s.user_id), "now": decided_at, "reason": p.reason},
        )
        await db.execute(
            text("UPDATE users SET account_status = 'REJECTED' WHERE id = :uid"),
            {"uid": target_uid},
        )
    else:  # MORE_INFO
        await db.execute(
            text("UPDATE role_requests SET info_requested = :reason WHERE id = :rid"),
            {"rid": p.request_id, "reason": p.reason},
        )

    await enqueue(
        db,
        user_id=target_uid,
        routing_key="email.trainer_decision",
        template="TRAINER_DECISION",
        params={"decision": p.decision, "reason": p.reason},
        dedupe_key=f"trainer-decision:{p.request_id}:{p.decision}",
    )
    return {"ok": True, "decision": p.decision}


HANDLERS = {
    "BOOK_CLASS": exec_book,
    "CHANGE_PLAN": exec_change_plan,
    "CANCEL_BOOKING": exec_cancel_booking,
    "JOIN_WAITLIST": exec_join_waitlist,
    "SEND_BOOKING_EMAIL": exec_send_booking_email,
    "SUBMIT_ISSUE_REPORT": exec_issue_report,
    "ADMIN_DECIDE_TRAINER_REQUEST": exec_decide_trainer_request,
}


async def run_action(db: AsyncSession, s: SessionContext, action: Any) -> dict[str, Any]:
    """Dispatches action to handler and records audit trail."""
    action_type = getattr(action, "type", None) or action["type"]
    action_id = getattr(action, "id", None) or action["id"]

    if action_type in ADMIN_ONLY and (s.role != "ADMIN" or s.cooling_off_active):
        result = {"ok": False, "error": "FORBIDDEN"}
    elif action_type not in HANDLERS:
        result = {"ok": False, "error": f"NO_HANDLER_FOR_{action_type}"}
    else:
        handler = HANDLERS[action_type]
        result = await handler(db, s, action)

    # If payment awaiting: neither executed nor failed yet
    if result.get("awaiting"):
        await db.execute(
            text(
                """
                UPDATE pending_actions
                SET status = 'AWAITING_PAYMENT', result = CAST(:res AS jsonb)
                WHERE id = :aid
                """
            ),
            {"aid": action_id, "res": json.dumps(result)},
        )
        return result

    status_str = "EXECUTED" if result.get("ok") else "FAILED"
    await set_rls_system(db)
    await db.execute(
        text(
            """
            UPDATE pending_actions
            SET status = :status, result = CAST(:res AS jsonb), executed_at = NOW()
            WHERE id = :aid
            """
        ),
        {"aid": action_id, "status": status_str, "res": json.dumps(result)},
    )

    # Insert audit log
    await db.execute(
        text(
            """
            INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
            VALUES (:aid, :act, 'pending_actions', :eid, CAST(:dt AS jsonb))
            """
        ),
        {
            "aid": uuid.UUID(s.user_id),
            "act": f"EXEC_{action_type}",
            "eid": action_id,
            "dt": json.dumps(result),
        },
    )
    return result
