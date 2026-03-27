import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.modules.auth.api import _validate_sandbox_provider_id


class AuthSandboxProviderValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_sandbox_provider_id_allows_local_provider_for_non_admin(self):
        provider_id = uuid.uuid4()
        db = types.SimpleNamespace()

        with patch(
            "giga_agent.modules.auth.api._validate",
            AsyncMock(return_value=None),
        ) as mocked_validate:
            await _validate_sandbox_provider_id(
                db=db,
                user_id=uuid.uuid4(),
                sandbox_provider_id=provider_id,
            )

        mocked_validate.assert_awaited_once()
