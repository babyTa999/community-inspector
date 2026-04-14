import os
import unittest

from scheduler import DEFAULT_SCHEDULE_HOURS, DigestScheduler, parse_schedule_hours


class SchedulerTests(unittest.TestCase):
    def test_parse_schedule_hours_defaults_and_validation(self) -> None:
        self.assertEqual(parse_schedule_hours(None), DEFAULT_SCHEDULE_HOURS)
        self.assertEqual(parse_schedule_hours("10, 12,12,14"), (10, 12, 14))
        with self.assertRaises(ValueError):
            parse_schedule_hours("24")

    def test_digest_scheduler_uses_explicit_values(self) -> None:
        scheduler = DigestScheduler(timezone_name="Asia/Shanghai", hours=(9, 17))

        self.assertEqual(tuple(scheduler.hours), (9, 17))
        self.assertEqual(str(scheduler.timezone), "Asia/Shanghai")

    def test_digest_scheduler_reads_env_values(self) -> None:
        previous_timezone = os.environ.get("DIGEST_TIMEZONE")
        previous_hours = os.environ.get("DIGEST_SCHEDULE_HOURS")
        try:
            os.environ["DIGEST_TIMEZONE"] = "Asia/Shanghai"
            os.environ["DIGEST_SCHEDULE_HOURS"] = "8,20"
            scheduler = DigestScheduler()
            self.assertEqual(tuple(scheduler.hours), (8, 20))
        finally:
            if previous_timezone is None:
                os.environ.pop("DIGEST_TIMEZONE", None)
            else:
                os.environ["DIGEST_TIMEZONE"] = previous_timezone
            if previous_hours is None:
                os.environ.pop("DIGEST_SCHEDULE_HOURS", None)
            else:
                os.environ["DIGEST_SCHEDULE_HOURS"] = previous_hours


if __name__ == "__main__":
    unittest.main()
