import unittest
import uuid
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from pydantic import Field
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.skill import SkillRepository, SkillSourceType
from giga_agent.models.users import User
from giga_agent.modules.skills.service import SkillsService
from giga_agent.sandbox.base import BaseSandbox, RuntimeSkillInfo
from giga_agent.sandbox.manager.file_policy import FileTooLargeError


class FakeRuntimeSkillSandbox(BaseSandbox):
    skills: list[RuntimeSkillInfo] = Field(default_factory=list)
    file_lists: dict[str, list[str]] = Field(default_factory=dict)
    file_contents: dict[str, str] = Field(default_factory=dict)
    removed_storage_paths: list[str] = Field(default_factory=list)

    async def up(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def is_up(self) -> bool:
        return True

    def supports_runtime_skill_listing(self) -> bool:
        return True

    async def list_skills(self, owner_id: uuid.UUID) -> list[RuntimeSkillInfo]:
        _ = owner_id
        return self.skills

    async def read_skill_file(
        self,
        owner_id: uuid.UUID,
        storage_path: str,
        relative_path: str,
    ) -> str:
        _ = owner_id
        skill_name = storage_path.split("/")[-1]
        return self.file_contents[f"{skill_name}:{relative_path}"]

    async def list_skill_files(
        self,
        owner_id: uuid.UUID,
        storage_path: str,
    ) -> list[str]:
        _ = owner_id
        skill_name = storage_path.split("/")[-1]
        return self.file_lists[skill_name]

    def get_skill_sandbox_path(
        self,
        owner_id: uuid.UUID,
        storage_path: str,
        relative_path: str,
    ) -> str:
        _ = owner_id
        return f"/runtime/{storage_path}/{relative_path}"

    async def remove_skill_files(
        self,
        owner_id: uuid.UUID,
        storage_path: str,
    ) -> None:
        _ = owner_id
        self.removed_storage_paths.append(storage_path)


class SkillsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _create_user(self, email: str) -> User:
        async with self.session_factory() as session:
            user = User(
                email=email,
                hashed_password="hash",
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def test_runtime_list_skills_returns_non_toggleable_summaries(self) -> None:
        owner_id = uuid.uuid4()
        sandbox = FakeRuntimeSkillSandbox(
            skills=[
                RuntimeSkillInfo(
                    name="runtime-skill",
                    description="Runtime description",
                    storage_path="skills/runtime-skill",
                )
            ]
        )

        service = SkillsService(session=object())
        summaries = await service.list_skills(owner_id, sandbox)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].name, "runtime-skill")
        self.assertEqual(summaries[0].description, "Runtime description")
        self.assertEqual(summaries[0].source_type, SkillSourceType.LOCAL_DIR)
        self.assertTrue(summaries[0].is_enabled)
        self.assertFalse(summaries[0].is_readonly)
        self.assertFalse(summaries[0].can_toggle)

    async def test_get_skill_body_activates_runtime_skill_without_db_record(
        self,
    ) -> None:
        owner_id = uuid.uuid4()
        sandbox = FakeRuntimeSkillSandbox(
            skills=[
                RuntimeSkillInfo(
                    name="runtime-skill",
                    description="Runtime description",
                    storage_path="skills/runtime-skill",
                )
            ],
            file_lists={
                "runtime-skill": ["SKILL.md", "scripts/run.py"],
            },
            file_contents={
                "runtime-skill:SKILL.md": """---
name: runtime-skill
description: Runtime description
---

Follow these runtime instructions.
""",
            },
        )

        service = SkillsService(session=object())
        activation = await service.get_skill_body(
            owner_id,
            "runtime-skill",
            sandbox,
        )

        self.assertEqual(activation.name, "runtime-skill")
        self.assertEqual(activation.sandbox_path, "/runtime/skills/runtime-skill")
        self.assertEqual(activation.body, "Follow these runtime instructions.")
        self.assertEqual(len(activation.files), 1)
        self.assertEqual(activation.files[0].relative_path, "scripts/run.py")
        self.assertEqual(
            activation.files[0].sandbox_path,
            "/runtime/skills/runtime-skill/scripts/run.py",
        )

    async def test_get_skill_body_uses_one_supported_manifest_name(self) -> None:
        owner_id = uuid.uuid4()
        sandbox = FakeRuntimeSkillSandbox(
            skills=[
                RuntimeSkillInfo(
                    name="runtime-skill",
                    description="Runtime description",
                    storage_path="skills/runtime-skill",
                )
            ],
            file_lists={
                "runtime-skill": ["skills.md", "SKILL.md", "scripts/run.py"],
            },
            file_contents={
                "runtime-skill:SKILL.md": """---
name: runtime-skill
description: Runtime description
---

Uppercase manifest instructions.
""",
                "runtime-skill:skills.md": """---
name: runtime-skill
description: Runtime description
---

Lowercase plural manifest instructions.
""",
            },
        )

        service = SkillsService(session=object())
        activation = await service.get_skill_body(
            owner_id,
            "runtime-skill",
            sandbox,
        )

        self.assertEqual(activation.body, "Uppercase manifest instructions.")
        self.assertEqual(
            [file.relative_path for file in activation.files],
            ["skills.md", "scripts/run.py"],
        )

    def test_find_skill_root_ignores_plural_manifest_name(self) -> None:
        with TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            (skill_dir / "skills.md").write_text(
                """---
name: my-skill
description: Test
---

Instructions.
""",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                SkillsService._find_skill_root(Path(tmpdir))

    async def test_remove_skill_deletes_runtime_skill_without_db_record(self) -> None:
        owner_id = uuid.uuid4()
        sandbox = FakeRuntimeSkillSandbox(
            skills=[
                RuntimeSkillInfo(
                    name="runtime-skill",
                    description="Runtime description",
                    storage_path="skills/runtime-skill",
                )
            ],
        )

        service = SkillsService(session=object())
        summaries = await service.list_skills(owner_id, sandbox)
        await service.remove_skill(owner_id, summaries[0].id, sandbox)

        self.assertEqual(sandbox.removed_storage_paths, ["skills/runtime-skill"])

    async def test_db_list_skills_uses_cache_until_invalidated(self) -> None:
        user = await self._create_user("skills-cache@example.com")
        await SkillsService.invalidate_list_cache(user.id)

        async with self.session_factory() as session:
            repo = SkillRepository(session)
            await repo.create(
                owner_id=user.id,
                name="first-skill",
                description="First",
                source_type=SkillSourceType.UPLOAD,
                storage_path="skills/first-skill",
            )

            service = SkillsService(session)
            initial = await service.list_skills(user.id)
            self.assertEqual([skill.name for skill in initial], ["first-skill"])

            await repo.create(
                owner_id=user.id,
                name="second-skill",
                description="Second",
                source_type=SkillSourceType.UPLOAD,
                storage_path="skills/second-skill",
            )

            cached = await service.list_skills(user.id)
            self.assertEqual([skill.name for skill in cached], ["first-skill"])

            await SkillsService.invalidate_list_cache(user.id)
            refreshed = await service.list_skills(user.id)
            self.assertEqual(
                {skill.name for skill in refreshed},
                {"first-skill", "second-skill"},
            )

    async def test_install_from_upload_rejects_oversized_archive(self) -> None:
        # Бэкстоп по факту прочитанных байт: роут отбивает по метаданным, но
        # вызывающий без размера в метаданных должен упереться здесь.
        service = SkillsService(session=object())

        with patch("giga_agent.modules.skills.service.MAX_SKILL_ARCHIVE_BYTES", 4):
            with self.assertRaises(FileTooLargeError) as ctx:
                await service.install_from_upload(
                    uuid.uuid4(), b"x" * 5, "skill.zip", FakeRuntimeSkillSandbox()
                )

        self.assertEqual(ctx.exception.declared_size, 5)
        self.assertEqual(ctx.exception.limit, 4)
