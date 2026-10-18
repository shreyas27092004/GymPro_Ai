# app/messaging/relay.py
import asyncio
import datetime
import json
from typing import Any
import aio_pika
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ..db import set_rls_system


def to_message(row: dict[str, Any]) -> dict[str, Any]:
    """Formats an outbox row into the canonical section 9.1 JSON message shape."""
    params = row["params"] if isinstance(row["params"], dict) else json.loads(row["params"])
    created_at = row.get("created_at") or datetime.datetime.now(datetime.timezone.utc)
    if hasattr(created_at, "isoformat"):
        created_str = created_at.isoformat()
    else:
        created_str = str(created_at)

    return {
        "v": 1,
        "message_id": str(row["id"]),
        "routing_key": row["routing_key"],
        "template": row["template"],
        "user_id": str(row["user_id"]) if row.get("user_id") else None,
        "params": params,
        "created_at": created_str,
        "trace_id": params.get("trace_id", ""),
    }


async def publish_outbox_batch(
    db: AsyncSession,
    exchange: aio_pika.abc.AbstractExchange,
    batch_size: int = 100,
) -> int:
    """
    Fetches one batch of due outbox rows, publishes to RabbitMQ with publisher confirms,
    and updates sent_at on success or increments attempts on failure.
    Returns the count of successfully confirmed messages.
    """
    # System context for reading outbox
    await set_rls_system(db)

    res = await db.execute(
        text(
            """
            SELECT id, user_id, channel, routing_key, template, params, dedupe_key, send_after, attempts, NOW() as created_at
            FROM notification_outbox
            WHERE sent_at IS NULL AND send_after <= NOW()
            ORDER BY send_after
            LIMIT :limit
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"limit": batch_size},
    )
    rows = [dict(r) for r in res.mappings().all()]
    if not rows:
        return 0

    confirmed_count = 0
    for r in rows:
        msg_payload = to_message(r)
        body_bytes = json.dumps(msg_payload).encode("utf-8")
        msg = aio_pika.Message(
            body=body_bytes,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(r["id"]),
            headers={"trace_id": msg_payload.get("trace_id", "")},
        )
        try:
            # exchange.publish on a channel with confirm_delivery=True waits for broker ACK
            await exchange.publish(msg, routing_key=r["routing_key"])
            await db.execute(
                text("UPDATE notification_outbox SET sent_at = NOW() WHERE id = :id"),
                {"id": r["id"]},
            )
            confirmed_count += 1
        except Exception:
            await db.execute(
                text("UPDATE notification_outbox SET attempts = attempts + 1 WHERE id = :id"),
                {"id": r["id"]},
            )

    await db.commit()
    return confirmed_count


async def relay_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    channel: aio_pika.abc.AbstractChannel,
    poll_interval: float = 1.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Continuous relay loop that periodically reads outbox and publishes."""
    exchange = await channel.get_exchange("gympro.events")
    while not (stop_event and stop_event.is_set()):
        try:
            async with sessionmaker() as db:
                await publish_outbox_batch(db, exchange)
        except Exception:
            # Log error and back off briefly
            pass
        if stop_event:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(poll_interval)
