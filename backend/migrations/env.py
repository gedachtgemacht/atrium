import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from atrium import models  # noqa: F401  (registers tables)
from atrium.config import get_settings
from atrium.db import Base

target_metadata = Base.metadata


def run_sync(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async():
    url = context.config.attributes.get("url") or get_settings().database_url
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(run_sync)
    await engine.dispose()


asyncio.run(run_async())
