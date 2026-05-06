"""Database configuration — PLATFORM layer."""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

DATABASE_URL = "postgresql+asyncpg://user:password@localhost/orders_db"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession)


class DatabaseConfig:
    """Platform-level database configuration and session factory."""

    def __init__(self, url: str = DATABASE_URL) -> None:
        self.engine = create_async_engine(url, echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession)

    async def get_session(self) -> AsyncSession:
        async with self.session_factory() as session:
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
