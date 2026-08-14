"""Feedback storage (Lesson 11.2: User Feedback Integration).

Collects explicit signals - thumbs up/down and, strongest of all, a human
correction - against a specific `turn_id`. Deliberately simple: one SQLite
table, no queueing, no training pipeline. This is the "Collect" step of the
lesson's 7-step feedback pipeline; Filter/Verify/Format/Train are future work
(see the README's "Növbəti addımlar" section) - a correction saved here is
already exactly the `{prompt, chosen, rejected}` shape once paired with the
original reply, it just isn't curated into a training set yet.
"""

import aiosqlite

from app.core.config import settings


class FeedbackStore:
    """Owns the aiosqlite connection for the lifetime of the app."""

    def __init__(self) -> None:
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> "FeedbackStore":
        settings.feedback_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(settings.feedback_file, check_same_thread=False)
        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                turn_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('up', 'down', 'correction')),
                advisor TEXT,
                text TEXT,
                original_reply TEXT,
                channel TEXT NOT NULL DEFAULT 'api',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        await self._conn.commit()
        return self

    async def add(
        self,
        *,
        turn_id: str,
        thread_id: str,
        kind: str,
        advisor: str | None = None,
        text: str | None = None,
        original_reply: str | None = None,
        channel: str = "api",
    ) -> int:
        assert self._conn is not None, "FeedbackStore.open() was not awaited"
        cursor = await self._conn.execute(
            """
            INSERT INTO feedback (turn_id, thread_id, kind, advisor, text, original_reply, channel)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (turn_id, thread_id, kind, advisor, text, original_reply, channel),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def stats(self) -> dict:
        """Counts by kind - enough to answer "is anyone unhappy" at a glance."""
        assert self._conn is not None, "FeedbackStore.open() was not awaited"
        cursor = await self._conn.execute("SELECT kind, COUNT(*) FROM feedback GROUP BY kind")
        rows = await cursor.fetchall()
        counts = {kind: count for kind, count in rows}
        return {
            "up": counts.get("up", 0),
            "down": counts.get("down", 0),
            "correction": counts.get("correction", 0),
            "total": sum(counts.values()),
        }

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
