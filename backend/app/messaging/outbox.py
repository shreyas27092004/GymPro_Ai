# app/messaging/outbox.py
import datetime
import json
import uuid
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def enqueue(
    db: AsyncSession,
    user_id: str | uuid.UUID | None = None,
    routing_key: str = "email.notify",
    template: str = "GENERIC",
    params: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    send_after: datetime.datetime | None = None,
    channel: str = "EMAIL",
    **kwargs: Any,
) -> None:
    """Enqueue a message to the transactional outbox table in the current transaction."""
    if "user_id" in kwargs:
        user_id = kwargs["user_id"]
    if "routing_key" in kwargs:
        routing_key = kwargs["routing_key"]
    if "template" in kwargs:
        template = kwargs["template"]
    if "params" in kwargs:
        params = kwargs["params"]
    if "dedupe_key" in kwargs:
        dedupe_key = kwargs["dedupe_key"]
    if "send_after" in kwargs:
        send_after = kwargs["send_after"]
    if "channel" in kwargs:
        channel = kwargs["channel"]

    uid = str(user_id) if user_id else None
    params_json = json.dumps(params or {})
    await db.execute(
        text(
            """
            INSERT INTO notification_outbox (user_id, channel, routing_key, template, params, dedupe_key, send_after)
            VALUES (:uid, :channel, :routing_key, :template, CAST(:params AS jsonb), :dedupe_key, COALESCE(:send_after, NOW()))
            ON CONFLICT (dedupe_key) DO NOTHING
            """
        ),
        {
            "uid": uid,
            "channel": channel,
            "routing_key": routing_key,
            "template": template,
            "params": params_json,
            "dedupe_key": dedupe_key,
            "send_after": send_after,
        },
    )
