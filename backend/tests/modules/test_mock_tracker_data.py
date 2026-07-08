"""Тесты нормализации/группировки демо-трекера (provider-agnostic контракт)."""

import unittest

from giga_agent.modules.mock_tracker import data


class MockTrackerDataTests(unittest.TestCase):
    def setUp(self):
        # _STATUS мутируется apply_transition — снимаем снапшот и восстанавливаем.
        self._status_backup = dict(data._STATUS)

    def tearDown(self):
        data._STATUS.clear()
        data._STATUS.update(self._status_backup)

    def test_group_by_status(self):
        groups = data.grouped("status")
        by_label = {g["label"]: g for g in groups}
        self.assertEqual(by_label["Открыт"]["issues"].__len__(), 2)
        self.assertEqual(len(by_label["В работе"]["issues"]), 1)
        # accent только для статус-группировки: «В работе» → info
        self.assertEqual(by_label["В работе"].get("accent"), "info")
        self.assertIsNone(by_label["Открыт"].get("accent"))
        # сортировка по размеру убыванием
        self.assertEqual(groups[0]["label"], "Открыт")

    def test_group_by_assignee_has_no_accent(self):
        groups = data.grouped("assignee")
        labels = {g["label"] for g in groups}
        self.assertEqual(labels, {"Алиса", "Боб"})
        self.assertTrue(all(g.get("accent") is None for g in groups))

    def test_unknown_group_by_falls_back_to_status(self):
        self.assertEqual(
            [g["label"] for g in data.grouped("nonsense")],
            [g["label"] for g in data.grouped("status")],
        )

    def test_normalized_issue_shape(self):
        issue = data.grouped("status")[0]["issues"][0]
        for key in ("id", "key", "title", "status", "provider"):
            self.assertIn(key, issue)
        self.assertEqual(issue["provider"], "mock_tracker")

    def test_apply_transition_mutates_status(self):
        issue = data.apply_transition("DEMO-1", "start")
        self.assertIsNotNone(issue)
        self.assertEqual(issue["status"], "В работе")
        self.assertEqual(data._STATUS["DEMO-1"], "В работе")

    def test_apply_transition_invalid_returns_none(self):
        self.assertIsNone(data.apply_transition("DEMO-1", "nonexistent"))
        self.assertIsNone(data.apply_transition("NOPE-9", "start"))


if __name__ == "__main__":
    unittest.main()
