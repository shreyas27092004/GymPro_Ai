import uuid
from datetime import datetime
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import set_rls


@pytest.mark.asyncio
async def test_role_change_trigger_blocks_self_promotion(
    db_session: AsyncSession, seed_session: AsyncSession
):
    """Verify role-change trigger blocks self-promotion to TRAINER or ADMIN without approved role request."""
    # 1. Attempt direct insert with role TRAINER as gympro_app -> must fail
    async with db_session.begin():
        with pytest.raises(DBAPIError) as exc_info:
            await db_session.execute(
                text(
                    "INSERT INTO users (email, password_hash, full_name, role) "
                    "VALUES ('trainer_bad@gympro.test', 'hash', 'Bad Trainer', 'TRAINER')"
                )
            )
        assert "requires an approved role_request" in str(exc_info.value)

    # 2. Attempt direct insert with role ADMIN as gympro_app -> must fail
    async with db_session.begin():
        with pytest.raises(DBAPIError) as exc_info:
            await db_session.execute(
                text(
                    "INSERT INTO users (email, password_hash, full_name, role) "
                    "VALUES ('admin_bad@gympro.test', 'hash', 'Bad Admin', 'ADMIN')"
                )
            )
        assert "requires an approved role_request" in str(exc_info.value)

    # 3. Insert normal USER as gympro_app -> must succeed
    user_id = uuid.uuid4()
    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role) "
                "VALUES (:id, 'member@gympro.test', 'hash', 'Member User', 'USER')"
            ),
            {"id": user_id},
        )

    # 4. Attempt to self-promote to ADMIN without role_request -> must fail
    async with db_session.begin():
        with pytest.raises(DBAPIError) as exc_info:
            await db_session.execute(
                text("UPDATE users SET role = 'ADMIN' WHERE id = :id"),
                {"id": user_id},
            )
        assert "requires an approved role_request" in str(exc_info.value)

    # 5. gympro_seed role CAN insert/set TRAINER or ADMIN
    seed_trainer_id = uuid.uuid4()
    async with seed_session.begin():
        await seed_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role) "
                "VALUES (:id, 'seed_trainer@gympro.test', 'hash', 'Seed Trainer', 'TRAINER')"
            ),
            {"id": seed_trainer_id},
        )
    # Verify seed trainer was created
    async with db_session.begin():
        res = await db_session.execute(
            text("SELECT role FROM users WHERE id = :id"),
            {"id": seed_trainer_id},
        )
        assert res.scalar_one() == "TRAINER"

    # 6. If an approved role_request exists (within 5 minutes), role update as gympro_app succeeds
    req_id = uuid.uuid4()
    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO role_requests (id, user_id, requested_role, status, decided_at, expires_at) "
                "VALUES (:id, :user_id, 'TRAINER', 'APPROVED', NOW(), NOW() + INTERVAL '1 day')"
            ),
            {"id": req_id, "user_id": user_id},
        )
        await db_session.execute(
            text("UPDATE users SET role = 'TRAINER' WHERE id = :id"),
            {"id": user_id},
        )
        role = (
            await db_session.execute(
                text("SELECT role FROM users WHERE id = :id"),
                {"id": user_id},
            )
        ).scalar_one()
        assert role == "TRAINER"


@pytest.mark.asyncio
async def test_rls_blocks_cross_user_reads_with_gympro_app_role(db_session: AsyncSession):
    """Verify RLS blocks cross-user reads for gympro_app connections."""
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    # Create users
    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role) VALUES "
                "(:a, 'user_a@gympro.test', 'hash', 'User A', 'USER'), "
                "(:b, 'user_b@gympro.test', 'hash', 'User B', 'USER')"
            ),
            {"a": user_a_id, "b": user_b_id},
        )

    # Insert user_a profile under user_a context
    async with db_session.begin():
        await set_rls(db_session, str(user_a_id), "USER")
        await db_session.execute(
            text(
                "INSERT INTO member_profiles (user_id, date_of_birth, height_cm, weight_kg) "
                "VALUES (:id, '1995-05-15', 175.0, 72.0)"
            ),
            {"id": user_a_id},
        )

    # 1. User B context: querying member_profiles cannot read User A's data
    async with db_session.begin():
        await set_rls(db_session, str(user_b_id), "USER")
        res_all = await db_session.execute(text("SELECT user_id FROM member_profiles"))
        rows_all = res_all.scalars().all()
        assert len(rows_all) == 0

        res_a = await db_session.execute(
            text("SELECT user_id FROM member_profiles WHERE user_id = :id"),
            {"id": user_a_id},
        )
        assert res_a.scalar_one_or_none() is None

    # 2. User A context: querying member_profiles returns User A's data
    async with db_session.begin():
        await set_rls(db_session, str(user_a_id), "USER")
        res_a = await db_session.execute(
            text("SELECT user_id, height_cm FROM member_profiles WHERE user_id = :id"),
            {"id": user_a_id},
        )
        row = res_a.first()
        assert row is not None
        assert row[0] == user_a_id
        assert float(row[1]) == 175.0


