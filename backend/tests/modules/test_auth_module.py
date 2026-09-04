import types
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from giga_agent.modules.auth.module import AuthModule


class AuthModuleBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_startup_fails_closed_without_required_admin_credentials(self):
        repository = MagicMock()
        repository.get_all = AsyncMock(return_value=[])

        with (
            patch(
                "giga_agent.modules.auth.module.UserRepository",
                return_value=repository,
            ),
            patch(
                "giga_agent.modules.auth.module.get_settings",
                return_value=types.SimpleNamespace(
                    giga_agent_admin_email="bootstrap@example.com",
                    giga_agent_admin_password=None,
                ),
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "GIGA_AGENT_ADMIN_EMAIL and GIGA_AGENT_ADMIN_PASSWORD must be set",
            ):
                await AuthModule().on_startup(object())

        repository.create.assert_not_called()

    async def test_admin_password_is_never_written_to_logs(self):
        email = "bootstrap@example.com"
        password = "unique-bootstrap-password"
        admin = types.SimpleNamespace(id=uuid.uuid4(), email=email)
        repository = MagicMock()
        repository.get_all = AsyncMock(return_value=[])
        repository.create = AsyncMock(return_value=admin)

        with (
            patch(
                "giga_agent.modules.auth.module.UserRepository",
                return_value=repository,
            ),
            patch(
                "giga_agent.modules.auth.module.get_settings",
                return_value=types.SimpleNamespace(
                    giga_agent_admin_email=email,
                    giga_agent_admin_password=password,
                ),
            ),
            patch(
                "giga_agent.modules.auth.module.security.get_password_hash",
                return_value="hashed-password",
            ) as hash_password,
            patch(
                "giga_agent.core.team.create_all_members_group",
                new=AsyncMock(),
            ),
            patch("giga_agent.modules.auth.module.event_bus.publish", new=AsyncMock()),
            patch("giga_agent.core.team.ensure_subscribed", new=AsyncMock()),
            patch("giga_agent.modules.auth.module.logger") as logger,
        ):
            await AuthModule().on_startup(object())

        hash_password.assert_called_once_with(password)
        logged = repr(logger.info.call_args_list)
        self.assertNotIn(password, logged)
        self.assertIn(email, logged)
