# app/db.py
from collections.abc import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from .settings import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def set_rls(session: AsyncSession, user_id: str | None, role: str | None) -> None:
    """Set transaction-local RLS context."""
    if user_id:
        await session.execute(text(f"SET LOCAL app.user_id = '{user_id}'"))
    if role:
        await session.execute(text(f"SET LOCAL app.role = '{role}'"))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
