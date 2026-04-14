import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from dedup import DedupStore


class DedupStoreTests(unittest.TestCase):
    def test_mark_sent_and_filter_unsent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DedupStore(db_path=f"{temp_dir}/sent_messages.db")
            store.initialize()
            store.mark_sent(["1", "2"], batch_id="batch-1")

            self.assertTrue(store.has_sent("1"))
            self.assertEqual(store.filter_unsent(["1", "2", "3"]), {"3"})

    def test_cleanup_forum_entries_older_than_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DedupStore(db_path=f"{temp_dir}/sent_messages.db")
            store.initialize()
            now = datetime.now(timezone.utc)
            store.mark_sent(["forum-topic:old"], sent_at=now - timedelta(hours=25), batch_id="batch-old")
            store.mark_sent(["forum-topic:recent"], sent_at=now - timedelta(hours=1), batch_id="batch-recent")
            store.mark_sent(["discord-1"], sent_at=now - timedelta(hours=25), batch_id="batch-discord")

            removed = store.cleanup_forum_entries_older_than(hours=24, now=now)

            self.assertEqual(removed, 1)
            self.assertFalse(store.has_sent("forum-topic:old"))
            self.assertTrue(store.has_sent("forum-topic:recent"))
            self.assertTrue(store.has_sent("discord-1"))


if __name__ == "__main__":
    unittest.main()
