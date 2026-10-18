# app/executor/payments_adapter.py
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext
from ..db import set_rls_system
from ..settings import settings


@dataclass
class PaymentResult:
    state: str  # "PAID" | "AWAITING" | "FAILED"
    id: uuid.UUID | None
    checkout: dict[str, Any] | None = None
    error: str | None = None


async def begin_payment(
    db: AsyncSession,
    s: SessionContext,
    action: Any,
    quote: Any,
) -> PaymentResult:
    """
    Initiates payment for an action.
    - If settings.payments_mode == 'mock', instantly marks as PAID.
    - If settings.payments_mode == 'razorpay', returns AWAITING with checkout payload.
    - If disabled, returns FAILED with PAYMENT_PROVIDER_REQUIRED.
    """
    mode = settings.payments_mode
    if mode == "disabled":
        return PaymentResult(state="FAILED", id=None, error="PAYMENT_PROVIDER_REQUIRED")

    payment_id = uuid.uuid4()
    amount_minor = int(Decimal(str(quote.prorated_today)) * 100)
    currency = getattr(quote, "currency", "INR")
    quote_dict = {
        "from_plan": getattr(quote, "from_plan", None),
        "to_plan": getattr(quote, "to_plan", None),
        "delta_per_cycle": float(getattr(quote, "delta_per_cycle", 0)),
        "prorated_today": float(getattr(quote, "prorated_today", 0)),
        "next_billing_date": (
            quote.next_billing_date.isoformat()
            if hasattr(getattr(quote, "next_billing_date", None), "isoformat")
            else str(getattr(quote, "next_billing_date", ""))
        ),
    }

    if mode == "mock":
        # Create PAID payment record under SYSTEM role to bypass write RLS
        await set_rls_system(db)
        await db.execute(
            text(
                """
                INSERT INTO payments (
                    id, user_id, action_id, provider, purpose, amount_minor,
                    currency, status, quote, expires_at, paid_at
                ) VALUES (
                    :id, :uid, :aid, 'MOCK', 'PLAN_CHANGE', :amt,
                    :curr, 'PAID', CAST(:quote AS jsonb), NOW() + INTERVAL '15 minutes', NOW()
                )
                """
            ),
            {
                "id": payment_id,
                "uid": uuid.UUID(s.user_id),
                "aid": action.id,
                "amt": amount_minor,
                "curr": currency,
                "quote": json.dumps(quote_dict),
            },
        )
        return PaymentResult(state="PAID", id=payment_id)

    elif mode == "razorpay":
        # Create CREATED payment record
        await set_rls_system(db)
        order_id = f"order_mock_{uuid.uuid4().hex[:12]}"
        await db.execute(
            text(
                """
                INSERT INTO payments (
                    id, user_id, action_id, provider, purpose, amount_minor,
                    currency, status, razorpay_order_id, quote, expires_at
                ) VALUES (
                    :id, :uid, :aid, 'RAZORPAY', 'PLAN_CHANGE', :amt,
                    :curr, 'CREATED', :order_id, CAST(:quote AS jsonb), NOW() + INTERVAL '15 minutes'
                )
                """
            ),
            {
                "id": payment_id,
                "uid": uuid.UUID(s.user_id),
                "aid": action.id,
                "amt": amount_minor,
                "curr": currency,
                "order_id": order_id,
                "quote": json.dumps(quote_dict),
            },
        )
        checkout_info = {
            "order_id": order_id,
            "amount_minor": amount_minor,
            "currency": currency,
            "key_id": settings.razorpay_key_id or "rzp_test_placeholder",
        }
        return PaymentResult(state="AWAITING", id=payment_id, checkout=checkout_info)

    return PaymentResult(state="FAILED", id=None, error="UNKNOWN_PAYMENT_MODE")
