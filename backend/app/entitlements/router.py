# app/entitlements/router.py
from typing import Any
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from ..auth.deps import SessionContext, get_session
from ..db import get_db
from .intake import (
    IntakeUpdate,
    get_intake_history,
    get_member_profile,
    save_member_profile,
    set_health_consent,
)
from .membership import (
    execute_upgrade,
    get_active_membership,
    list_membership_plans,
    price_diff,
)
from .trial import get_active_trial

router = APIRouter(tags=["Entitlements & Intake"])


class UpgradeRequest(BaseModel):
    to_plan: str
    cycle: str = "MONTHLY"


# -------------------------------------------------------------------------
# Plans & Membership
# -------------------------------------------------------------------------
@router.get("/plans", status_code=status.HTTP_200_OK)
async def api_list_plans(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Browse catalog of membership plans."""
    return await list_membership_plans(db)


@router.get("/me/membership", status_code=status.HTTP_200_OK)
async def api_get_my_membership(
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve caller's own active membership."""
    m = await get_active_membership(db, s.user_id)
    if not m:
        return {"active": False, "membership": None}
    return {"active": True, "membership": m}


@router.get("/me/trial", status_code=status.HTTP_200_OK)
async def api_get_my_trial(
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve caller's trial status."""
    trial = await get_active_trial(db, s.user_id)
    if not trial:
        return {"active": False, "trial": None}
    return {"active": True, "trial": trial}


@router.post("/me/membership/quote", status_code=status.HTTP_200_OK)
async def api_membership_quote(
    body: UpgradeRequest,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Proration calculation quote for plan upgrade/change."""
    quote = await price_diff(db, s.user_id, body.to_plan, body.cycle)
    return quote.to_dict()


@router.post("/me/membership/upgrade", status_code=status.HTTP_200_OK)
async def api_membership_upgrade(
    body: UpgradeRequest,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Direct membership upgrade execution (replaces old membership)."""
    res = await execute_upgrade(db, s.user_id, body.to_plan, body.cycle)
    await db.commit()
    return res


# -------------------------------------------------------------------------
# Intake & Health-Data Consent
# -------------------------------------------------------------------------
@router.get("/me/intake", status_code=status.HTTP_200_OK)
async def api_get_intake(
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve member's current intake profile questionnaire."""
    profile = await get_member_profile(db, s.user_id)
    return profile or {}


@router.put("/me/intake", status_code=status.HTTP_200_OK)
async def api_save_intake(
    body: IntakeUpdate,
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Update member's intake questionnaire.
    Database trigger automatically snapshots the update into member_intake_versions.
    """
    updated = await save_member_profile(db, s.user_id, body)
    await db.commit()
    return updated


@router.post("/me/consent", status_code=status.HTTP_200_OK)
async def api_grant_consent(
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Grant revocable health-data consent."""
    res = await set_health_consent(db, s.user_id, granted=True)
    await db.commit()
    return res


@router.delete("/me/consent", status_code=status.HTTP_200_OK)
async def api_revoke_consent(
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Withdraw revocable health-data consent."""
    res = await set_health_consent(db, s.user_id, granted=False)
    await db.commit()
    return res


@router.get("/me/memory", status_code=status.HTTP_200_OK)
async def api_get_memory(
    s: SessionContext = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Audit trail of what the AI remembers (snapshots from member_intake_versions)."""
    return await get_intake_history(db, s.user_id)
