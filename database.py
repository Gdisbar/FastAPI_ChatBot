from sqlalchemy.ext.asyncio import (
    create_async_engine, async_sessionmaker, AsyncSession,
)
from sqlalchemy.orm import DeclarativeBase

# aiosqlite driver = async SQLite
SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///./chatbot.db"

engine = create_async_engine(SQLALCHEMY_DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency. NOTE: do NOT use this for streaming endpoints —
    the session is closed when the route function returns, BEFORE the
    stream finishes. For streaming, manage the session inside the generator."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Create tables on startup (use Alembic in prod)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)