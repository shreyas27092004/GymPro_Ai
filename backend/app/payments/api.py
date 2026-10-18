# app/payments/api.py
from datetime import datetime, timezone
import json
from typing import Any
import uuid
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext, get_session
from ..db import get_db, set_rls_system
from ..ratelimit import check_rate_limit
from ..settings import settings
from .provider import get_provider
from .service import finalize_paid, finalize_unpaid

router = APIRouter(prefix="/payments", tags=["payments"])


class VerifyBody(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


def rate_limit(bucket: str, limit: int, window_s: float):
    async def _dep(s: SessionContext = Depends(get_session)) -> None:
        key = f"{bucket}:{s.user_id}"
        if not check_rate_limit(key, limit, window_s):
            raise HTTPException(status_code=429, detail="RATE_LIMIT_EXCEEDED")
    return _dep


async def payment_state_with_steps(db: AsyncSession, payment_id: uuid.UUID) -> dict[str, Any]:
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT p.id, p.user_id, p.action_id, p.status, p.amount_minor, p.currency,
                   p.razorpay_order_id, p.razorpay_payment_id, a.bundle_id
            FROM payments p
            JOIN pending_actions a ON p.action_id = a.id
            WHERE p.id = :id
            """
        ),
        {"id": payment_id},
    )
    row = res.mappings().one_or_none()
    if not row:
        return {}

    steps = []
    if row["bundle_id"]:
        from ..executor.bundles import step_results
        steps = await step_results(db, row["bundle_id"])

    return {
        "ok": True,
        "payment_id": str(row["id"]),
        "status": row["status"],
        "order_id": row["razorpay_order_id"],
        "payment_ref": row["razorpay_payment_id"],
        "steps": steps,
    }


@router.post("/razorpay/verify")
async def verify(
    body: VerifyBody,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("pay-verify", 10, 600)),
) -> dict[str, Any]:
    """
    Authenticated callback from Checkout.js.
    Validates HMAC signature and order ownership, finalizes payment,
    activates membership, and resumes any paused bundle.
    """
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT id, user_id, action_id, status, amount_minor, currency, razorpay_order_id
            FROM payments
            WHERE razorpay_order_id = :oid
            """
        ),
        {"oid": body.razorpay_order_id},
    )
    pay = res.mappings().one_or_none()
    if not pay:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment order not found")

    # Order must belong to authenticated user
    if str(pay["user_id"]) != s.user_id and s.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment order not found")

    prov = get_provider()
    if not prov.verify_checkout_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        # Audit invalid signature attempt
        await set_rls_system(db)
        await db.execute(
            text(
                """
                INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
                VALUES (:actor, 'PAYMENT_SIGNATURE_INVALID', 'payments', :pid, CAST(:meta AS jsonb))
                """
            ),
            {
                "actor": uuid.UUID(s.user_id),
                "pid": pay["id"],
                "meta": json.dumps({"order_id": body.razorpay_order_id}),
            },
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PAYMENT_SIGNATURE_INVALID")

    res_final = await finalize_paid(db, body.razorpay_order_id, body.razorpay_payment_id, "VERIFY")
    if not res_final.get("ok") and not res_final.get("replay"):
        if res_final.get("error") == "PAYMENT_NEEDS_REVIEW":
            return {"ok": False, "status": "NEEDS_REVIEW", "error": "PAYMENT_NEEDS_REVIEW"}
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res_final.get("error"))

    return await payment_state_with_steps(db, pay["id"])


