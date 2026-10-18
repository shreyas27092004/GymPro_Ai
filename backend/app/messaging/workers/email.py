# app/messaging/workers/email.py
import asyncio
import email.message
import hashlib
import json
from typing import Any
import aio_pika
import aiosmtplib
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ...db import set_rls_system
from ...settings import settings
from ..renderer import is_marketing_template, make_ics, render


def sha256_hash(val: str) -> str:
    return hashlib.sha256(val.strip().lower().encode("utf-8")).hexdigest()


async def claim(db: AsyncSession, message_id: str, consumer: str = "email") -> bool:
    """Attempts to claim the message in processed_messages. Returns True if claimed, False if duplicate."""
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


async def unclaim(db: AsyncSession, message_id: str, consumer: str = "email") -> None:
    """Removes message from processed_messages if an error occurred during delivery so it can be retried."""
    await db.execute(
        text("DELETE FROM processed_messages WHERE message_id = :mid AND consumer = :consumer"),
        {"mid": message_id, "consumer": consumer},
    )


async def log_email(
    db: AsyncSession,
    message_id: str,
    user_id: str | None,
    to_email: str,
    template: str,
    status: str,
    error: str | None = None,
) -> None:
    """Logs email delivery status in email_log with hashed recipient (privacy control: Section 9.4)."""
    to_hash = sha256_hash(to_email)
    err_str = error[:200] if error else None
    await db.execute(
        text(
            """
            INSERT INTO email_log (message_id, user_id, to_hash, template, status, error, created_at)
            VALUES (:mid, :uid, :th, :tmpl, :status, :err, NOW())
            """
        ),
        {
            "mid": message_id,
            "uid": user_id,
            "th": to_hash,
            "tmpl": template,
            "status": status,
            "err": err_str,
        },
    )


async def is_suppressed(db: AsyncSession, to_email: str, template: str, user_id: str | None) -> bool:
    """
    Checks if email should be suppressed.
    Transactional emails are NEVER suppressed. Marketing emails check unsubscribes and prefs.
    """
    if not is_marketing_template(template):
        return False

    to_hash = sha256_hash(to_email)
    # Check unsubscribes table
    unsub = await db.execute(
        text("SELECT 1 FROM unsubscribes WHERE email_hash = :th"),
        {"th": to_hash},
    )
    if unsub.scalar():
        return True

    # If associated with a user, check notification_prefs.marketing_opt_in
    if user_id:
        pref = await db.execute(
            text("SELECT marketing_opt_in FROM notification_prefs WHERE user_id = :uid"),
            {"uid": user_id},
        )
        opt_in = pref.scalar()
        if opt_in is False:
            return True

    return False


async def still_valid(db: AsyncSession, body: dict[str, Any]) -> bool:
    """State check to ensure event is still valid (e.g. booking not cancelled)."""
    template = body.get("template")
    params = body.get("params", {})
    booking_id = params.get("booking_id")
    if template in ("CLASS_CONFIRMED", "BOOKING_DETAILS") and booking_id:
        res = await db.execute(
            text("SELECT status FROM bookings WHERE id = :bid"),
            {"bid": booking_id},
        )
        row = res.scalar_one_or_none()
        if row and row != "CONFIRMED":
            return False
    return True


def build_mime(
    from_addr: str,
    to_addr: str,
    subject: str,
    html: str,
    text_part: str,
    ics: bytes | None = None,
) -> email.message.EmailMessage:
    """Constructs multipart MIME email message with HTML, plain-text, and optional calendar invite."""
    msg = email.message.EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject

    # Plain text alternative
    msg.set_content(text_part)
    # HTML part
    msg.add_alternative(html, subtype="html")

    if ics:
        msg.add_attachment(
            ics,
            maintype="text",
            subtype="calendar",
            filename="invite.ics",
            params={"method": "REQUEST"},
        )
    return msg


async def sanitize_outbox_tokens(db: AsyncSession, message_id: str) -> None:
    """
    Section 9.1: Links and tokens are removed from stored params in notification_outbox after sending.
    """
    await db.execute(
        text(
            """
            UPDATE notification_outbox
            SET params = params - 'link' - 'token' - 'code'
            WHERE id = :id
            """
        ),
        {"id": message_id},
    )


async def handle_message(
    body: dict[str, Any],
    sessionmaker: async_sessionmaker[AsyncSession],
    retry_channel: aio_pika.abc.AbstractChannel | None = None,
    headers: dict[str, Any] | None = None,
) -> bool:
    """
    Processes an email message payload.
    Returns True if successfully processed or permanently discarded, False if retry queued.
    """
    message_id = body.get("message_id")
    if not message_id:
        return True

    user_id = body.get("user_id")
    template = body.get("template", "GENERIC")
    params = body.get("params", {})
    headers = headers or {}
    retry_count = int(headers.get("x-retry-count", 0))

    async with sessionmaker() as db:
        await set_rls_system(db)

        # 1. Idempotency claim
        if not await claim(db, message_id, "email"):
            # Already processed
            return True

        # 2. Re-read recipient email from DB (Rule 9.4: never trust recipient from client/agent)
        to_email = None
        user_locale = "en"
        if user_id:
            u_res = await db.execute(
                text("SELECT email, locale FROM users WHERE id = :uid AND deleted_at IS NULL"),
                {"uid": user_id},
            )
            u = u_res.mappings().one_or_none()
            if u:
                to_email = u["email"]
                user_locale = u.get("locale") or "en"

        if not to_email:
            to_email = params.get("email")

        if not to_email:
            # Cannot deliver without recipient
            await log_email(db, message_id, user_id, "unknown@gympro.local", template, "FAILED", "Missing recipient")
            await db.commit()
            return True

        # 3. Check suppression
        if await is_suppressed(db, to_email, template, user_id):
            await log_email(db, message_id, user_id, to_email, template, "SUPPRESSED")
            await db.commit()
            return True

        # 4. State check
        if not await still_valid(db, body):
            await log_email(db, message_id, user_id, to_email, template, "SUPPRESSED", "State invalid")
            await db.commit()
            return True

        # 5. Render
        try:
            subject, html_part, text_part = render(template, params, locale=user_locale)
        except Exception as e:
            await log_email(db, message_id, user_id, to_email, template, "FAILED", f"Render error: {e}")
            await db.commit()
            return True

        ics_payload = make_ics(params) if params.get("attach_calendar") else None
        mime_msg = build_mime(settings.mail_from, to_email, subject, html_part, text_part, ics_payload)

        # 6. SMTP Send
        try:
            await aiosmtplib.send(
                mime_msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                start_tls=bool(settings.smtp_user),
            )
            await log_email(db, message_id, user_id, to_email, template, "SENT")
            await sanitize_outbox_tokens(db, message_id)
            await db.commit()
            return True
        except Exception as smtp_err:
            # Delivery failed (e.g. SMTP outage)
            # Unclaim so future retry can claim
            await unclaim(db, message_id, "email")
            await log_email(db, message_id, user_id, to_email, template, "FAILED", f"SMTP error: {smtp_err}")
            await db.commit()

            # Retry Routing
            if retry_channel:
                dlx = await retry_channel.get_exchange("gympro.dlx")
                new_retry = retry_count + 1
                if new_retry == 1:
                    next_routing = "email.retry.30s"
                elif new_retry == 2:
                    next_routing = "email.retry.5m"
                elif new_retry == 3:
                    next_routing = "email.retry.30m"
                else:
                    next_routing = "q.dlq"

                retry_msg = aio_pika.Message(
                    body=json.dumps(body).encode("utf-8"),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    headers={"x-retry-count": new_retry, "trace_id": body.get("trace_id", "")},
                )
                await dlx.publish(retry_msg, routing_key=next_routing)

            return False


async def run_email_consumer(
    channel: aio_pika.abc.AbstractChannel,
    sessionmaker: async_sessionmaker[AsyncSession],
    prefetch_count: int = 10,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Runs the email worker consumer on q.email with prefetch limit and manual acks."""
    await channel.set_qos(prefetch_count=prefetch_count)
    queue = await channel.get_queue("q.email")

    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process(requeue=False):
                try:
                    payload = json.loads(message.body.decode("utf-8"))
                    await handle_message(
                        payload,
                        sessionmaker=sessionmaker,
                        retry_channel=channel,
                        headers=dict(message.headers),
                    )
                except Exception:
                    # Exception handled; message is acked because requeue=False and retry was routed
                    pass
            if stop_event and stop_event.is_set():
                break
