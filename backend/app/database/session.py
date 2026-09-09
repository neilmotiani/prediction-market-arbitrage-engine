from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.entities import Base


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        # MVP bootstrap, deliberately single-worker. See architecture for migration policy.
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()
