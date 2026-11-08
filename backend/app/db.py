from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.models import Base


engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.run_sync(
            lambda sync: {
                column["name"] for column in inspect(sync).get_columns("jobs")
            }
        )
        if "execution_mode" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE jobs ADD COLUMN execution_mode VARCHAR NOT NULL DEFAULT 'unknown'"
                )
            )
        if "sample_id" not in columns:
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN sample_id VARCHAR"))
        if "filename" not in columns:
            await conn.execute(
                text(
                    "ALTER TABLE jobs ADD COLUMN filename VARCHAR NOT NULL DEFAULT 'install.sh'"
                )
            )
