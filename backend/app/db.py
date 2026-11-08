
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.models import Base


engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
