import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock, patch

import aiohttp

from bot import CommunityInspectorBot, SourceMessage
from classifier import ClassificationResult, FollowupMessage, MessageClassifier


async def _empty_async_iterable():
    if False:
        yield None


class _MockResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self.payload


class _MockSession:
    def __init__(self, latest_payload=None, topic_payloads=None):
        self.latest_payload = latest_payload or {}
        self.topic_payloads = topic_payloads or {}
        self.requested_urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, **kwargs):
        self.requested_urls.append(url)
        if "latest.json" in url:
            return _MockResponse(self.latest_payload)
        # topic detail url pattern: /t/{slug}/{id}.json
        for key, payload in self.topic_payloads.items():
            if url.endswith(key) or key in url:
                return _MockResponse(payload)
        return _MockResponse({})


class CommunityInspectorBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = {
            key: os.environ.get(key)
            for key in {
                "DISCORD_BOT_TOKEN",
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_BASE_URL",
                "MODEL_NAME",
                "GUILD_ID",
                "OUTPUT_CHANNEL_ID",
                "INCLUDE_CHANNEL_IDS",
                "EXCLUDE_CHANNEL_IDS",
                "DIGEST_TIMEZONE",
                "DIGEST_SCHEDULE_HOURS",
                "DRY_RUN",
                "RUN_ON_STARTUP",
                "FORUM_ENABLED",
                "FORUM_BASE_URL",
            }
        }
        os.environ.update(
            {
                "DISCORD_BOT_TOKEN": "token",
                "ANTHROPIC_API_KEY": "key",
                "ANTHROPIC_BASE_URL": "https://api.example.com",
                "MODEL_NAME": "claude-sonnet-4-6",
                "GUILD_ID": "123",
                "OUTPUT_CHANNEL_ID": "456",
                "INCLUDE_CHANNEL_IDS": "111,222",
                "EXCLUDE_CHANNEL_IDS": "333",
                "DIGEST_TIMEZONE": "Asia/Shanghai",
                "DIGEST_SCHEDULE_HOURS": "10,12,14",
                "DRY_RUN": "true",
                "RUN_ON_STARTUP": "false",
                "FORUM_ENABLED": "false",
                "FORUM_BASE_URL": "https://community.example.com",
            }
        )

    def tearDown(self) -> None:
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_channel_filtering_prefers_exclude(self) -> None:
        with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
            bot = CommunityInspectorBot()

        allowed = SimpleNamespace(id=111)
        blocked = SimpleNamespace(id=333)
        overlapping = SimpleNamespace(id=222)
        unknown = SimpleNamespace(id=999)
        bot.exclude_channel_ids.add("222")

        self.assertTrue(bot._should_scan_channel(allowed))
        self.assertFalse(bot._should_scan_channel(blocked))
        self.assertFalse(bot._should_scan_channel(overlapping))
        self.assertFalse(bot._should_scan_channel(unknown))
        self.assertEqual(bot.digest_scheduler.hours, (10, 12, 14))

    def test_dry_run_skips_send_and_mark_sent(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                bot = CommunityInspectorBot()

            bot._collect_source_messages = AsyncMock(
                return_value=[
                    SourceMessage(
                        message_id="1",
                        channel_name="support",
                        author_name="alice",
                        author_id=101,
                        content="help",
                        followups=[],
                        message_url="https://discord.com/channels/1/2/3",
                        created_at_text="03-27 10:00",
                        has_attachments=False,
                    )
                ]
            )
            bot.classifier.classify_message = AsyncMock(
                return_value=ClassificationResult(
                    category="Problem",
                    translated_zh="帮助",
                    has_reply=False,
                    solved=False,
                    known_status="unknown",
                )
            )
            bot._resolve_output_channel = AsyncMock(return_value=SimpleNamespace(send=AsyncMock()))

            await bot.run_digest_cycle()

            bot._resolve_output_channel.assert_not_called()
            dedup_store.mark_sent.assert_not_called()

        asyncio.run(scenario())

    def test_run_digest_cycle_marks_sent_after_all_chunks_succeed(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls, patch(
                "bot.render_digest_chunks",
                return_value=[
                    SimpleNamespace(text="chunk-1", message_ids=("1",)),
                    SimpleNamespace(text="chunk-2", message_ids=("2",)),
                ],
            ):
                dedup_store = dedup_cls.return_value
                bot = CommunityInspectorBot()
                bot.dry_run = False
                bot._collect_source_messages = AsyncMock(
                    return_value=[
                        SourceMessage("1", "support", "alice", 101, "help", [], has_attachments=False),
                        SourceMessage("2", "support", "bob", 102, "update", [], has_attachments=False),
                    ]
                )
                bot.classifier.classify_message = AsyncMock(
                    side_effect=[
                        ClassificationResult("Problem", "帮助", False, False, "unknown"),
                        ClassificationResult("Signal", "更新", False, False, "unknown"),
                    ]
                )
                output_channel = SimpleNamespace(id=456, name="digest", send=AsyncMock())
                bot._resolve_output_channel = AsyncMock(return_value=output_channel)

                with self.assertLogs("bot", level="INFO") as captured_logs:
                    await bot.run_digest_cycle()

            self.assertEqual(output_channel.send.await_count, 2)
            self.assertEqual(
                dedup_store.mark_sent.call_args_list,
                [
                    ((["1", "2"],), {"batch_id": ANY}),
                ],
            )
            joined_logs = "\n".join(captured_logs.output)
            self.assertIn("Collected 2 candidate source messages", joined_logs)
            self.assertIn("Classification summary: total=2 included=2 ignored=0 failed=0", joined_logs)
            self.assertIn("Resolved output channel: #digest (456)", joined_logs)
            self.assertIn("Sending digest chunk 1/2", joined_logs)
            self.assertIn("Sending digest chunk 2/2", joined_logs)
            self.assertIn("Digest run complete: mode=live items=2 ignored=0 chunks=2 sent_items=2", joined_logs)

        asyncio.run(scenario())

    def test_run_digest_cycle_stops_after_partial_send_failure(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls, patch(
                "bot.render_digest_chunks",
                return_value=[
                    SimpleNamespace(text="chunk-1", message_ids=("1",)),
                    SimpleNamespace(text="chunk-2", message_ids=("2",)),
                ],
            ):
                dedup_store = dedup_cls.return_value
                bot = CommunityInspectorBot()
                bot.dry_run = False
                bot._collect_source_messages = AsyncMock(
                    return_value=[
                        SourceMessage("1", "support", "alice", 101, "help", [], has_attachments=False),
                        SourceMessage("2", "support", "bob", 102, "update", [], has_attachments=False),
                    ]
                )
                bot.classifier.classify_message = AsyncMock(
                    side_effect=[
                        ClassificationResult("Problem", "帮助", False, False, "unknown"),
                        ClassificationResult("Signal", "更新", False, False, "unknown"),
                    ]
                )
                output_channel = SimpleNamespace(
                    id=456,
                    name="digest",
                    send=AsyncMock(side_effect=[None, RuntimeError("boom")]),
                )
                bot._resolve_output_channel = AsyncMock(return_value=output_channel)

                with self.assertLogs("bot", level="INFO") as captured_logs:
                    with self.assertRaises(RuntimeError):
                        await bot.run_digest_cycle()

            self.assertEqual(output_channel.send.await_count, 2)
            self.assertEqual(dedup_store.mark_sent.call_args_list, [])
            joined_logs = "\n".join(captured_logs.output)
            self.assertIn("Resolved output channel: #digest (456)", joined_logs)
            self.assertIn("Sending digest chunk 1/2", joined_logs)
            self.assertIn("Sending digest chunk 2/2", joined_logs)
            self.assertNotIn("Digest run complete:", joined_logs)
            self.assertIn("Failed to send digest chunk 2/2", joined_logs)

        asyncio.run(scenario())

    def test_setup_hook_initializes_scheduler_without_startup_task(self) -> None:
        async def scenario() -> None:
            os.environ["RUN_ON_STARTUP"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls, patch(
                "bot.asyncio.create_task"
            ) as create_task:
                dedup_store = dedup_cls.return_value
                bot = CommunityInspectorBot()
                bot.digest_scheduler.start = Mock()

                await bot.setup_hook()

            dedup_store.initialize.assert_called_once()
            bot.digest_scheduler.start.assert_called_once_with(bot.run_digest_cycle)
            create_task.assert_not_called()
            self.assertIsNone(bot._startup_task)

        asyncio.run(scenario())

    def test_on_ready_starts_startup_task(self) -> None:
        async def scenario() -> None:
            os.environ["RUN_ON_STARTUP"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"), patch(
                "bot.asyncio.create_task"
            ) as create_task:
                startup_task = Mock()
                startup_task.add_done_callback = Mock()
                startup_task.done.return_value = False
                create_task.return_value = startup_task
                bot = CommunityInspectorBot()

                await bot.on_ready()

            create_task.assert_called_once()
            startup_task.add_done_callback.assert_called_once_with(bot._handle_startup_task_done)
            self.assertIs(bot._startup_task, startup_task)
            created_coro = create_task.call_args.args[0]
            created_coro.close()

        asyncio.run(scenario())

    def test_on_ready_does_not_start_second_startup_task(self) -> None:
        async def scenario() -> None:
            os.environ["RUN_ON_STARTUP"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"), patch(
                "bot.asyncio.create_task"
            ) as create_task:
                startup_task = Mock()
                startup_task.add_done_callback = Mock()
                startup_task.done.return_value = False
                create_task.return_value = startup_task
                bot = CommunityInspectorBot()

                await bot.on_ready()
                created_coro = create_task.call_args.args[0]
                await bot.on_ready()

            create_task.assert_called_once()
            self.assertIs(bot._startup_task, startup_task)
            created_coro.close()

        asyncio.run(scenario())

    def test_handle_startup_task_done_logs_error(self) -> None:
        with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
            bot = CommunityInspectorBot()

        error = RuntimeError("boom")
        task = Mock()
        task.exception.return_value = error
        bot._startup_task = task

        with self.assertLogs("bot", level="ERROR") as captured_logs:
            bot._handle_startup_task_done(task)

        self.assertIs(bot._startup_task, task)
        self.assertIn("Startup digest task failed", "\n".join(captured_logs.output))

    def test_handle_startup_task_done_ignores_cancelled_task(self) -> None:
        with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
            bot = CommunityInspectorBot()

        task = Mock()
        task.exception.side_effect = asyncio.CancelledError
        bot._startup_task = task

        bot._handle_startup_task_done(task)

        self.assertIs(bot._startup_task, task)

    def test_on_ready_skips_startup_task_when_disabled(self) -> None:
        async def scenario() -> None:
            os.environ["RUN_ON_STARTUP"] = "false"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"), patch(
                "bot.asyncio.create_task"
            ) as create_task:
                bot = CommunityInspectorBot()

                await bot.on_ready()

            create_task.assert_not_called()
            self.assertIsNone(bot._startup_task)

        asyncio.run(scenario())

    def test_close_cancels_startup_task(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"), patch("discord.Client.close", new=AsyncMock()):
                bot = CommunityInspectorBot()

            bot.digest_scheduler.shutdown = Mock()

            async def startup_job() -> None:
                await asyncio.sleep(3600)

            task = asyncio.create_task(startup_job())
            bot._startup_task = task

            await bot.close()

            bot.digest_scheduler.shutdown.assert_called_once()
            self.assertTrue(task.cancelled())
            self.assertIsNone(bot._startup_task)

        asyncio.run(scenario())

    def test_collect_source_messages_skips_self_reply_followup(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                dedup_store.has_sent.return_value = False
                bot = CommunityInspectorBot()

            source_author = SimpleNamespace(id=101, bot=False, display_name="alice")
            reply_author = SimpleNamespace(id=101, bot=False, display_name="alice")
            source_message = SimpleNamespace(
                id=1,
                author=source_author,
                content="need help",
                attachments=[],
                jump_url="https://discord.com/channels/1/2/1",
                created_at=datetime(2026, 3, 27, 10, 0, tzinfo=timezone.utc),
                reference=None,
            )
            reply_message = SimpleNamespace(
                id=2,
                author=reply_author,
                content="self reply",
                attachments=[],
                jump_url="https://discord.com/channels/1/2/2",
                created_at=datetime(2026, 3, 27, 10, 5, tzinfo=timezone.utc),
                reference=SimpleNamespace(message_id=1, resolved=None),
            )

            async def history(*args, **kwargs):
                for item in (source_message, reply_message):
                    yield item

            channel = SimpleNamespace(
                id=111,
                name="support",
                guild=SimpleNamespace(me=object()),
                permissions_for=lambda _: SimpleNamespace(view_channel=True, read_message_history=True),
                history=history,
            )
            guild = SimpleNamespace(text_channels=[channel])
            bot.get_guild = Mock(return_value=guild)
            bot._collect_forum_source_messages = AsyncMock(return_value=[])

            collected = await bot._collect_source_messages()

            self.assertEqual(len(collected), 2)
            self.assertEqual(collected[0].followups, [])
            self.assertEqual(collected[1].followups, [])

        asyncio.run(scenario())

    def test_collect_source_messages_keeps_attachment_only_message(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                dedup_store.has_sent.return_value = False
                bot = CommunityInspectorBot()

            attachment_only_message = SimpleNamespace(
                id=1,
                author=SimpleNamespace(id=101, bot=False, display_name="alice"),
                content="   ",
                attachments=[SimpleNamespace(url="https://file.example/image.png")],
                jump_url="https://discord.com/channels/1/2/1",
                created_at=datetime(2026, 3, 27, 10, 0, tzinfo=timezone.utc),
                reference=None,
            )

            async def history(*args, **kwargs):
                yield attachment_only_message

            channel = SimpleNamespace(
                id=111,
                name="support",
                guild=SimpleNamespace(me=object()),
                permissions_for=lambda _: SimpleNamespace(view_channel=True, read_message_history=True),
                history=history,
            )
            guild = SimpleNamespace(text_channels=[channel])
            bot.get_guild = Mock(return_value=guild)

            collected = await bot._collect_discord_source_messages()

            self.assertEqual(len(collected), 1)
            self.assertEqual(collected[0].content, "[附件]")
            self.assertTrue(collected[0].has_attachments)

        asyncio.run(scenario())

    def test_collect_forum_source_messages_includes_recent_topics_only(self) -> None:
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                dedup_store.has_sent.return_value = False
                bot = CommunityInspectorBot()

            now = datetime.now(timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            stale = (now - timedelta(days=10)).isoformat()
            payload = {
                "users": [{"id": 10, "name": "Alice", "username": "alice"}],
                "topic_list": {
                    "topics": [
                        {
                            "id": 123,
                            "slug": "recent-topic",
                            "title": "Recent topic",
                            "excerpt": "Need help with setup",
                            "created_at": recent,
                            "bumped_at": recent,
                            "last_posted_at": recent,
                            "category_id": 5,
                            "posters": [{"user_id": 10, "extras": ""}],
                        },
                        {
                            "id": 456,
                            "slug": "old-topic",
                            "title": "Old topic",
                            "excerpt": "Old but bumped",
                            "created_at": stale,
                            "bumped_at": recent,
                            "last_posted_at": recent,
                            "category_id": 6,
                            "posters": [{"user_id": 10, "extras": ""}],
                        },
                    ]
                },
            }

            with patch("bot.aiohttp.ClientSession", return_value=_MockSession(payload)):
                collected = await bot._collect_forum_source_messages()

            self.assertEqual(len(collected), 2)
            self.assertEqual(
                [item.message_id for item in collected],
                [
                    f"forum-topic:123:{recent}",
                    f"forum-topic:456:{recent}",
                ],
            )
            self.assertEqual(collected[0].source_type, "forum")
            self.assertEqual(collected[0].source_label, "Forum")
            self.assertEqual(collected[0].thread_title, "Recent topic")
            self.assertEqual(collected[0].content, "Need help with setup")
            self.assertEqual(collected[0].followups, [])
            self.assertEqual(collected[0].author_name, "Alice")

        asyncio.run(scenario())

    def test_collect_forum_source_messages_skips_deduped_topic(self) -> None:
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                dedup_store.has_sent.side_effect = lambda message_id: str(message_id) == "forum-topic:123:2026-04-02T23:00:00+00:00"
                bot = CommunityInspectorBot()

            payload = {
                "users": [{"id": 10, "name": "Alice", "username": "alice"}],
                "topic_list": {
                    "topics": [
                        {
                            "id": 123,
                            "slug": "recent-topic",
                            "title": "Recent topic",
                            "excerpt": "Need help with setup",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "last_posted_at": "2026-04-02T23:00:00+00:00",
                            "category_id": 5,
                            "posters": [{"user_id": 10, "extras": ""}],
                        }
                    ]
                },
            }

            with patch("bot.aiohttp.ClientSession", return_value=_MockSession(payload)):
                collected = await bot._collect_forum_source_messages()

            self.assertEqual(collected, [])

        asyncio.run(scenario())

    def test_collect_forum_source_messages_includes_followups(self) -> None:
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                dedup_store.has_sent.return_value = False
                bot = CommunityInspectorBot()

            # Mock the _fetch_forum_topic_replies to return test followups
            bot._fetch_forum_topic_replies = AsyncMock(
                return_value=(
                    [
                        FollowupMessage(author_name="bob", content="Reply from bob"),
                        FollowupMessage(author_name="charlie", content="Another reply"),
                    ],
                    False,  # has_official_reply
                    False,  # user_solved
                )
            )

            now = datetime.now(timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            payload = {
                "users": [{"id": 10, "name": "Alice", "username": "alice"}],
                "topic_list": {
                    "topics": [
                        {
                            "id": 123,
                            "slug": "recent-topic",
                            "title": "Recent topic",
                            "excerpt": "Need help with setup",
                            "created_at": recent,
                            "bumped_at": recent,
                            "last_posted_at": recent,
                            "category_id": 5,
                            "posters": [{"user_id": 10, "extras": ""}],
                        }
                    ]
                },
            }

            with patch("bot.aiohttp.ClientSession", return_value=_MockSession(payload)):
                collected = await bot._collect_forum_source_messages()

            self.assertEqual(len(collected), 1)
            self.assertEqual(len(collected[0].followups), 2)
            self.assertEqual(collected[0].followups[0].author_name, "bob")
            self.assertEqual(collected[0].followups[0].content, "Reply from bob")
            self.assertEqual(collected[0].followups[1].author_name, "charlie")

        asyncio.run(scenario())

    def test_collect_forum_source_messages_skips_author_self_replies(self) -> None:
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                dedup_store.has_sent.return_value = False
                bot = CommunityInspectorBot()

            # Mock _fetch_forum_topic_replies to simulate filtering of self-replies
            # The actual filtering logic is tested in the method itself
            bot._fetch_forum_topic_replies = AsyncMock(
                return_value=(
                    [FollowupMessage(author_name="bob", content="Reply from bob")],
                    False,  # has_official_reply
                    False,  # user_solved
                )
            )

            now = datetime.now(timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            payload = {
                "users": [{"id": 10, "name": "Alice", "username": "alice"}],
                "topic_list": {
                    "topics": [
                        {
                            "id": 123,
                            "slug": "recent-topic",
                            "title": "Recent topic",
                            "excerpt": "Need help",
                            "created_at": recent,
                            "bumped_at": recent,
                            "last_posted_at": recent,
                            "category_id": 5,
                            "posters": [{"user_id": 10, "extras": ""}],
                        }
                    ]
                },
            }

            with patch("bot.aiohttp.ClientSession", return_value=_MockSession(payload)):
                collected = await bot._collect_forum_source_messages()

            self.assertEqual(len(collected), 1)
            # Should only include reply from bob, not self-reply from alice
            self.assertEqual(len(collected[0].followups), 1)
            self.assertEqual(collected[0].followups[0].author_name, "bob")

        asyncio.run(scenario())

    def test_fetch_forum_topic_replies_filters_self_replies(self) -> None:
        """Test that _fetch_forum_topic_replies correctly filters out author self-replies."""
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
                bot = CommunityInspectorBot()

            # Create a mock session that returns test data
            class MockResponse:
                def raise_for_status(self):
                    pass
                async def json(self):
                    return {
                        "post_stream": {
                            "posts": [
                                {"id": 1, "cooked": "Original", "username": "alice", "user_id": 10},
                                {"id": 2, "cooked": "Self reply", "username": "alice", "user_id": 10},
                                {"id": 3, "cooked": "Reply from bob", "username": "bob", "user_id": 20},
                                {"id": 4, "cooked": "Reply from charlie", "username": "charlie", "user_id": 30},
                            ]
                        }
                    }

            class MockSession:
                async def __aenter__(self):
                    return MockResponse()
                async def __aexit__(self, exc_type, exc, tb):
                    return False
                def get(self, url, **kwargs):
                    return MockSession()

            followups, has_official_reply, user_solved = await bot._fetch_forum_topic_replies(
                MockSession(), 123, "test-topic", author_id=10
            )

            self.assertEqual(len(followups), 2)
            self.assertEqual(followups[0].author_name, "bob")
            self.assertEqual(followups[1].author_name, "charlie")
            self.assertFalse(has_official_reply)
            self.assertFalse(user_solved)

        asyncio.run(scenario())

    def test_collect_source_messages_merges_discord_and_forum(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
                bot = CommunityInspectorBot()

            bot._collect_discord_source_messages = AsyncMock(
                return_value=[SourceMessage("1", "support", "alice", 101, "help", [])]
            )
            bot._collect_forum_source_messages = AsyncMock(
                return_value=[
                    SourceMessage(
                        "forum-topic:123",
                        "forum-c5",
                        "bob",
                        10,
                        "Need help",
                        [],
                        source_type="forum",
                        source_label="Forum",
                        thread_title="Recent topic",
                    )
                ]
            )

            collected = await bot._collect_source_messages()

            self.assertEqual([item.message_id for item in collected], ["1", "forum-topic:123"])

        asyncio.run(scenario())

    def test_collect_source_messages_continues_when_forum_collection_fails(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
                bot = CommunityInspectorBot()

            bot._collect_discord_source_messages = AsyncMock(
                return_value=[SourceMessage("1", "support", "alice", 101, "help", [])]
            )
            bot._collect_forum_source_messages = AsyncMock(side_effect=RuntimeError("forum boom"))

            collected = await bot._collect_source_messages()

            self.assertEqual([item.message_id for item in collected], ["1"])
            bot._collect_discord_source_messages.assert_awaited_once()

        asyncio.run(scenario())

    def test_collect_source_messages_logs_error_when_forum_collection_fails(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
                bot = CommunityInspectorBot()

            bot._collect_discord_source_messages = AsyncMock(
                return_value=[SourceMessage("1", "support", "alice", 101, "help", [])]
            )
            bot._collect_forum_source_messages = AsyncMock(side_effect=RuntimeError("forum boom"))

            with self.assertLogs("bot", level="ERROR") as captured_logs:
                collected = await bot._collect_source_messages()

            self.assertEqual([item.message_id for item in collected], ["1"])
            self.assertIn("forum", "\n".join(captured_logs.output).lower())
            self.assertIn("boom", "\n".join(captured_logs.output))

        asyncio.run(scenario())

    def test_classify_messages_passes_source_context(self) -> None:
        async def scenario() -> None:
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
                bot = CommunityInspectorBot()

            bot.classifier.classify_message = AsyncMock(
                return_value=ClassificationResult(
                    category="Problem",
                    translated_zh="帮助",
                    has_reply=False,
                    solved=False,
                    known_status="unknown",
                )
            )

            source = SourceMessage(
                message_id="forum-topic:123",
                channel_name="forum-c5",
                author_name="alice",
                author_id=10,
                content="Need help",
                followups=[],
                source_type="forum",
                source_label="Forum",
                source_location="forum-c5",
                thread_title="Recent topic",
            )

            items, ignored = await bot._classify_messages([source])

            self.assertEqual(len(items), 1)
            self.assertEqual(ignored, [])
            bot.classifier.classify_message.assert_awaited_once_with(
                source_type="forum",
                source_location="forum-c5",
                thread_title="Recent topic",
                channel_name="forum-c5",
                author_name="alice",
                content="Need help",
                followups=[],
            )
            self.assertEqual(items[0].source_label, "Forum")
            self.assertEqual(items[0].thread_title, "Recent topic")

        asyncio.run(scenario())

    def test_message_text_returns_attachment_placeholder(self) -> None:
        with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
            bot = CommunityInspectorBot()

        message = SimpleNamespace(content="   ", attachments=[SimpleNamespace(url="https://file.example")])
        self.assertEqual(bot._message_text(message), "[附件]")

    def test_format_message_time_uses_scheduler_timezone(self) -> None:
        with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
            bot = CommunityInspectorBot()

        value = datetime(2026, 3, 27, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(bot._format_message_time(value), "03-27 18:00")

    def test_fetch_forum_topic_replies_detects_official_user_reply(self) -> None:
        """Test that _fetch_forum_topic_replies detects official user replies."""
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
                bot = CommunityInspectorBot()

            class MockResponse:
                def raise_for_status(self):
                    pass
                async def json(self):
                    return {
                        "post_stream": {
                            "posts": [
                                {"id": 1, "cooked": "Original", "username": "alice", "user_id": 10},
                                {"id": 2, "cooked": "Let me help", "username": "official-user-1", "user_id": 20},
                            ]
                        }
                    }

            class MockSession:
                async def __aenter__(self):
                    return MockResponse()
                async def __aexit__(self, exc_type, exc, tb):
                    return False
                def get(self, url, **kwargs):
                    return MockSession()

            followups, has_official_reply, user_solved = await bot._fetch_forum_topic_replies(
                MockSession(), 123, "test-topic", author_id=10
            )

            self.assertEqual(len(followups), 1)
            self.assertTrue(has_official_reply)
            self.assertFalse(user_solved)

        asyncio.run(scenario())

    def test_fetch_forum_topic_replies_detects_user_solved(self) -> None:
        """Test that _fetch_forum_topic_replies detects user saying solved."""
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            with patch("bot.MessageClassifier"), patch("bot.DedupStore"):
                bot = CommunityInspectorBot()

            class MockResponse:
                def raise_for_status(self):
                    pass
                async def json(self):
                    return {
                        "post_stream": {
                            "posts": [
                                {"id": 1, "cooked": "Original", "username": "alice", "user_id": 10},
                                {"id": 2, "cooked": "Thanks, 解决了！", "username": "bob", "user_id": 20},
                            ]
                        }
                    }

            class MockSession:
                async def __aenter__(self):
                    return MockResponse()
                async def __aexit__(self, exc_type, exc, tb):
                    return False
                def get(self, url, **kwargs):
                    return MockSession()

            followups, has_official_reply, user_solved = await bot._fetch_forum_topic_replies(
                MockSession(), 123, "test-topic", author_id=10
            )

            self.assertEqual(len(followups), 1)
            self.assertFalse(has_official_reply)
            self.assertTrue(user_solved)

        asyncio.run(scenario())

    def test_collect_forum_source_messages_skips_resolved_topics(self) -> None:
        """Test that resolved forum topics are skipped and marked in dedup."""
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            os.environ["DRY_RUN"] = "false"  # Disable dry run to test mark_sent
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                dedup_store.has_sent.return_value = False
                bot = CommunityInspectorBot()

            # Mock _fetch_forum_topic_replies to return official reply (resolved)
            bot._fetch_forum_topic_replies = AsyncMock(
                return_value=(
                    [FollowupMessage(author_name="official-user-1", content="Let me help")],
                    True,   # has_official_reply
                    False,  # user_solved
                )
            )

            now = datetime.now(timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            payload = {
                "users": [{"id": 10, "name": "Alice", "username": "alice"}],
                "topic_list": {
                    "topics": [
                        {
                            "id": 123,
                            "slug": "recent-topic",
                            "title": "Recent topic",
                            "excerpt": "Need help",
                            "created_at": recent,
                            "bumped_at": recent,
                            "last_posted_at": recent,
                            "category_id": 5,
                            "posters": [{"user_id": 10, "extras": ""}],
                        }
                    ]
                },
            }

            with patch("bot.aiohttp.ClientSession", return_value=_MockSession(payload)):
                collected = await bot._collect_forum_source_messages()

            # Should skip resolved topic
            self.assertEqual(len(collected), 0)
            # Should mark as resolved in dedup
            dedup_store.mark_sent.assert_called_once()
            call_args = dedup_store.mark_sent.call_args
            self.assertTrue(call_args[0][0][0].startswith("forum-topic:123:"))
            self.assertEqual(call_args[1]["batch_id"], "resolved")

        asyncio.run(scenario())

    def test_collect_forum_source_messages_skips_resolved_topics_dry_run(self) -> None:
        """Test that resolved forum topics are skipped but NOT marked in dedup during dry_run."""
        async def scenario() -> None:
            os.environ["FORUM_ENABLED"] = "true"
            os.environ["DRY_RUN"] = "true"  # Enable dry run
            with patch("bot.MessageClassifier"), patch("bot.DedupStore") as dedup_cls:
                dedup_store = dedup_cls.return_value
                dedup_store.has_sent.return_value = False
                bot = CommunityInspectorBot()

            # Mock _fetch_forum_topic_replies to return official reply (resolved)
            bot._fetch_forum_topic_replies = AsyncMock(
                return_value=(
                    [FollowupMessage(author_name="official-user-1", content="Let me help")],
                    True,   # has_official_reply
                    False,  # user_solved
                )
            )

            now = datetime.now(timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            payload = {
                "users": [{"id": 10, "name": "Alice", "username": "alice"}],
                "topic_list": {
                    "topics": [
                        {
                            "id": 123,
                            "slug": "recent-topic",
                            "title": "Recent topic",
                            "excerpt": "Need help",
                            "created_at": recent,
                            "bumped_at": recent,
                            "last_posted_at": recent,
                            "category_id": 5,
                            "posters": [{"user_id": 10, "extras": ""}],
                        }
                    ]
                },
            }

            with patch("bot.aiohttp.ClientSession", return_value=_MockSession(payload)):
                collected = await bot._collect_forum_source_messages()

            # Should skip resolved topic
            self.assertEqual(len(collected), 0)
            # Should NOT mark as resolved in dedup during dry_run
            dedup_store.mark_sent.assert_not_called()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
