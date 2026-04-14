from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_DB_PATH = "/data/sent_messages.db"


class DedupStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sent_messages (
                    message_id TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL,
                    batch_id TEXT
                )
                """
            )
            connection.commit()

    def has_sent(self, message_id: int | str) -> bool:
        with closing(self._connect()) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                "SELECT 1 FROM sent_messages WHERE message_id = ? LIMIT 1",
                (str(message_id),),
            )
            return cursor.fetchone() is not None

    def filter_unsent(self, message_ids: Iterable[int | str]) -> set[str]:
        normalized_ids = {str(message_id) for message_id in message_ids}
        if not normalized_ids:
            return set()

        placeholders = ",".join("?" for _ in normalized_ids)
        query = f"SELECT message_id FROM sent_messages WHERE message_id IN ({placeholders})"

        with closing(self._connect()) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(query, tuple(normalized_ids))
            sent_ids = {row[0] for row in cursor.fetchall()}

        return normalized_ids - sent_ids

    def mark_sent(
        self,
        message_ids: Iterable[int | str],
        sent_at: datetime | None = None,
        batch_id: str | None = None,
    ) -> None:
        normalized_ids = [str(message_id) for message_id in message_ids]
        if not normalized_ids:
            return

        timestamp = (sent_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        rows = [(message_id, timestamp, batch_id) for message_id in normalized_ids]

        with closing(self._connect()) as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO sent_messages (message_id, sent_at, batch_id)
                VALUES (?, ?, ?)
                """,
                rows,
            )
            connection.commit()

    def cleanup_forum_entries_older_than(
        self,
        *,
        hours: int,
        now: datetime | None = None,
    ) -> int:
        threshold = (now or datetime.now(timezone.utc)).astimezone(timezone.utc) - timedelta(hours=hours)
        threshold_text = threshold.isoformat()

        with closing(self._connect()) as connection, closing(connection.cursor()) as cursor:
            cursor.execute(
                """
                DELETE FROM sent_messages
                WHERE message_id LIKE ?
                  AND sent_at < ?
                """,
                ("forum-topic:%", threshold_text),
            )
            deleted_rows = cursor.rowcount
            connection.commit()
        return deleted_rows

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection
