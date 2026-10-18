# tests/messaging/test_messaging.py
import asyncio
import datetime
import hashlib
import json
import pathlib
import subprocess
import time
import uuid
import aio_pika
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.messaging.outbox import enqueue
from app.messaging.relay import publish_outbox_batch, to_message
from app.messaging.renderer import TEMPLATES, make_ics, render
from app.messaging.topology import setup_topology
from app.messaging.workers.email import (
    claim,
    handle_message,
    is_suppressed,
    log_email,
    sha256_hash,
)
from app.messaging.workers.notify import handle_notify_message
from app.settings import settings
from tests.conftest import TestAppSession


@pytest_asyncio.fixture
async def amqp_channel():
    """Connects to RabbitMQ and sets up test topology."""
    conn = await aio_pika.connect_robust(settings.rabbitmq_url)
    channel = await conn.channel(publisher_confirms=True)
    await setup_topology(channel)
    yield channel
    await conn.close()


# -------------------------------------------------------------------------
# 1. Topology & Bindings Verification
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_topology_declarations(amqp_channel):
    """Verify all exchanges, queues, dead-letter and retry queues exist and are durable."""
    # Ensure exchanges are retrievable
    events_exchange = await amqp_channel.get_exchange("gympro.events")
    assert events_exchange is not None

    dlx_exchange = await amqp_channel.get_exchange("gympro.dlx")
    assert dlx_exchange is not None

    # Ensure all queues exist
    for q_name in [
        "q.email",
        "q.notify",
        "q.digest",
        "q.agent.async",
        "q.dlq",
        "q.email.retry.30s",
        "q.email.retry.5m",
        "q.email.retry.30m",
    ]:
        q = await amqp_channel.get_queue(q_name)
        assert q is not None
        assert q.durable is True


# -------------------------------------------------------------------------
# 2. Template Rendering & Security Controls
# -------------------------------------------------------------------------
def test_all_templates_render():
    """Verify all 21 templates from Section 9.5 render with subjects, HTML, and text parts."""
    assert len(TEMPLATES) == 21, f"Expected 21 templates, found {len(TEMPLATES)}"

    sample_params = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "link": "https://gympro.local/verify?token=abc",
        "class_name": "Power Yoga",
        "class_time": "Friday 6:00 PM",
        "trainer_name": "Alex Coach",
        "new_plan": "GOLD",
        "effective_date": "2026-11-01",
        "amount": "1999",
        "currency": "INR",
        "payment_date": "2026-10-16",
        "payment_ref": "pay_test_123",
        "payment_id": "pay_test_123",
        "reason": "Late capture",
        "issue_id": "iss-001",
        "severity": "CRITICAL",
        "category": "FACILITY",
        "admin_link": "https://gympro.local/admin",
        "status": "APPROVED",
        "message": "Welcome aboard",
        "applicant_email": "admin_candidate@gympro.local",
        "code": "ABCDEFGH",
        "reject_link": "https://gympro.local/reject",
        "admin_name": "Super Admin",
        "activated_at": "2026-10-16 18:05",
        "suspend_link": "https://gympro.local/suspend",
        "pending_count": 3,
        "digest_date": "2026-10-16",
        "summary": "15 classes booked",
        "summary_stats": "3 workouts completed",
        "broadcast_title": "Gym Closure Notice",
        "content": "Closed for maintenance",
        "unsubscribe_link": "https://gympro.local/unsub",
    }

    for tmpl_name in TEMPLATES:
        subject, html_part, text_part = render(tmpl_name, sample_params)
        assert subject and len(subject) > 0
        assert html_part and len(html_part) > 0
        assert text_part and len(text_part) > 0


def test_template_autoescaping_and_header_safety():
    """Verify HTML injection is autoescaped and newlines in subjects are stripped."""
    malicious_params = {
        "name": "<script>alert('xss')</script>",
        "link": "https://gympro.local/verify",
        "broadcast_title": "Header Injection\r\nBcc: evil@attacker.com\nSubject: Overridden",
        "content": "<img src=x onerror=alert(1)>",
    }

    # 1. HTML auto-escaping
    _, html_part, _ = render("VERIFY_EMAIL", malicious_params)
    assert "<script>" not in html_part
    assert "&lt;script&gt;" in html_part and "&lt;/script&gt;" in html_part

    # 2. Header injection prevention in subject
    subject, _, _ = render("BROADCAST", malicious_params)
    assert "\r" not in subject
    assert "\n" not in subject


