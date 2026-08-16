from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepo:
    """Repository dasar: semua query DB berada di layer ini."""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def add(self, obj):
        self.s.add(obj)
        await self.s.flush()
        return obj

    async def delete(self, obj) -> None:
        await self.s.delete(obj)
        await self.s.flush()
