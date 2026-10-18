# backend/scripts/fix_seeds.py
import asyncio
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db import AsyncSessionLocal, set_rls
from sqlalchemy import text
from app.auth.security import hash_password

async def main():
    pw_hash = hash_password('Password123!')
    member_id = '44444444-4444-4444-4444-444444444444'

    async with AsyncSessionLocal() as session:
        # 1. Update trainers
        await session.execute(
            text("UPDATE users SET password_hash = :h WHERE role = 'TRAINER'"),
            {'h': pw_hash}
        )
        print("Updated trainer passwords to Password123!")

        # 2. Check or insert Alex Rivera (demo active member)
        res = await session.execute(text("SELECT id FROM users WHERE email = 'member.alex@gympro.local'"))
        row = res.fetchone()
        if not row:
            await session.execute(
                text("""
                    INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at, phone)
                    VALUES ('44444444-4444-4444-4444-444444444444', 'member.alex@gympro.local', :h, 'Alex Rivera', 'USER', 'ACTIVE', '2026-10-01 10:00:00+05:30', '+15555550199')
                    ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash
                """),
                {'h': pw_hash}
            )
            print("Created member.alex@gympro.local.")

            # Create active gold membership
            await session.execute(
                text("""
                    INSERT INTO memberships (id, user_id, plan_code, status, billing_cycle, price_paid, start_date, end_date, auto_renew)
                    VALUES ('55555555-5555-5555-5555-555555555555', '44444444-4444-4444-4444-444444444444', 'GOLD', 'ACTIVE', 'MONTHLY', 1999.00, '2026-10-01', '2026-11-01', TRUE)
                    ON CONFLICT (id) DO NOTHING
                """)
            )

            # Set RLS context for member to insert member profile
            await set_rls(session, member_id, 'USER')

            # Create member profile with health consent
            await session.execute(
                text("""
                    INSERT INTO member_profiles (user_id, date_of_birth, gender, height_cm, weight_kg, experience_level, goal, health_data_consent_at)
                    VALUES ('44444444-4444-4444-4444-444444444444', '1995-05-15', 'MALE', 175.0, 72.0, 'INTERMEDIATE', 'MUSCLE_GAIN', NOW())
                    ON CONFLICT (user_id) DO UPDATE SET health_data_consent_at = NOW()
                """)
            )
            print("Created membership & member_profiles for member.alex@gympro.local.")
        else:
            await session.execute(
                text("UPDATE users SET password_hash = :h WHERE email = 'member.alex@gympro.local'"),
                {'h': pw_hash}
            )
            print("Updated member.alex@gympro.local password.")

        await session.commit()
        print("All seeds updated successfully!")

if __name__ == '__main__':
    asyncio.run(main())
