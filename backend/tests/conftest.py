import os
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.main import app
from app.settings import settings

# Frozen clock per Spec 0.2 rule 5: 2026-10-16T18:05:00+05:30 (Friday)
FROZEN_TIME_STR = "2026-10-16T18:05:00+05:30"
FROZEN_TIME = datetime.fromisoformat(FROZEN_TIME_STR)

from sqlalchemy.pool import NullPool

test_app_engine = create_async_engine(
    settings.test_database_url,
    echo=False,
    future=True,
    poolclass=NullPool,
)

test_seed_engine = create_async_engine(
    settings.test_seed_database_url,
    echo=False,
    future=True,
    poolclass=NullPool,
)

superuser_engine = create_async_engine(
    settings.superuser_database_url,
    echo=False,
    future=True,
    poolclass=NullPool,
)

TestAppSession = async_sessionmaker(
    bind=test_app_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

TestSeedSession = async_sessionmaker(
    bind=test_seed_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="session")
def frozen_clock() -> datetime:
    """Returns the frozen test clock datetime."""
    return FROZEN_TIME


@pytest.fixture(scope="session")
def frozen_clock_str() -> str:
    """Returns the frozen test clock ISO string."""
    return FROZEN_TIME_STR


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async test client for FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    """Truncates dynamic tables in gympro_test before each test using superuser connection."""
    tables = [
        "payments", "payment_events", "class_bookings", "pending_actions", "action_bundles",
        "fitness_classes", "class_series", "trainer_availability", "trainer_time_off", "trainer_reviews",
        "trainer_applications", "trainer_profiles", "member_intake_versions", "member_profiles",
        "daily_health_logs", "nutrition_plans", "trial_grants", "memberships", "issue_reports",
        "notifications", "notification_outbox", "notification_prefs", "unsubscribes", "feedback",
        "processed_messages", "email_log", "staff_invites", "email_verifications", "password_resets",
        "refresh_tokens", "role_requests", "agent_tool_calls", "agent_runs", "users",
    ]
    try:
        async with superuser_engine.begin() as conn:
            await conn.execute(text("TRUNCATE " + ", ".join(tables) + " CASCADE;"))
    except Exception as e:
        # If superuser is unavailable in non-db tests, ignore
        pass
    yield


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async session connected as gympro_app with NOBYPASSRLS."""
    async with TestAppSession() as session:
        yield session


@pytest_asyncio.fixture
async def seed_session() -> AsyncGenerator[AsyncSession, None]:
    """Async session connected as gympro_seed."""
    async with TestSeedSession() as session:
        yield session
