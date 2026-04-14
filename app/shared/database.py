from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.shared.config import get_settings


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(get_settings().DATABASE_URL)
    return async_sessionmaker(engine, expire_on_commit=False)
