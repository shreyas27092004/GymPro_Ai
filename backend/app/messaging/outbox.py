# app/messaging/outbox.py
import json
import uuid
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def enqueue(
    db: AsyncSession,
    user_id: str | uuid.UUID | None,
    routing_key: str,
    template: str,
    params: dict[str, Any],
    dedupe_key: str | None = None,
    channel: str = "EMAIL",
) -> None:
    """Enqueue a message to the transactional outbox table in the current transaction."""
    uid = str(user_id) if user_id else None
    params_json = json.dumps(params)
    await db.execute(
        text(
            """
            INSERT INTO notification_outbox (user_id, channel, routing_key, template, params, dedupe_key)
            VALUES (:uid, :channel, :routing_key, :template, CAST(:params AS jsonb), :dedupe_key)
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
        },
    )