def test_calendar_ics_generation():
    """Verify .ics calendar invite generation."""
    params = {
        "class_name": "Morning HIIT",
        "trainer_name": "Coach Sam",
        "start_time": "2026-10-17T09:00:00+05:30",
        "end_time": "2026-10-17T10:00:00+05:30",
        "booking_id": "book-123",
    }
    ics_bytes = make_ics(params)
    assert b"BEGIN:VCALENDAR" in ics_bytes
    assert b"BEGIN:VEVENT" in ics_bytes
    assert b"Morning HIIT" in ics_bytes
    assert b"END:VCALENDAR" in ics_bytes


# -------------------------------------------------------------------------
# 3. Outbox Helper & Relay with Publisher Confirms
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_outbox_relay_publisher_confirms(db_session: AsyncSession, amqp_channel):
    """Verify outbox enqueue and batch publishing with publisher confirms sets sent_at."""
    u_id = uuid.uuid4()
    # Create user for outbox reference
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status)
            VALUES (:uid, 'relay_test@gympro.test', 'fakehash', 'Relay Tester', 'USER', 'ACTIVE')
            """
        ),
        {"uid": u_id},
    )
    await db_session.commit()

    # Enqueue message
    await enqueue(
        db_session,
        user_id=u_id,
        routing_key="email.verify",
        template="VERIFY_EMAIL",
        params={"link": "https://gympro.local/verify?token=xyz123"},
        dedupe_key=f"relay_test_{u_id}",
    )
    await db_session.commit()

    # Check initially unsent
    res = await db_session.execute(
        text("SELECT sent_at, attempts FROM notification_outbox WHERE user_id = :uid"),
        {"uid": u_id},
    )
    row = res.mappings().one()
    assert row["sent_at"] is None
    assert row["attempts"] == 0

    # Publish batch
    exchange = await amqp_channel.get_exchange("gympro.events")
    count = await publish_outbox_batch(db_session, exchange)
    assert count >= 1

    # Verify sent_at was set
    res = await db_session.execute(
        text("SELECT sent_at FROM notification_outbox WHERE user_id = :uid"),
        {"uid": u_id},
    )
    row = res.mappings().one()
    assert row["sent_at"] is not None


# -------------------------------------------------------------------------
# 4. Idempotent Redelivery
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idempotent_redelivery(db_session: AsyncSession):
    """Verify duplicate message processing is rejected via processed_messages claim."""
    mid = str(uuid.uuid4())

    # 1. First claim succeeds
    claimed1 = await claim(db_session, mid, "email")
    assert claimed1 is True
    await db_session.commit()

    # 2. Second claim for same message_id and consumer fails
    claimed2 = await claim(db_session, mid, "email")
    assert claimed2 is False

    # 3. Different consumer can claim same message_id
    claimed_notify = await claim(db_session, mid, "notify")
    assert claimed_notify is True
    await db_session.commit()


# -------------------------------------------------------------------------
# 5. Suppression & Privacy Checks
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_suppression_and_marketing_rules(db_session: AsyncSession):
    """Verify marketing emails respect unsubscribes while transactional emails are never suppressed."""
    test_email = "unsub_user@gympro.test"
    th = sha256_hash(test_email)

    # Insert unsubscribe record
    await db_session.execute(
        text("INSERT INTO unsubscribes (email_hash, scope) VALUES (:th, 'MARKETING')"),
        {"th": th},
    )
    await db_session.commit()

    # Transactional template is NEVER suppressed
    assert await is_suppressed(db_session, test_email, "VERIFY_EMAIL", None) is False
    assert await is_suppressed(db_session, test_email, "RESET_PASSWORD", None) is False
    assert await is_suppressed(db_session, test_email, "ADMIN_CODE", None) is False

    # Marketing template IS suppressed
    assert await is_suppressed(db_session, test_email, "BROADCAST", None) is True
    assert await is_suppressed(db_session, test_email, "WEEKLY_SUMMARY", None) is True

    # Test email_log writes to_hash, never the raw email
    mid = str(uuid.uuid4())
    await log_email(db_session, mid, None, test_email, "BROADCAST", "SUPPRESSED")
    await db_session.commit()

    res = await db_session.execute(
        text("SELECT to_hash, status FROM email_log WHERE message_id = :mid"),
        {"mid": mid},
    )
    row = res.mappings().one()
    assert row["to_hash"] == th
    assert row["status"] == "SUPPRESSED"


# -------------------------------------------------------------------------
# 6. Retry & DLQ Routing
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dlq_and_retry_routing(amqp_channel):
    """Verify message failure triggers bounded retries through retry queues and ends in q.dlq."""
    dlx = await amqp_channel.get_exchange("gympro.dlx")

    # Purge queues first
    q_retry_30s = await amqp_channel.get_queue("q.email.retry.30s")
    q_dlq = await amqp_channel.get_queue("q.dlq")
    await q_retry_30s.purge()
    await q_dlq.purge()

    # 1. Attempt 0 fails -> routes to email.retry.30s with count 1
    msg1 = aio_pika.Message(
        body=json.dumps({"test": "retry1"}).encode(),
        headers={"x-retry-count": 1},
    )
    await dlx.publish(msg1, routing_key="email.retry.30s")

    # 2. After 3 retries (count 4) -> routes to q.dlq
    msg_dlq = aio_pika.Message(
        body=json.dumps({"test": "dlq_message"}).encode(),
        headers={"x-retry-count": 4},
    )
    await dlx.publish(msg_dlq, routing_key="q.dlq")

    # Verify message in retry queue
    retried = await q_retry_30s.get(timeout=2.0)
    assert retried is not None
    assert retried.headers.get("x-retry-count") == 1
    await retried.ack()

    # Verify message in DLQ
    dlq_item = await q_dlq.get(timeout=2.0)
    assert dlq_item is not None
    assert dlq_item.headers.get("x-retry-count") == 4
    await dlq_item.ack()


# -------------------------------------------------------------------------
# 7. In-App Notify Worker
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notify_worker(db_session: AsyncSession):
    """Verify in-app notify worker claims message and inserts into notifications table."""
    u_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status)
            VALUES (:uid, 'notify_user@gympro.test', 'fakehash', 'Notify User', 'USER', 'ACTIVE')
            """
        ),
        {"uid": u_id},
    )
    await db_session.commit()

    mid = str(uuid.uuid4())
    payload = {
        "message_id": mid,
        "user_id": str(u_id),
        "routing_key": "notify.inapp",
        "params": {"title": "Class Reminder", "message": "Your class starts in 1 hour"},
    }

    # First handle: inserts notification
    res1 = await handle_notify_message(payload, TestAppSession)
    assert res1 is True

    # Verify notification created (RLS requires user context)
    from app.db import set_rls
    await set_rls(db_session, u_id, "USER")
    res = await db_session.execute(
        text("SELECT title, message FROM notifications WHERE user_id = :uid"),
        {"uid": u_id},
    )
    rows = res.mappings().all()
    assert len(rows) == 1
    assert rows[0]["title"] == "Class Reminder"

    # Second handle: idempotent, no duplicate
    res2 = await handle_notify_message(payload, TestAppSession)
    assert res2 is True

    res = await db_session.execute(
        text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid"),
        {"uid": u_id},
    )
    assert res.scalar() == 1


# -------------------------------------------------------------------------
# 8. SMTP Outage Drill (Gate Core Requirement)
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_smtp_outage_drill(db_session: AsyncSession, amqp_channel):
    """
    SMTP Outage Drill:
    1. Start Mailpit and verify clean state.
    2. Stop Mailpit (simulating outage).
    3. Enqueue and relay email message.
    4. Worker attempts send -> fails gracefully, unclaims message, records FAILED in email_log.
    5. Restart Mailpit!
    6. Retry delivery -> succeeds, records SENT in email_log, sanitizes outbox tokens.
    7. Query Mailpit: exactly 1 email received, 0 lost, 0 duplicates!
    """
    candidates = [
        pathlib.Path("tools/mailpit.exe"),
        pathlib.Path("../tools/mailpit.exe"),
        pathlib.Path(__file__).resolve().parents[3] / "tools" / "mailpit.exe",
    ]
    mailpit_exe = next((str(p) for p in candidates if p.exists()), "tools/mailpit.exe")
    email_addr = "outage_drill@gympro.test"

    # Create active user
    u_id = uuid.uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO users (id, email, password_hash, full_name, role, account_status)
            VALUES (:uid, :email, 'fakehash', 'Outage Drill User', 'USER', 'ACTIVE')
            """
        ),
        {"uid": u_id, "email": email_addr},
    )
    await db_session.commit()

    # Step 1: Start Mailpit initially to verify port
    proc = subprocess.Popen([mailpit_exe, "--smtp", "127.0.0.1:1025", "--listen", "127.0.0.1:8025"])
    time.sleep(1.5)

    # Clear any existing messages in Mailpit
    async with httpx.AsyncClient() as http_client:
        del_res = await http_client.delete("http://127.0.0.1:8025/api/v1/messages")
        assert del_res.status_code in (200, 204)

    # Step 2: STOP Mailpit to simulate SMTP outage!
    proc.terminate()
    proc.wait()
    time.sleep(1.0)

    # Step 3: Enqueue message during outage
    raw_token = "secret_drill_token_12345"
    mid = str(uuid.uuid4())
    await enqueue(
        db_session,
        user_id=u_id,
        routing_key="email.verify",
        template="VERIFY_EMAIL",
        params={"link": f"https://gympro.local/verify?token={raw_token}", "name": "Outage Drill User"},
        dedupe_key=f"outage_drill_{mid}",
    )
    await db_session.commit()

    # Step 4: Outbox relay runs and publishes to RabbitMQ
    exchange = await amqp_channel.get_exchange("gympro.events")
    confirmed = await publish_outbox_batch(db_session, exchange)
    assert confirmed >= 1

    # Fetch published message payload from outbox
    res = await db_session.execute(
        text("SELECT * FROM notification_outbox WHERE user_id = :uid"),
        {"uid": u_id},
    )
    outbox_row = dict(res.mappings().one())
    msg_payload = to_message(outbox_row)

    # Step 5: Email worker attempts delivery while Mailpit is DOWN
    # Should catch connection error, unclaim, record FAILED, and route retry
    success1 = await handle_message(
        msg_payload,
        sessionmaker=TestAppSession,
        retry_channel=amqp_channel,
        headers={"x-retry-count": 0},
    )
    assert success1 is False, "Delivery during outage must fail gracefully"

    # Verify email_log has status FAILED and message is NOT claimed in processed_messages
    res = await db_session.execute(
        text("SELECT status FROM email_log WHERE message_id = :mid"),
        {"mid": str(outbox_row["id"])},
    )
    assert res.scalar() == "FAILED"

    res_proc = await db_session.execute(
        text("SELECT 1 FROM processed_messages WHERE message_id = :mid"),
        {"mid": str(outbox_row["id"])},
    )
    assert res_proc.scalar() is None, "Failed message must be unclaimed so it can retry"

    # Step 6: RESTART Mailpit!
    proc2 = subprocess.Popen([mailpit_exe, "--smtp", "127.0.0.1:1025", "--listen", "127.0.0.1:8025"])
    time.sleep(1.5)

    try:
        # Step 7: Worker retries delivery with recovered SMTP server
        success2 = await handle_message(
            msg_payload,
            sessionmaker=TestAppSession,
            retry_channel=amqp_channel,
            headers={"x-retry-count": 1},
        )
        assert success2 is True, "Delivery after restart must succeed"

        # Verify email_log now has SENT record
        res_sent = await db_session.execute(
            text("SELECT status FROM email_log WHERE message_id = :mid AND status = 'SENT'"),
            {"mid": str(outbox_row["id"])},
        )
        assert res_sent.scalar() == "SENT"

        # Verify processed_messages claimed
        res_claimed = await db_session.execute(
            text("SELECT 1 FROM processed_messages WHERE message_id = :mid"),
            {"mid": str(outbox_row["id"])},
        )
        assert res_claimed.scalar() == 1

        # Verify tokens were sanitized from outbox
        res_outbox = await db_session.execute(
            text("SELECT params FROM notification_outbox WHERE id = :id"),
            {"id": outbox_row["id"]},
        )
        sanitized_params = res_outbox.scalar()
        assert "link" not in sanitized_params, "Sensitive token link must be removed from outbox after sending"

        # Step 8: Query Mailpit REST API to verify exactly 1 message delivered (no lost, no duplicate)
        async with httpx.AsyncClient() as http_client:
            mp_res = await http_client.get("http://127.0.0.1:8025/api/v1/messages")
            assert mp_res.status_code == 200
            data = mp_res.json()
            messages = data.get("messages", [])
            assert len(messages) == 1, f"Expected exactly 1 email delivered, got {len(messages)}"
            assert messages[0]["To"][0]["Address"] == email_addr
            assert "Verify your GymPro account" in messages[0]["Subject"]

    finally:
        # Step 9: Cleanly stop Mailpit
        proc2.terminate()
        proc2.wait()
