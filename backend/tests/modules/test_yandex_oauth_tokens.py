"""Тесты решения о валидности/refresh OAuth-токена (tokens._valid_token_for_user).

Контракт обратной совместимости: свежий — отдаём как есть; протухший с refresh —
обновляем; ручной (без expiry/refresh) — отдаём; пусто — ошибка.
"""

import asyncio
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from giga_agent.modules.yandex_oauth import tokens

_ACCESS = "YANDEX_DISK_ACCESS_TOKEN"
_REFRESH = "YANDEX_DISK_REFRESH_TOKEN"
_EXPIRES = "YANDEX_DISK_TOKEN_EXPIRES_AT"


def _user(secrets: dict) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), secrets=secrets)


class ValidTokenTests(unittest.TestCase):
    def test_fresh_token_returned_without_refresh(self):
        user = _user({_ACCESS: "fresh-tok", _EXPIRES: str(int(time.time()) + 9999)})
        with patch.object(
            tokens.service, "refresh_access_token", new=AsyncMock()
        ) as refresh:
            result = asyncio.run(tokens._valid_token_for_user(user, "yandex_disk"))
        self.assertEqual(result, "fresh-tok")
        refresh.assert_not_called()

    def test_expired_token_triggers_refresh(self):
        user = _user(
            {
                _ACCESS: "old-tok",
                _REFRESH: "refresh-tok",
                _EXPIRES: str(int(time.time()) - 10),
            }
        )
        new_resp = {"access_token": "new-tok", "expires_in": 3600}
        with patch.object(
            tokens.service, "refresh_access_token", new=AsyncMock(return_value=new_resp)
        ) as refresh, patch.object(tokens, "store_tokens", new=AsyncMock()) as store:
            result = asyncio.run(tokens._valid_token_for_user(user, "yandex_disk"))
        self.assertEqual(result, "new-tok")
        refresh.assert_awaited_once_with("refresh-tok")
        store.assert_awaited_once()

    def test_manual_token_returned_as_is(self):
        # Ручной токен: только access, без expiry и refresh — отдаём без обновления.
        user = _user({_ACCESS: "manual-tok"})
        with patch.object(
            tokens.service, "refresh_access_token", new=AsyncMock()
        ) as refresh:
            result = asyncio.run(tokens._valid_token_for_user(user, "yandex_disk"))
        self.assertEqual(result, "manual-tok")
        refresh.assert_not_called()

    def test_no_token_raises(self):
        user = _user({})
        with self.assertRaises(ValueError):
            asyncio.run(tokens._valid_token_for_user(user, "yandex_disk"))

    def test_is_connected(self):
        self.assertTrue(tokens.is_connected(_user({_ACCESS: "x"}), "yandex_disk"))
        self.assertFalse(tokens.is_connected(_user({}), "yandex_disk"))
        self.assertFalse(tokens.is_connected(None, "yandex_disk"))


if __name__ == "__main__":
    unittest.main()
