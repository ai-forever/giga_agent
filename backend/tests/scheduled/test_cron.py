import unittest
from datetime import datetime, timezone

from giga_agent.scheduled.cron import compute_next_run, is_valid_cron


class CronTests(unittest.TestCase):
    def test_valid_and_invalid(self) -> None:
        self.assertTrue(is_valid_cron("*/5 * * * *"))
        self.assertTrue(is_valid_cron("0 9 * * 1"))
        self.assertFalse(is_valid_cron("not a cron"))
        self.assertFalse(is_valid_cron(""))

    def test_next_run_is_strictly_after(self) -> None:
        after = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
        nxt = compute_next_run("*/15 * * * *", after=after)
        self.assertGreater(nxt, after)
        self.assertEqual(nxt, datetime(2026, 6, 28, 12, 15, tzinfo=timezone.utc))

    def test_timezone_is_respected_and_normalized_to_utc(self) -> None:
        # Sunday 15:00 Moscow -> next Monday 09:00 Moscow == 06:00 UTC.
        after = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
        nxt = compute_next_run("0 9 * * 1", tz_name="Europe/Moscow", after=after)
        self.assertEqual(nxt, datetime(2026, 6, 29, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(nxt.tzinfo, timezone.utc)

    def test_unknown_timezone_falls_back_to_default(self) -> None:
        # An invalid tz_name behaves like no tz_name: both use the default
        # (GIGA_AGENT_TIMEZONE / system local tz), so results match.
        after = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            compute_next_run("0 0 * * *", tz_name="Not/AZone", after=after),
            compute_next_run("0 0 * * *", after=after),
        )

    def test_explicit_timezone_overrides_default(self) -> None:
        after = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
        # Daily midnight in a fixed +03:00 zone == 21:00 UTC previous day.
        nxt = compute_next_run("0 0 * * *", tz_name="Europe/Moscow", after=after)
        self.assertEqual(nxt, datetime(2026, 6, 28, 21, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