@router.post("/razorpay/webhook")
async def webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_razorpay_signature: str | None = Header(None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: str | None = Header(None, alias="X-Razorpay-Event-Id"),
) -> dict[str, Any]:
    """
    Public webhook from Razorpay. Authenticated strictly by HMAC signature over raw body bytes.
    Deduplicated by X-Razorpay-Event-Id header.
    """
    raw_body = await request.body()
    prov = get_provider()

    if not x_razorpay_signature or not prov.verify_webhook(raw_body, x_razorpay_signature):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PAYMENT_SIGNATURE_INVALID")

    try:
        data = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_JSON_BODY")

    event_id = x_razorpay_event_id or data.get("event_id") or f"ev_{uuid.uuid4().hex}"
    event_name = data.get("event", "")

    # Deduplicate in payment_events table
    await set_rls_system(db)
    payload_entity = data.get("payload", {})
    order_id = (
        payload_entity.get("payment", {}).get("entity", {}).get("order_id")
        or payload_entity.get("order", {}).get("entity", {}).get("id")
    )

    ev_ins = await db.execute(
        text(
            """
            INSERT INTO payment_events (event_id, event, order_id, payload)
            VALUES (:eid, :ev, :oid, CAST(:payload AS jsonb))
            ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id
            """
        ),
        {
            "eid": event_id,
            "ev": event_name,
            "oid": order_id,
            "payload": json.dumps(data),
        },
    )
    if not ev_ins.first():
        # Duplicate event delivery: acknowledge cleanly without re-executing
        return {"ok": True, "duplicate": True}
    await db.commit()

    # Process events
    if event_name in ("payment.captured", "order.paid"):
        payment_entity = payload_entity.get("payment", {}).get("entity", {})
        pid = payment_entity.get("id") or f"pay_{uuid.uuid4().hex[:10]}"
        target_order = payment_entity.get("order_id") or order_id
        if target_order:
            await finalize_paid(db, target_order, pid, "WEBHOOK")

    elif event_name == "payment.failed":
        # Increment attempt counter only (not terminal)
        payment_entity = payload_entity.get("payment", {}).get("entity", {})
        target_order = payment_entity.get("order_id") or order_id
        if target_order:
            await set_rls_system(db)
            await db.execute(
                text("UPDATE payments SET attempts = attempts + 1 WHERE razorpay_order_id = :oid"),
                {"oid": target_order},
            )
            await db.commit()

    elif event_name == "refund.processed":
        refund_entity = payload_entity.get("refund", {}).get("entity", {})
        ref_amt = refund_entity.get("amount", 0)
        target_pid = refund_entity.get("payment_id")
        if target_pid:
            await set_rls_system(db)
            await db.execute(
                text(
                    """
                    UPDATE payments
                    SET refunded_minor = refunded_minor + :ramt,
                        status = CASE WHEN refunded_minor + :ramt >= amount_minor THEN 'REFUNDED' ELSE 'PARTIALLY_REFUNDED' END
                    WHERE razorpay_payment_id = :pid
                    """
                ),
                {"ramt": ref_amt, "pid": target_pid},
            )
            await db.commit()

    return {"ok": True}


@router.get("/{payment_id}")
async def get_payment(
    payment_id: uuid.UUID,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieves payment status and, if CREATED, returns checkout details to reopen."""
    await set_rls_system(db)
    res = await db.execute(
        text(
            """
            SELECT p.id, p.user_id, p.action_id, p.provider, p.purpose, p.amount_minor,
                   p.currency, p.status, p.razorpay_order_id, p.razorpay_payment_id,
                   p.quote, p.attempts, p.refunded_minor, p.failure_code, p.expires_at,
                   p.created_at, p.paid_at, a.summary
            FROM payments p
            JOIN pending_actions a ON p.action_id = a.id
            WHERE p.id = :id
            """
        ),
        {"id": payment_id},
    )
    pay = res.mappings().one_or_none()
    if not pay:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    if str(pay["user_id"]) != s.user_id and s.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    out: dict[str, Any] = {
        "id": str(pay["id"]),
        "status": pay["status"],
        "amount_minor": pay["amount_minor"],
        "currency": pay["currency"],
        "order_id": pay["razorpay_order_id"],
        "payment_ref": pay["razorpay_payment_id"],
        "failure_code": pay["failure_code"],
        "attempts": pay["attempts"],
        "refunded_minor": pay["refunded_minor"],
    }

    if pay["status"] == "CREATED":
        exp = pay["expires_at"]
        exp_iso = exp.isoformat() if hasattr(exp, "isoformat") else str(exp)
        out["checkout"] = {
            "payment_id": str(pay["id"]),
            "key_id": settings.razorpay_key_id or "",
            "order_id": pay["razorpay_order_id"],
            "amount_minor": pay["amount_minor"],
            "currency": pay["currency"],
            "description": (pay["summary"] or "")[:120],
            "expires_at": exp_iso,
        }

    return out


@router.post("/{payment_id}/cancel")
async def cancel_payment(
    payment_id: uuid.UUID,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Allows user to cancel an open checkout. Marks payment FAILED and resumes bundle."""
    await set_rls_system(db)
    res = await db.execute(
        text("SELECT id, user_id, status FROM payments WHERE id = :id"),
        {"id": payment_id},
    )
    pay = res.mappings().one_or_none()
    if not pay:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    if str(pay["user_id"]) != s.user_id and s.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    res_cancel = await finalize_unpaid(db, payment_id, "PAYMENT_CANCELLED")
    return {"ok": True, "status": "CANCELLED"}
