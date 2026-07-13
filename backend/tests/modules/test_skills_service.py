import unittest
import uuid
from tempfile import TemporaryDirectory
from pathlib import Path

from pydantic import Field
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.skill import SkillRepository, SkillSourceType
from giga_agent.models.users import User
from giga_agent.modules.skills.service import SkillInstallError, SkillsService
from giga_agent.sandbox.base import BaseSandbox, RuntimeSkillInfo


class FakeInstallSandbox(BaseSandbox):
    """Minimal sandbox that stores installed skill files in memory."""

    installed: dict[str, dict[str, str]] = Field(default_factory=dict)
    removed_storage_paths: list[str] = Field(default_factory=list)

    async def up(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def is_up(self) -> bool:
        return True

    def supports_runtime_skill_listing(self) -> bool:
        return False

    async def install_skill_files(
        self,
        owner_id: uuid.UUID,
        skill_name: str,
        source_dir,
    ) -> str:
        _ = owner_id
        source = Path(source_dir)
        files: dict[str, str] = {}
        for path in sorted(source.rglob("*")):
            if path.is_file():
                files[str(path.relative_to(source))] = path.read_text(encoding="utf-8")
        self.installed[skill_name] = files
        return f"skills/{skill_name}"

    async def remove_skill_files(
        self,
        owner_id: uuid.UUID,
        storage_path: str,
    ) -> None:
        _ = owner_id
        self.removed_storage_paths.append(storage_path)
        self.installed.pop(storage_path.split("/")[-1], None)


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

    async def test_create_from_content_persists_agent_skill(self) -> None:
        user = await self._create_user("skill-builder@example.com")
        skill_md = """---
name: my-workflow
description: A reusable workflow captured from chat
---

# Steps

1. Do the thing.
2. Do the other thing.
"""
        sandbox = FakeInstallSandbox()

        async with self.session_factory() as session:
            service = SkillsService(session)
            skill = await service.create_from_content(user.id, skill_md, sandbox)

        self.assertEqual(skill.name, "my-workflow")
        self.assertEqual(skill.description, "A reusable workflow captured from chat")
        self.assertEqual(skill.source_type, SkillSourceType.AGENT)
        self.assertTrue(skill.is_enabled)
        self.assertEqual(skill.storage_path, "skills/my-workflow")
        self.assertIn("SKILL.md", sandbox.installed["my-workflow"])

    async def test_create_from_content_replaces_existing_skill(self) -> None:
        user = await self._create_user("skill-builder-replace@example.com")
        sandbox = FakeInstallSandbox()
        first_md = """---
name: dup-skill
description: first
---

First body.
"""
        second_md = """---
name: dup-skill
description: second
---

Second body.
"""

        async with self.session_factory() as session:
            service = SkillsService(session)
            await service.create_from_content(user.id, first_md, sandbox)
            replaced = await service.create_from_content(user.id, second_md, sandbox)

            self.assertEqual(replaced.description, "second")
            self.assertIn("skills/dup-skill", sandbox.removed_storage_paths)

            summaries = await service.list_skills(user.id)
            names = [s.name for s in summaries]
            self.assertEqual(names.count("dup-skill"), 1)

    async def test_create_from_content_rejects_invalid_manifest(self) -> None:
        user = await self._create_user("skill-builder-invalid@example.com")
        sandbox = FakeInstallSandbox()

        async with self.session_factory() as session:
            service = SkillsService(session)
            with self.assertRaises(ValueError):
                await service.create_from_content(
                    user.id,
                    "no frontmatter here",
                    sandbox,
                )

    async def test_write_extra_skill_file_blocks_path_escape(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(SkillInstallError):
                SkillsService._write_extra_skill_file(root, "../evil.txt", "content")

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
