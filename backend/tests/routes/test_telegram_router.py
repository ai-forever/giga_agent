import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.routes.channels import get_channel_repository, router


class ChannelsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            is_active=True,
            email="owner@example.com",
        )
        self.repo = types.SimpleNamespace()

        app = FastAPI()
        app.include_router(router)

        async def _override_current_user():
            return self.user

        async def _override_get_channel_repository():
            return self.repo

        app.dependency_overrides[get_current_active_user] = _override_current_user
        app.dependency_overrides[get_channel_repository] = (
            _override_get_channel_repository
        )
        self.client = TestClient(app)

    def test_update_channel_contact_by_chat_id_approves_group_chat(self):
        bot = types.SimpleNamespace(
            id=uuid.uuid4(),
            user_id=self.user.id,
            channel_type="telegram",
        )
        now = datetime.now(timezone.utc)
        updated_contact = types.SimpleNamespace(
            id=uuid.uuid4(),
            bot_id=bot.id,
            external_chat_id="-1001234567890",
            external_user_id=None,
            chat_type="supergroup",
            chat_title="GigaAgent Team",
            username="giga_agent_team",
            first_name=None,
            last_name=None,
            is_approved=True,
            created_at=now,
            updated_at=now,
        )
        self.repo.get_by_id = AsyncMock(return_value=bot)
        self.repo.set_contact_approved_by_external_id = AsyncMock(
            return_value=updated_contact
        )

        response = self.client.patch(
            f"/channels/{bot.id}/contacts/by-chat/{updated_contact.external_chat_id}",
            json={"is_approved": True},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["external_chat_id"], updated_contact.external_chat_id)
        self.assertIsNone(payload["external_user_id"])
        self.assertEqual(payload["chat_type"], "supergroup")
        self.assertEqual(payload["chat_title"], "GigaAgent Team")
        self.repo.get_by_id.assert_awaited_once_with(bot.id)
        self.repo.set_contact_approved_by_external_id.assert_awaited_once_with(
            bot_id=bot.id,
            external_chat_id=updated_contact.external_chat_id,
            external_user_id=None,
            approved=True,
        )


if __name__ == "__main__":
    unittest.main()
