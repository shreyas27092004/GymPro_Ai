# app/executor/schemas.py
from datetime import datetime
from decimal import Decimal
from typing import Any
import uuid
from pydantic import BaseModel, Field


class BookPayload(BaseModel):
    class_id: uuid.UUID


class ChangePlanPayload(BaseModel):
    to_plan: str
    cycle: str = "MONTHLY"
    confirmed_total: Decimal


class SendEmailPayload(BaseModel):
    template_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    attach_calendar: bool = False
    requires_step: int | None = None


class IssuePayload(BaseModel):
    class_id: uuid.UUID | None = None
    category: str
    severity_hint: str = "LOW"
    user_words: str
    neutral_summary: str | None = None


class DecidePayload(BaseModel):
    request_id: uuid.UUID
    decision: str  # APPROVE | REJECT | MORE_INFO
    reason: str | None = None


class CancelBookingPayload(BaseModel):
    booking_id: uuid.UUID


class JoinWaitlistPayload(BaseModel):
    class_id: uuid.UUID
