# app/seed_admin.py
import argparse
import asyncio
import concurrent.futures
import getpass
import sys
import uuid
import asyncpg
from .auth.security import hash_password
from .settings import settings


async def _seed_first_admin_async(
    email: str,
    password: str,
    full_name: str,
    db_url: str,
) -> uuid.UUID:
    clean_url = db_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(clean_url)
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id, email FROM users WHERE role = 'ADMIN' AND account_status = 'ACTIVE' AND deleted_at IS NULL LIMIT 1"
            )
            if row:
                raise RuntimeError(f"Active admin already exists ({row['email']}). Seed bootstrap is disabled.")

            pw_hash = hash_password(password)
            admin_id = uuid.uuid4()

            # gympro_seed role bypasses guard_role_change trigger per section 6.2 DDL
            await conn.execute(
                """
                INSERT INTO users (id, email, password_hash, full_name, role, account_status, email_verified_at)
                VALUES ($1, $2, $3, $4, 'ADMIN', 'ACTIVE', NOW())
                """,
                admin_id,
                email.strip().lower(),
                pw_hash,
                full_name,
            )

            await conn.execute(
                """
                INSERT INTO audit_log (actor_id, action, entity, entity_id, details)
                VALUES ($1, 'ADMIN_SEEDED', 'users', $2, '{"method": "CLI_SEED"}'::jsonb)
                """,
                admin_id,
                admin_id,
            )
            return admin_id
    finally:
        await conn.close()


def seed_first_admin(
    email: str,
    password: str,
    full_name: str = "GymPro Administrator",
    use_test_db: bool = False,
) -> uuid.UUID:
    """
    Connects as gympro_seed to create the first system administrator.
    Refuses to execute if any active administrator already exists.
    """
    db_url = settings.test_seed_database_url if use_test_db else settings.seed_database_url
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            lambda: asyncio.run(_seed_first_admin_async(email, password, full_name, db_url))
        )
        return future.result()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap the first GymPro system administrator.")
    parser.add_argument("--email", required=True, help="Administrator email address")
    parser.add_argument("--name", default="System Administrator", help="Administrator full name")
    parser.add_argument("--password", default=None, help="Admin password (optional; prompted securely if omitted)")
    parser.add_argument("--test-db", action="store_true", help="Seed into test database (gympro_test)")

    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("Enter password for initial administrator (10-72 chars): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Error: Passwords do not match.", file=sys.stderr)
            sys.exit(1)

    try:
        admin_id = seed_first_admin(args.email, password, args.name, use_test_db=args.test_db)
        print(f"Success: Initial administrator seeded successfully! (ID: {admin_id}, Email: {args.email})")
    except Exception as e:
        print(f"Error seeding admin: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
