import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.skills.api import router
from giga_agent.modules.skills.service import SkillInstallError


class SkillsUploadLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = types.SimpleNamespace(id=uuid.uuid4(), is_active=True)
        self.app = FastAPI()
        self.app.include_router(router)

        async def _override_current_user():
            return self.user

        async def _override_get_session():
            yield object()

        self.app.dependency_overrides[get_current_active_user] = _override_current_user
        self.app.dependency_overrides[get_session] = _override_get_session
        self.client = TestClient(self.app)

    def _post(self, payload: bytes):
        return self.client.post(
            "/upload",
            files={"file": ("skill.zip", payload, "application/zip")},
        )

    def test_oversize_archive_rejected_with_413(self):
        with patch("giga_agent.modules.skills.api.MAX_SKILL_ARCHIVE_BYTES", 3):
            response = self._post(b"x" * 10)

        self.assertEqual(response.status_code, 413)
        self.assertIn("превышает лимит", response.json()["detail"])

    def test_oversize_archive_not_read_or_installed(self):
        install = AsyncMock()
        with (
            patch("giga_agent.modules.skills.api.MAX_SKILL_ARCHIVE_BYTES", 3),
            patch(
                "giga_agent.modules.skills.api.SkillsService.install_from_upload",
                install,
            ),
        ):
            response = self._post(b"x" * 10)

        self.assertEqual(response.status_code, 413)
        install.assert_not_awaited()

    def test_within_limit_reaches_install(self):
        # Гард пропускает: дальше падаем уже на установке, а не на размере.
        with (
            patch("giga_agent.modules.skills.api.MAX_SKILL_ARCHIVE_BYTES", 1024),
            patch(
                "giga_agent.modules.skills.api._get_sandbox_runtime",
                AsyncMock(return_value=object()),
            ),
            patch(
                "giga_agent.modules.skills.api.SkillsService.install_from_upload",
                AsyncMock(side_effect=SkillInstallError("bad archive")),
            ),
        ):
            response = self._post(b"x" * 10)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "bad archive")


if __name__ == "__main__":
    unittest.main()
