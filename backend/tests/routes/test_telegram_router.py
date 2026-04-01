import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.telegram.api import router


class TelegramRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            is_active=True,
            email="owner@example.com",
        )
        self.db = types.SimpleNamespace()

        app = FastAPI()
        app.include_router(router)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            yield self.db

        app.dependency_overrides[get_current_active_user] = _override_current_user
        app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(app)

    def test_update_contact_by_chat_id_approves_group_chat(self):
        bot = types.SimpleNamespace(id=uuid.uuid4(), user_id=self.user.id)
        now = datetime.now(timezone.utc)
        updated_contact = types.SimpleNamespace(
            id=uuid.uuid4(),
            bot_id=bot.id,
            telegram_chat_id=-1001234567890,
            telegram_chat_type="supergroup",
            telegram_chat_title="GigaAgent Team",
            telegram_username="giga_agent_team",
            telegram_first_name=None,
            telegram_last_name=None,
            is_approved=True,
            created_at=now,
            updated_at=now,
        )
        repo = types.SimpleNamespace(
            get_by_user=AsyncMock(return_value=bot),
            set_contact_approved_by_chat_id=AsyncMock(return_value=updated_contact),
        )

        with patch(
            "giga_agent.modules.telegram.api.TelegramBotRepository",
            return_value=repo,
        ):
            response = self.client.patch(
                f"/contacts/by-chat/{updated_contact.telegram_chat_id}",
                json={"is_approved": True},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["telegram_chat_id"], updated_contact.telegram_chat_id)
        self.assertEqual(payload["telegram_chat_type"], "supergroup")
        self.assertEqual(payload["telegram_chat_title"], "GigaAgent Team")
        repo.set_contact_approved_by_chat_id.assert_awaited_once_with(
            bot.id,
            updated_contact.telegram_chat_id,
            True,
        )


if __name__ == "__main__":
    unittest.main()
