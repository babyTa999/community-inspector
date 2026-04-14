from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Sequence
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

DEFAULT_SCHEDULE_TIMEZONE = "Asia/Shanghai"
DEFAULT_SCHEDULE_HOURS = (10, 12, 14, 16, 18, 20)
MISFIRE_GRACE_TIME_SECONDS = 1800


def parse_schedule_hours(raw_value: str | None) -> tuple[int, ...]:
    if raw_value is None or not raw_value.strip():
        return DEFAULT_SCHEDULE_HOURS

    hours: list[int] = []
    for chunk in raw_value.split(","):
        normalized = chunk.strip()
        if not normalized:
            continue
        try:
            hour = int(normalized)
        except ValueError as exc:
            raise ValueError(f"Invalid digest schedule hour: {normalized}") from exc
        if hour < 0 or hour > 23:
            raise ValueError(f"Digest schedule hour out of range: {hour}")
        hours.append(hour)

    if not hours:
        return DEFAULT_SCHEDULE_HOURS
    return tuple(dict.fromkeys(hours))


class DigestScheduler:
    def __init__(
        self,
        *,
        timezone_name: str | None = None,
        hours: Sequence[int] | None = None,
    ) -> None:
        resolved_timezone_name = timezone_name or os.getenv("DIGEST_TIMEZONE") or DEFAULT_SCHEDULE_TIMEZONE
        resolved_hours = tuple(hours or parse_schedule_hours(os.getenv("DIGEST_SCHEDULE_HOURS")))

        self.timezone = ZoneInfo(resolved_timezone_name)
        self.hours = resolved_hours
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        self._started = False

    def start(self, job: Callable[[], Awaitable[None]]) -> None:
        if self._started:
            return

        self.scheduler.add_job(
            job,
            trigger=self._build_trigger(),
            id="community_digest",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=MISFIRE_GRACE_TIME_SECONDS,
        )
        self.scheduler.start()
        self._started = True

    def shutdown(self) -> None:
        if not self._started:
            return

        self.scheduler.shutdown(wait=False)
        self._started = False

    def _build_trigger(self) -> CronTrigger:
        return CronTrigger(
            hour=",".join(str(hour) for hour in self.hours),
            minute=0,
            timezone=self.timezone,
        )
