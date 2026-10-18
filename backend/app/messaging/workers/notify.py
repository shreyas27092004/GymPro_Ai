# app/messaging/workers/notify.py
import asyncio
import json
from typing import Any
import aio_pika
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ...db import set_rls_system


async def claim(db: AsyncSession, message_id: str, consumer: str = "notify") -> bool:
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


async def handle_notify_message(
    body: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
) -> bool:
    message_id = body.get("message_id")
    if not message_id:
        return True

    user_id = body.get("user_id")
    routing_key = body.get("routing_key", "")
    params = body.get("params", {})
    template = body.get("template", "")

    async with sessionmaker() as db:
        await set_rls_system(db)

        if not await claim(db, message_id, "notify"):
            return True

        title = params.get("title", f"Notice: {routing_key}")
        message = params.get("message", f"Update regarding {template}")

        # If user_id is provided, create direct notification
        if user_id:
            await db.execute(
                text(
                    """
                    INSERT INTO notifications (user_id, title, message, created_at)
                    VALUES (:uid, :title, :msg, NOW())
                    """
                ),
                {"uid": user_id, "title": title, "msg": message},
            )
        elif routing_key.startswith("issue.") or "admin" in routing_key:
            # Fan out urgent issue notification to all active admins
            admins_res = await db.execute(
                text("SELECT id FROM users WHERE role = 'ADMIN' AND account_status = 'ACTIVE' AND deleted_at IS NULL")
            )
            for adm in admins_res.mappings().all():
                await db.execute(
                    text(
                        """
                        INSERT INTO notifications (user_id, title, message, created_at)
                        VALUES (:uid, :title, :msg, NOW())
                        """
                    ),
                    {"uid": adm["id"], "title": title, "msg": message},
                )

        await db.commit()
        return True


async def run_notify_consumer(
    channel: aio_pika.abc.AbstractChannel,
    sessionmaker: async_sessionmaker[AsyncSession],
    prefetch_count: int = 10,
    stop_event: asyncio.Event | None = None,
) -> None:
    await channel.set_qos(prefetch_count=prefetch_count)
    queue = await channel.get_queue("q.notify")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(requeue=False):
                try:
                    payload = json.loads(message.body.decode("utf-8"))
                    await handle_notify_message(payload, sessionmaker)
                except Exception:
                    pass
            if stop_event and stop_event.is_set():
                break