@pytest.mark.asyncio
async def test_exclusion_constraint_blocks_trainer_overlap(
    db_session: AsyncSession, seed_session: AsyncSession
):
    """Verify exclusion constraint prevents a trainer from teaching overlapping non-cancelled classes."""
    trainer_id = uuid.uuid4()
    async with seed_session.begin():
        await seed_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role) "
                "VALUES (:id, 'trainer_overlap@gympro.test', 'hash', 'Overlap Trainer', 'TRAINER')"
            ),
            {"id": trainer_id},
        )

    async with db_session.begin():
        await db_session.execute(
            text("INSERT INTO trainer_profiles (trainer_id) VALUES (:id)"),
            {"id": trainer_id},
        )

    class1_id = uuid.uuid4()
    class2_id = uuid.uuid4()

    # Insert class 1: 10:00 to 11:00
    start1 = datetime(2026, 10, 20, 10, 0, 0)
    end1 = datetime(2026, 10, 20, 11, 0, 0)
    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO fitness_classes (id, title, trainer_id, category, capacity, start_time, end_time, status) "
                "VALUES (:id, 'Class 1', :trainer_id, 'HIIT', 15, :start, :end, 'SCHEDULED')"
            ),
            {"id": class1_id, "trainer_id": trainer_id, "start": start1, "end": end1},
        )

    # Attempt to insert class 2 with overlapping window: 10:30 to 11:30 for same trainer -> must fail
    start2 = datetime(2026, 10, 20, 10, 30, 0)
    end2 = datetime(2026, 10, 20, 11, 30, 0)
    async with db_session.begin():
        with pytest.raises(IntegrityError) as exc_info:
            await db_session.execute(
                text(
                    "INSERT INTO fitness_classes (id, title, trainer_id, category, capacity, start_time, end_time, status) "
                    "VALUES (:id, 'Class 2', :trainer_id, 'HIIT', 15, :start, :end, 'SCHEDULED')"
                ),
                {"id": class2_id, "trainer_id": trainer_id, "start": start2, "end": end2},
            )
        assert "excl_trainer_overlap" in str(exc_info.value).lower()

    # If class 1 is CANCELLED, inserting overlapping class 2 succeeds
    async with db_session.begin():
        await db_session.execute(
            text("UPDATE fitness_classes SET status = 'CANCELLED' WHERE id = :id"),
            {"id": class1_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO fitness_classes (id, title, trainer_id, category, capacity, start_time, end_time, status) "
                "VALUES (:id, 'Class 2', :trainer_id, 'HIIT', 15, :start, :end, 'SCHEDULED')"
            ),
            {"id": class2_id, "trainer_id": trainer_id, "start": start2, "end": end2},
        )
        c2_status = (
            await db_session.execute(
                text("SELECT status FROM fitness_classes WHERE id = :id"),
                {"id": class2_id},
            )
        ).scalar_one()
        assert c2_status == "SCHEDULED"


@pytest.mark.asyncio
async def test_one_active_membership_per_user(db_session: AsyncSession):
    """Verify unique constraint allows only one ACTIVE membership per user."""
    user_id = uuid.uuid4()
    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role) "
                "VALUES (:id, 'membership_user@gympro.test', 'hash', 'Member User', 'USER')"
            ),
            {"id": user_id},
        )

    # Insert first active membership
    m1_id = uuid.uuid4()
    m2_id = uuid.uuid4()
    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date) "
                "VALUES (:id, :uid, 'SILVER', 'ACTIVE', 'MONTHLY', 999.00, CURRENT_DATE, CURRENT_DATE + 30)"
            ),
            {"id": m1_id, "uid": user_id},
        )

    # Attempt to insert second active membership -> must fail
    async with db_session.begin():
        with pytest.raises(IntegrityError) as exc_info:
            await db_session.execute(
                text(
                    "INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date) "
                    "VALUES (:id, :uid, 'GOLD', 'ACTIVE', 'MONTHLY', 1999.00, CURRENT_DATE, CURRENT_DATE + 30)"
                ),
                {"id": m2_id, "uid": user_id},
            )
        assert "uq_one_active_membership" in str(exc_info.value).lower()

    # Transition m1 to REPLACED; inserting m2 as ACTIVE now succeeds
    async with db_session.begin():
        await db_session.execute(
            text("UPDATE memberships SET status = 'REPLACED' WHERE id = :id"),
            {"id": m1_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date) "
                "VALUES (:id, :uid, 'GOLD', 'ACTIVE', 'MONTHLY', 1999.00, CURRENT_DATE, CURRENT_DATE + 30)"
            ),
            {"id": m2_id, "uid": user_id},
        )
        m2_status = (
            await db_session.execute(
                text("SELECT status FROM memberships WHERE id = :id"),
                {"id": m2_id},
            )
        ).scalar_one()
        assert m2_status == "ACTIVE"


