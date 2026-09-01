import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from giga_agent.models.scheduled_task import STATUS_PENDING
from giga_agent.modules.scheduler.tools import (
    _apply_schedule_edit,
    _caller_personal_tag,
    _task_belongs_to_caller,
)


def _runtime(*, metadata=None, memory_tags=None):
    return SimpleNamespace(
        config={
            "metadata": metadata or {},
            "configurable": {"memory_tags": memory_tags or []},
        }
    )


class CallerIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        async def read_metadata(config, _thread_id):
            return (config or {}).get("metadata") or {}

        self._metadata_patcher = patch(
            "giga_agent.modules.scheduler.tools.get_thread_metadata", read_metadata
        )
        self._metadata_patcher.start()

    def tearDown(self) -> None:
        self._metadata_patcher.stop()

    def test_personal_tag_from_group_metadata(self) -> None:
        rt = _runtime(metadata={"channel": "telegram", "telegram_user_id": "42"})
        self.assertEqual(asyncio.run(_caller_personal_tag(rt)), "tg_user_42")

    def test_personal_tag_from_base_memory_tags(self) -> None:
        rt = _runtime(memory_tags=["tg_user_7"])
        self.assertEqual(asyncio.run(_caller_personal_tag(rt)), "tg_user_7")

    def test_personal_tag_absent(self) -> None:
        rt = _runtime(memory_tags=["tg_chat_100"])
        self.assertIsNone(asyncio.run(_caller_personal_tag(rt)))

    def test_belongs_to_caller_matches(self) -> None:
        rt = _runtime(metadata={"channel": "telegram", "telegram_user_id": "42"})
        task = SimpleNamespace(memory_tags=["tg_chat_100", "tg_user_42"])
        self.assertTrue(asyncio.run(_task_belongs_to_caller(task, rt)))

    def test_belongs_to_caller_foreign(self) -> None:
        rt = _runtime(metadata={"channel": "telegram", "telegram_user_id": "42"})
        task = SimpleNamespace(memory_tags=["tg_chat_100", "tg_user_99"])
        self.assertFalse(asyncio.run(_task_belongs_to_caller(task, rt)))

    def test_belongs_to_caller_unknown_identity_allows(self) -> None:
        # No resolvable identity → chat scope already isolates, so allow.
        rt = _runtime(memory_tags=["tg_chat_100"])
        task = SimpleNamespace(memory_tags=["tg_chat_100", "tg_user_99"])
        self.assertTrue(asyncio.run(_task_belongs_to_caller(task, rt)))


class ScheduleEditTests(unittest.TestCase):
    def test_cron_reschedule_reactivates(self) -> None:
        fields: dict = {}
        self.assertIsNone(_apply_schedule_edit(fields, "0 9 * * 1"))
        self.assertEqual(fields["kind"], "cron")
        self.assertEqual(fields["cron"], "0 9 * * 1")
        self.assertEqual(fields["status"], STATUS_PENDING)
        self.assertTrue(fields["is_enabled"])
        self.assertIsNotNone(fields["run_at"])

    def test_iso_reschedule(self) -> None:
        fields: dict = {}
        self.assertIsNone(_apply_schedule_edit(fields, "2099-01-01T09:00"))
        self.assertEqual(fields["kind"], "once")
        self.assertIsNone(fields["cron"])
        self.assertIsNotNone(fields["run_at"])

    def test_invalid_when_returns_error(self) -> None:
        fields: dict = {}
        error = _apply_schedule_edit(fields, "not a time")
        self.assertIsNotNone(error)
        self.assertIn("error", error)
        self.assertEqual(fields, {})


if __name__ == "__main__":
    unittest.main()
