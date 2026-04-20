from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings

# NullPool: every session opens its own connection. Avoids cross-event-loop
# pool issues (each pytest-asyncio test runs on a fresh loop and cached
# asyncpg connections bound to the old loop raise "Event loop is closed").
# In our scale (single case, bursty traffic), the cost of re-connecting is
# negligible; for production we'd swap to asyncpg's native pool.
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=NullPool,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
