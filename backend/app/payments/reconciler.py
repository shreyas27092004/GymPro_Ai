# app/payments/reconciler.py
from datetime import datetime, timezone
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import set_rls_system
from .provider import PaymentProvider, get_provider
from .service import finalize_paid, finalize_unpaid

logger = logging.getLogger(__name__)


async def reconcile_payments(
    db: AsyncSession,
    provider: PaymentProvider | None = None,
) -> dict[str, int]:
    """
    Reconciles open payments against the payment provider.
    - Payments in CREATED older than 2 minutes: checks if provider captured payment.
      If captured -> calls finalize_paid(..., "RECONCILER").
    - Payments in CREATED past expires_at with no capture -> calls finalize_unpaid(..., "PAYMENT_EXPIRED").
    """
    if provider is None:
        provider = get_provider()

    await set_rls_system(db)
    now = datetime.now(timezone.utc)

    # Find open CREATED payments
    res = await db.execute(
        text(
            """
            SELECT id, user_id, action_id, razorpay_order_id, status, created_at, expires_at
            FROM payments
            WHERE status = 'CREATED' AND razorpay_order_id IS NOT NULL
            """
        )
    )
    open_payments = res.mappings().all()

    finalized_paid = 0
    finalized_expired = 0

    for pay in open_payments:
        order_id = pay["razorpay_order_id"]
        created_at = pay["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        expires_at = pay["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        age_seconds = (now - created_at).total_seconds()
        is_expired = now > expires_at

        # Check provider payments if older than 2 minutes or expired
        captured_item = None
        if age_seconds >= 120 or is_expired:
            try:
                items = await provider.list_order_payments(order_id)
                for it in items:
                    if it.get("status") in ("captured", "paid"):
                        captured_item = it
                        break
            except Exception as e:
                logger.warning("Failed to list order payments for %s: %s", order_id, e)

        if captured_item:
            res_paid = await finalize_paid(db, order_id, captured_item["id"], "RECONCILER")
            if res_paid.get("ok"):
                finalized_paid += 1
        elif is_expired:
            res_unpaid = await finalize_unpaid(db, pay["id"], "PAYMENT_EXPIRED")
            if res_unpaid.get("ok"):
                finalized_expired += 1

    return {"paid": finalized_paid, "expired": finalized_expired}
