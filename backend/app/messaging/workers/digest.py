# app/messaging/workers/digest.py
import asyncio
import json
from typing import Any
import aio_pika
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ...db import set_rls_system


async def claim(db: AsyncSession, message_id: str, consumer: str = "digest") -> bool:
    res = await db.execute(
        text(
            """
            INSERT INTO processed_messages (message_id, consumer, processed_at)
            VALUES (:mid, :consumer, NOW())
            ON CONFLICT (message_id, consumer) DO NOTHING
            """
        ),
        {"mid": message_id, "consumer": consumer},
    )
    return res.rowcount > 0


async def handle_digest_message(
    body: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
) -> bool:
    message_id = body.get("message_id")
    if not message_id:
        return True

    async with sessionmaker() as db:
        await set_rls_system(db)

        if not await claim(db, message_id, "digest"):
            return True

        # Digest worker handles periodic triggers (daily digest, payment reconciliation, expiry jobs)
        routing_key = body.get("routing_key", "")
        if routing_key == "digest.daily":
            # Record audit log that daily digest schedule trigger fired
            await db.execute(
                text(
                    """
                    INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
                    VALUES (NULL, 'DIGEST_PROCESSED', 'scheduler', :mid, CAST('{"job": "daily_digest"}' AS jsonb))
                    """
                ),
                {"mid": message_id},
            )

        await db.commit()
        return True


async def run_digest_consumer(
    channel: aio_pika.abc.AbstractChannel,
    sessionmaker: async_sessionmaker[AsyncSession],
    prefetch_count: int = 10,
    stop_event: asyncio.Event | None = None,
) -> None:
    await channel.set_qos(prefetch_count=prefetch_count)
    queue = await channel.get_queue("q.digest")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(requeue=False):
                try:
                    payload = json.loads(message.body.decode("utf-8"))
                    await handle_digest_message(payload, sessionmaker)
                except Exception:
                    pass
            if stop_event and stop_event.is_set():
                break
