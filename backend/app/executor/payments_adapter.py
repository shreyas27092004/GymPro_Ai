# app/executor/payments_adapter.py
from ..payments.service import PayState, begin as service_begin

# Backwards-compatibility alias
PaymentResult = PayState

async def begin_payment(db, s, action, quote) -> PayState:
    """Delegates payment initiation to app.payments.service."""
    return await service_begin(db, s, action, quote)
