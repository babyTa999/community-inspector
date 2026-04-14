from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urljoin

import aiohttp
import discord
from dotenv import load_dotenv

from classifier import FollowupMessage, MessageClassifier
from dedup import DedupStore
from formatter import DigestItem, render_digest_chunks
from scheduler import DigestScheduler, parse_schedule_hours

logger = logging.getLogger(__name__)
WINDOW_HOURS = 24
OFFICIAL_USERS = {"official-user-1", "official-user-2", "official-user-3"}
# Pre-compute lowercase set for case-insensitive matching
_OFFICIAL_USERS_LOWER = {u.lower() for u in OFFICIAL_USERS}
_HTML_TAG_RE = re.compile(r"<[^>]+>")
REQUIRED_ENV_VARS = (
    "DISCORD_BOT_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "MODEL_NAME",
    "GUILD_ID",
    "OUTPUT_CHANNEL_ID",
)
OPTIONAL_ENV_DEFAULTS = {
    "DIGEST_TIMEZONE": "Asia/Shanghai",
    "DIGEST_SCHEDULE_HOURS": "10,12,14,16,18,20",
    "DRY_RUN": "false",
    "RUN_ON_STARTUP": "false",
    "FORUM_ENABLED": "true",
    "FORUM_BASE_URL": "https://community.example.com",
}


@dataclass(slots=True)
class SourceMessage:
    message_id: str
    channel_name: str
    author_name: str
    author_id: int
    content: str
    followups: list[FollowupMessage]
    message_url: str = ""
    created_at_text: str = ""
    has_attachments: bool = False
    source_type: str = "discord"
    source_label: str = "Discord"
    source_location: str = ""
    thread_title: str = ""
    has_reply: bool | None = None
    solved: bool | None = None
    is_dcmirror: bool = False


class CommunityInspectorBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)

        load_dotenv()
        self.config = self._load_config()
        self.classifier = MessageClassifier()
        self.dedup_store = DedupStore()
        self.digest_scheduler = DigestScheduler(
            timezone_name=self.config["DIGEST_TIMEZONE"],
            hours=self._parse_schedule_hours(self.config["DIGEST_SCHEDULE_HOURS"]),
        )
        self.guild_id = int(self.config["GUILD_ID"])
        self.output_channel_id = int(self.config["OUTPUT_CHANNEL_ID"])
        self.dry_run = self._parse_bool(self.config["DRY_RUN"])
        self.run_on_startup = self._parse_bool(self.config["RUN_ON_STARTUP"])
        self.forum_enabled = self._parse_bool(self.config["FORUM_ENABLED"])
        self.forum_base_url = self.config["FORUM_BASE_URL"].rstrip("/")
        self._run_lock = asyncio.Lock()
        self._startup_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        self.dedup_store.initialize()
        self.digest_scheduler.start(self.run_digest_cycle)

    async def close(self) -> None:
        self.digest_scheduler.shutdown()
        if self._startup_task is not None and not self._startup_task.done():
            self._startup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._startup_task
        self._startup_task = None
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")
        if self.run_on_startup and self._startup_task is None:
            self._startup_task = asyncio.create_task(self.run_digest_cycle())
            self._startup_task.add_done_callback(self._handle_startup_task_done)

    def _handle_startup_task_done(self, task: asyncio.Task[None]) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            exception = task.exception()
            if exception is not None:
                logger.error("Startup digest task failed", exc_info=exception)

    async def run_digest_cycle(self) -> None:
        if self._run_lock.locked():
            logger.info("Digest run skipped because another run is active")
            return

        async with self._run_lock:
            logger.info("Starting digest run (dry_run=%s)", self.dry_run)
            source_messages = await self._collect_source_messages()
            if not source_messages:
                logger.info("No unsent source messages found")
                logger.info(
                    "Digest run complete: mode=%s items=0 ignored=0 chunks=0 sent_items=0",
                    self._run_mode_label(),
                )
                return

            logger.info("Collected %s candidate source messages", len(source_messages))

            if self.dry_run:
                logger.info(
                    "Dry run complete: collected=%s messages (classification skipped)",
                    len(source_messages),
                )
                logger.info(
                    "Digest run complete: mode=%s items=%s ignored=0 chunks=0 sent_items=0",
                    self._run_mode_label(),
                    len(source_messages),
                )
                return

            items, ignored_message_ids = await self._classify_messages(source_messages)
            if not items:
                if ignored_message_ids and not self.dry_run:
                    self.dedup_store.mark_sent(ignored_message_ids, batch_id="ignored")
                logger.info(
                    "No digest items produced after classification (ignored=%s)",
                    len(ignored_message_ids),
                )
                logger.info(
                    "Digest run complete: mode=%s items=0 ignored=%s chunks=0 sent_items=0",
                    self._run_mode_label(),
                    len(ignored_message_ids),
                )
                return

            digest_time = datetime.now(timezone.utc).astimezone(self.digest_scheduler.timezone)
            batch_id = str(uuid.uuid4())
            chunks = render_digest_chunks(items, digest_time)

            try:
                await self._send_to_discord(chunks)
            except Exception:
                logger.exception("Failed to send digest output")
                raise

            sent_message_ids: list[str] = []
            for chunk in chunks:
                if chunk.message_ids:
                    sent_message_ids.extend(chunk.message_ids)

            if sent_message_ids:
                self.dedup_store.mark_sent(sent_message_ids, batch_id=batch_id)
            if ignored_message_ids:
                self.dedup_store.mark_sent(ignored_message_ids, batch_id="ignored")
            logger.info(
                "Digest posted with %s items across %s chunks (ignored=%s sent_items=%s)",
                len(items),
                len(chunks),
                len(ignored_message_ids),
                len(sent_message_ids),
            )
            logger.info(
                "Digest run complete: mode=%s items=%s ignored=%s chunks=%s sent_items=%s",
                self._run_mode_label(),
                len(items),
                len(ignored_message_ids),
                len(chunks),
                len(sent_message_ids),
            )

    async def _collect_source_messages(self) -> list[SourceMessage]:
        try:
            return await self._collect_forum_source_messages()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Forum source collection failed")
            raise

    async def _collect_forum_source_messages(self) -> list[SourceMessage]:
        if not self.forum_enabled:
            return []

        removed_count = self.dedup_store.cleanup_forum_entries_older_than(hours=WINDOW_HOURS)
        if removed_count:
            logger.info("Expired %s forum dedup entries older than %s hours", removed_count, WINDOW_HOURS)

        window_start = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        latest_url = urljoin(f"{self.forum_base_url}/", "latest.json")
        logger.info("Fetching forum latest topics from %s", latest_url)

        async with aiohttp.ClientSession() as session:
            async with session.get(latest_url) as response:
                response.raise_for_status()
                payload = await response.json()

            users_by_id = {
                int(user["id"]): user
                for user in payload.get("users", [])
                if isinstance(user, dict) and isinstance(user.get("id"), int)
            }
            topics = payload.get("topic_list", {}).get("topics", [])
            collected: list[SourceMessage] = []

            for topic in topics:
                if not isinstance(topic, dict):
                    continue

                created_at = self._parse_forum_datetime(topic.get("created_at"))
                last_posted_at = self._parse_forum_datetime(
                    topic.get("last_posted_at") or topic.get("bumped_at") or topic.get("created_at")
                )
                if last_posted_at is None or last_posted_at < window_start:
                    continue

                topic_id = topic.get("id")
                slug = str(topic.get("slug") or "").strip()
                if not isinstance(topic_id, int) or not slug:
                    continue

                message_id = self._build_forum_message_id(topic_id, last_posted_at)
                if self.dedup_store.has_sent(message_id):
                    continue

                posters = topic.get("posters")
                author_id = self._extract_forum_author_id(posters)
                author = users_by_id.get(author_id, {}) if author_id is not None else {}
                author_name = str(author.get("name") or author.get("username") or "forum-user").strip() or "forum-user"
                category_id = topic.get("category_id")
                location = f"forum-c{category_id}" if isinstance(category_id, int) else "forum"
                title = self._normalize_forum_text(str(topic.get("title") or topic.get("fancy_title") or ""))
                excerpt = self._normalize_forum_text(str(topic.get("excerpt") or ""))
                message_url = urljoin(f"{self.forum_base_url}/", f"t/{slug}/{topic_id}")

                followups, has_official_reply, user_solved = await self._fetch_forum_topic_replies(
                    session, topic_id, slug, author_id
                )

                collected.append(
                    SourceMessage(
                        message_id=message_id,
                        channel_name=location,
                        author_name=author_name,
                        author_id=author_id or 0,
                        content=excerpt,
                        followups=followups,
                        message_url=message_url,
                        created_at_text=self._format_message_time(created_at),
                        has_attachments=False,
                        source_type="forum",
                        source_label="Forum",
                        source_location=location,
                        thread_title=title,
                        has_reply=bool(followups),
                        solved=user_solved,
                    )
                )

        logger.info("Forum scanning complete: candidates=%s", len(collected))
        return collected

    async def _classify_messages(
        self,
        source_messages: Iterable[SourceMessage],
    ) -> tuple[list[DigestItem], list[str]]:
        items: list[DigestItem] = []
        ignored_message_ids: list[str] = []
        total_messages = 0
        failed_messages = 0

        for source in source_messages:
            total_messages += 1
            try:
                result = await self.classifier.classify_message(
                    source_type=source.source_type,
                    source_location=source.source_location or source.channel_name,
                    thread_title=source.thread_title,
                    channel_name=source.channel_name,
                    author_name=source.author_name,
                    content=source.content,
                    followups=source.followups,
                )
            except Exception:
                failed_messages += 1
                logger.exception("Classification failed for message %s", source.message_id)
                continue

            if result.category == "Ignore":
                ignored_message_ids.append(source.message_id)
                continue

            items.append(
                DigestItem(
                    message_id=source.message_id,
                    channel_name=source.channel_name,
                    author_name=source.author_name,
                    original_text=source.content,
                    translated_zh=result.translated_zh,
                    category=result.category,
                    has_reply=source.has_reply,
                    solved=source.solved,
                    known_status=result.known_status,
                    known_source=result.known_source,
                    message_url=source.message_url,
                    created_at_text=source.created_at_text,
                    has_attachments=source.has_attachments,
                    source_label=source.source_label,
                    thread_title=source.thread_title,
                    is_dcmirror=source.is_dcmirror,
                )
            )

        logger.info(
            "Classification summary: total=%s included=%s ignored=%s failed=%s",
            total_messages,
            len(items),
            len(ignored_message_ids),
            failed_messages,
        )
        return items, ignored_message_ids

    async def _resolve_output_channel(self) -> discord.TextChannel:
        channel = self.get_channel(self.output_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.output_channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Output channel {self.output_channel_id} is not a TextChannel")
        return channel

    async def _send_to_discord(self, chunks: list[DigestItem]) -> None:
        """Send digest chunks to Discord channel."""
        output_channel = await self._resolve_output_channel()
        logger.info(
            "Resolved output channel: #%s (%s)",
            output_channel.name,
            output_channel.id,
        )
        total_chunks = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            logger.info("Sending digest chunk %s/%s", index, total_chunks)
            await output_channel.send(chunk.text)

    def _load_config(self) -> dict[str, str]:
        config = {key: os.getenv(key, "").strip() for key in REQUIRED_ENV_VARS}
        config.update({key: os.getenv(key, default).strip() for key, default in OPTIONAL_ENV_DEFAULTS.items()})
        missing = [key for key, value in config.items() if key in REQUIRED_ENV_VARS and not value]
        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {missing_text}")
        return config

    def _parse_bool(self, raw_value: str) -> bool:
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}

    def _parse_schedule_hours(self, raw_value: str) -> tuple[int, ...]:
        return parse_schedule_hours(raw_value)

    def _format_message_time(self, value: datetime) -> str:
        local_time = value.astimezone(self.digest_scheduler.timezone)
        return local_time.strftime("%m-%d %H:%M")

    def _parse_forum_datetime(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _build_forum_message_id(self, topic_id: int, last_posted_at: datetime) -> str:
        return f"forum-topic:{topic_id}:{last_posted_at.astimezone(timezone.utc).isoformat()}"

    async def _fetch_forum_topic_replies(
        self,
        session: aiohttp.ClientSession,
        topic_id: int,
        slug: str,
        author_id: int | None,
    ) -> tuple[list[FollowupMessage], bool, bool]:
        """Fetch forum topic replies and detect resolved status.

        Returns:
            Tuple of (followups, has_official_reply, user_solved)
        """
        topic_url = urljoin(f"{self.forum_base_url}/", f"t/{slug}/{topic_id}.json")
        try:
            async with session.get(topic_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning("Failed to fetch forum topic replies for %s: %s", topic_id, exc)
            return [], False, False

        posts = data.get("post_stream", {}).get("posts", [])
        # skip first post (original), take up to 5 latest replies
        replies = posts[1:][-5:]
        result: list[FollowupMessage] = []
        has_official_reply = False
        user_solved = False
        solved_keywords = ("solved", "解决", "已解决", "搞定了", "ok了", "好了")

        for post in replies:
            if not isinstance(post, dict):
                continue
            post_user_id = post.get("user_id")
            raw = str(post.get("cooked") or post.get("raw") or "").strip()
            text = _HTML_TAG_RE.sub(" ", raw)
            text = self._normalize_forum_text(text)
            if text and text != "-":
                username = str(post.get("username") or post.get("name") or "forum-user").strip()
                result.append(FollowupMessage(author_name=username, content=text))
                if username.lower() in _OFFICIAL_USERS_LOWER:
                    has_official_reply = True
                if isinstance(post_user_id, int) and post_user_id == author_id and any(kw in text.lower() for kw in solved_keywords):
                    user_solved = True
        return result, has_official_reply, user_solved

    def _extract_forum_author_id(self, posters: Any) -> int | None:
        if not isinstance(posters, list):
            return None
        for poster in posters:
            if not isinstance(poster, dict):
                continue
            extras = poster.get("extras")
            if isinstance(extras, str) and "latest" in extras:
                continue
            user_id = poster.get("user_id")
            if isinstance(user_id, int):
                return user_id
        for poster in posters:
            if isinstance(poster, dict) and isinstance(poster.get("user_id"), int):
                return int(poster["user_id"])
        return None

    def _normalize_forum_text(self, value: str) -> str:
        compact = " ".join((value or "").split())
        return compact or "-"

    def _run_mode_label(self) -> str:
        return "dry-run" if self.dry_run else "live"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    bot = CommunityInspectorBot()
    bot.run(bot.config["DISCORD_BOT_TOKEN"], log_handler=None)


if __name__ == "__main__":
    main()
