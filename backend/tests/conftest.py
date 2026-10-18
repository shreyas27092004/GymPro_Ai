import os
from collections.abc import AsyncGenerator
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.settings import settings

# Frozen clock per Spec 0.2 rule 5: 2026-10-16T18:05:00+05:30 (Friday)
FROZEN_TIME_STR = "2026-10-16T18:05:00+05:30"
FROZEN_TIME = datetime.fromisoformat(FROZEN_TIME_STR)


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
