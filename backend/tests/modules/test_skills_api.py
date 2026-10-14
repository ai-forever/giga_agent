import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from giga_agent.core.db import get_session
from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.modules.skills.api import router
from giga_agent.modules.skills.github import (
    GithubInstallBatch,
    GithubInstallResult,
    GithubPreview,
    GithubSkillCandidate,
    GithubSkillInstall,
    GithubSkillUpdate,
    GithubSource,
)
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

    def test_github_preview_returns_candidates(self):
        candidate = GithubSkillCandidate(
            name="web-design-guidelines",
            description="Design guidance",
            path="skills/web-design-guidelines",
            manifest_path="skills/web-design-guidelines/SKILL.md",
        )
        preview = GithubPreview(
            source=GithubSource("vercel-labs/agent-skills", "main"),
            resolved_ref="main",
            resolved_commit="a" * 40,
            skills=(candidate,),
        )
        with (
            patch(
                "giga_agent.modules.skills.api.preview_github_skills",
                AsyncMock(return_value=preview),
            ),
            patch(
                "giga_agent.models.skill.SkillRepository.get_by_owner",
                AsyncMock(return_value=[]),
            ),
        ):
            response = self.client.post(
                "/github/preview",
                json={"source": "vercel-labs/agent-skills"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["skills"][0]["path"], "skills/web-design-guidelines"
        )
        self.assertEqual(
            response.json()["skills"][0]["manifest_url"],
            "https://github.com/vercel-labs/agent-skills/blob/"
            + "a" * 40
            + "/skills/web-design-guidelines/SKILL.md",
        )
        self.assertFalse(response.json()["skills"][0]["already_installed"])

    def test_github_install_returns_per_skill_result(self):
        candidate = GithubSkillCandidate(
            name="web-design-guidelines",
            description="Design guidance",
            path="skills/web-design-guidelines",
            manifest_path="skills/web-design-guidelines/SKILL.md",
        )
        preview = GithubPreview(
            source=GithubSource("vercel-labs/agent-skills", "main"),
            resolved_ref="main",
            resolved_commit="a" * 40,
            skills=(candidate,),
        )
        fake_skill = types.SimpleNamespace(
            id=uuid.uuid4(),
            name="web-design-guidelines",
            source_url="https://github.com/vercel-labs/agent-skills/tree/" + "a" * 40,
        )
        batch = GithubInstallBatch(
            preview=preview,
            results=(
                GithubInstallResult(
                    candidate=candidate,
                    status="installed",
                    install=GithubSkillInstall(fake_skill, "a" * 40, "hash"),
                ),
            ),
        )
        with (
            patch(
                "giga_agent.modules.skills.api._get_sandbox_runtime",
                AsyncMock(return_value=object()),
            ),
            patch(
                "giga_agent.modules.skills.api.install_github_skills",
                AsyncMock(return_value=batch),
            ) as install,
        ):
            response = self.client.post(
                "/github/install",
                json={
                    "source": "vercel-labs/agent-skills",
                    "skills": [
                        {
                            "path": "skills/web-design-guidelines",
                            "replace_existing": False,
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["status"], "installed")
        install.assert_awaited_once()

    def test_github_update_check_returns_item_status(self):
        skill = types.SimpleNamespace(id=uuid.uuid4(), name="web-design-guidelines")
        update = GithubSkillUpdate(
            skill=skill,
            source="vercel-labs/agent-skills",
            ref="main",
            path="skills/web-design-guidelines",
            status="update_available",
            available_commit="b" * 40,
        )
        with patch(
            "giga_agent.modules.skills.api.check_github_skill_updates",
            AsyncMock(return_value=(update,)),
        ):
            response = self.client.post("/github/updates/check", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["status"], "update_available")


if __name__ == "__main__":
    unittest.main()
