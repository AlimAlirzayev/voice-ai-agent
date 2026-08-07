"""SQLite checkpointer - the agent's memory (Lesson 31).

LangGraph stores one checkpoint per thread_id, so a conversation survives a
server restart. `InMemorySaver` would lose it, which is why the demo uses a
file-backed saver instead.
"""

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.core.config import settings


class Checkpointer:
    """Owns the aiosqlite connection for the lifetime of the app."""

    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None
        self.saver: AsyncSqliteSaver | None = None

    async def open(self) -> AsyncSqliteSaver:
        settings.sqlite_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(
            settings.sqlite_file,
            check_same_thread=False,
        )
        self.saver = AsyncSqliteSaver(self._conn)
        await self.saver.setup()
        return self.saver

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self.saver = None
