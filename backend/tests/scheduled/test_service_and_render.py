import unittest
from datetime import datetime, timedelta, timezone

from giga_agent.channels.render import render_run_result
from giga_agent.models.scheduled_task import KIND_CRON, KIND_ONCE
from giga_agent.modules.scheduler.service import ScheduleParseError, parse_when


class ParseWhenTests(unittest.TestCase):
    def test_cron_expression(self) -> None:
        parsed = parse_when("0 9 * * 1")
        self.assertEqual(parsed["kind"], KIND_CRON)
        self.assertEqual(parsed["cron"], "0 9 * * 1")
        self.assertIsNotNone(parsed["run_at"])
        self.assertGreater(parsed["run_at"], datetime.now(timezone.utc))

    def test_iso_future_datetime(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(
            microsecond=0
        )
        parsed = parse_when(future.isoformat())
        self.assertEqual(parsed["kind"], KIND_ONCE)
        self.assertIsNone(parsed["cron"])
        self.assertEqual(parsed["run_at"], future)

    def test_past_datetime_rejected(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with self.assertRaises(ScheduleParseError):
            parse_when(past)

    def test_garbage_rejected(self) -> None:
        with self.assertRaises(ScheduleParseError):
            parse_when("tomorrow maybe")
        with self.assertRaises(ScheduleParseError):
            parse_when("")


class RenderTests(unittest.TestCase):
    def test_extracts_text_image_and_attachment(self) -> None:
        result = {
            "messages": [
                {"type": "human", "content": "go"},
                {
                    "type": "ai",
                    "content": (
                        "Готово ![pic](https://x.com/a.png) "
                        "и файл [doc](attachment:/bucket/u/f.pdf)"
                    ),
                },
            ]
        }
        parts = render_run_result(result)
        kinds = {p["kind"] for p in parts}
        self.assertIn("text", kinds)
        self.assertIn("image_url", kinds)
        self.assertIn("attachment_path", kinds)
        attachment = next(p for p in parts if p["kind"] == "attachment_path")
        self.assertEqual(attachment["value"], "/bucket/u/f.pdf")

    def test_empty_result(self) -> None:
        self.assertEqual(render_run_result({"messages": []}), [])


if __name__ == "__main__":
    unittest.main()
