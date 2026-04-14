import unittest
from datetime import datetime

from formatter import DigestItem, render_digest, render_digest_chunks, split_for_discord


class FormatterTests(unittest.TestCase):
    def test_render_digest_includes_counts_and_links(self) -> None:
        digest = render_digest(
            [
                DigestItem(
                    message_id="1",
                    channel_name="support",
                    author_name="alice",
                    original_text="need help",
                    translated_zh="需要帮助",
                    category="Problem",
                    has_reply=True,
                    solved=False,
                    known_status="unknown",
                    message_url="https://discord.com/channels/1/2/3",
                    created_at_text="03-27 10:00",
                    has_attachments=True,
                ),
                DigestItem(
                    message_id="2",
                    channel_name="showcase",
                    author_name="bob",
                    original_text="look at this",
                    translated_zh="看看这个",
                    category="UGC",
                ),
            ],
            datetime(2026, 3, 27, 10, 0),
        )

        self.assertIn("总计：2", digest)
        self.assertIn("Problem：1", digest)
        self.assertIn("UGC：1", digest)
        self.assertIn("链接：https://discord.com/channels/1/2/3", digest)
        self.assertIn("03-27 10:00", digest)
        self.assertIn("知识库：🆕 未知晓", digest)
        self.assertIn("附件：有", digest)

    def test_render_digest_forum_item_shows_source_and_title(self) -> None:
        digest = render_digest(
            [
                DigestItem(
                    message_id="forum-topic:123",
                    channel_name="forum-c5",
                    author_name="alice",
                    original_text="help needed with product",
                    translated_zh="产品需要帮助",
                    category="Problem",
                    known_status="unknown",
                    source_label="Forum",
                    thread_title="Installation issue",
                    message_url="https://community.example.com/t/topic/123",
                    created_at_text="03-27 10:00",
                )
            ],
            datetime(2026, 3, 27, 10, 0),
        )

        self.assertIn("[Forum] #forum-c5 | alice | 03-27 10:00", digest)
        self.assertIn("标题：Installation issue", digest)
        self.assertIn("链接：https://community.example.com/t/topic/123", digest)

    def test_render_digest_chunks_preserves_category_headers(self) -> None:
        chunks = render_digest_chunks(
            [
                DigestItem(
                    message_id="1",
                    channel_name="support",
                    author_name="alice",
                    original_text="need help",
                    translated_zh="需要帮助",
                    category="Problem",
                ),
                DigestItem(
                    message_id="2",
                    channel_name="support",
                    author_name="bob",
                    original_text="more info",
                    translated_zh="更多信息",
                    category="Problem",
                ),
            ],
            datetime(2026, 3, 27, 10, 0),
            limit=120,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk.text.startswith("========== [10:00") for chunk in chunks))
        self.assertIn(("1",), [chunk.message_ids for chunk in chunks])
        self.assertIn(("2",), [chunk.message_ids for chunk in chunks])

    def test_render_digest_chunks_tracks_message_ids_for_split_item(self) -> None:
        chunks = render_digest_chunks(
            [
                DigestItem(
                    message_id="1",
                    channel_name="support",
                    author_name="alice",
                    original_text="x" * 200,
                    translated_zh="需要帮助",
                    category="Problem",
                )
            ],
            datetime(2026, 3, 27, 10, 0),
            limit=120,
        )

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[-1].message_ids, ("1",))
        self.assertTrue(all(len(chunk.text) <= 120 for chunk in chunks))

    def test_split_for_discord_respects_limit(self) -> None:
        text = "\n".join(["x" * 40 for _ in range(5)])
        chunks = split_for_discord(text, limit=50)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 50 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