@pytest.mark.asyncio
async def test_one_active_booking_per_user_per_class(
    db_session: AsyncSession, seed_session: AsyncSession
):
    """Verify unique constraint allows only one ACTIVE (CONFIRMED or WAITLISTED) booking per user per class."""
    user_id = uuid.uuid4()
    trainer_id = uuid.uuid4()
    class_id = uuid.uuid4()

    async with seed_session.begin():
        await seed_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role) "
                "VALUES (:id, 'booking_trainer@gympro.test', 'hash', 'Booking Trainer', 'TRAINER')"
            ),
            {"id": trainer_id},
        )

    async with db_session.begin():
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, role) "
                "VALUES (:id, 'booking_user@gympro.test', 'hash', 'Booking User', 'USER')"
            ),
            {"id": user_id},
        )
        await db_session.execute(
            text("INSERT INTO trainer_profiles (trainer_id) VALUES (:id)"),
            {"id": trainer_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO fitness_classes (id, title, trainer_id, category, capacity, start_time, end_time, status) "
                "VALUES (:id, 'Yoga Flow', :trainer_id, 'YOGA', 10, NOW() + INTERVAL '1 day', NOW() + INTERVAL '1 day 1 hour', 'SCHEDULED')"
            ),
            {"id": class_id, "trainer_id": trainer_id},
        )

    b1_id = uuid.uuid4()
    b2_id = uuid.uuid4()

    # 1. Insert first confirmed booking under user_id RLS context
    async with db_session.begin():
        await set_rls(db_session, str(user_id), "USER")
        await db_session.execute(
            text(
                "INSERT INTO class_bookings (id, user_id, class_id, status) "
                "VALUES (:id, :uid, :cid, 'CONFIRMED')"
            ),
            {"id": b1_id, "uid": user_id, "cid": class_id},
        )

    # 2. Attempt duplicate booking with WAITLISTED -> must fail
    async with db_session.begin():
        await set_rls(db_session, str(user_id), "USER")
        with pytest.raises(IntegrityError) as exc_info:
            await db_session.execute(
                text(
                    "INSERT INTO class_bookings (id, user_id, class_id, status) "
                    "VALUES (:id, :uid, :cid, 'WAITLISTED')"
                ),
                {"id": b2_id, "uid": user_id, "cid": class_id},
            )
        assert "uq_active_booking" in str(exc_info.value).lower()

    # 3. Attempt duplicate booking with CONFIRMED -> must fail
    async with db_session.begin():
        await set_rls(db_session, str(user_id), "USER")
        with pytest.raises(IntegrityError) as exc_info:
            await db_session.execute(
                text(
                    "INSERT INTO class_bookings (id, user_id, class_id, status) "
                    "VALUES (:id, :uid, :cid, 'CONFIRMED')"
                ),
                {"id": b2_id, "uid": user_id, "cid": class_id},
            )
        assert "uq_active_booking" in str(exc_info.value).lower()

    # 4. If booking 1 is CANCELLED, new booking succeeds
    async with db_session.begin():
        await set_rls(db_session, str(user_id), "USER")
        await db_session.execute(
            text("UPDATE class_bookings SET status = 'CANCELLED' WHERE id = :id"),
            {"id": b1_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO class_bookings (id, user_id, class_id, status) "
                "VALUES (:id, :uid, :cid, 'CONFIRMED')"
            ),
            {"id": b2_id, "uid": user_id, "cid": class_id},
        )
        b2_status = (
            await db_session.execute(
                text("SELECT status FROM class_bookings WHERE id = :id"),
                {"id": b2_id},
            )
        ).scalar_one()
        assert b2_status == "CONFIRMED"
