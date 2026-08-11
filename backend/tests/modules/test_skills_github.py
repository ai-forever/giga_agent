import base64
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from cashews import cache
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.users import User
from giga_agent.modules.skills.github import (
    GithubInstallSelection,
    check_github_skill_updates,
    install_github_skills,
    parse_github_source,
    preview_github_skills,
)
from giga_agent.modules.skills.parser import parse_skill_md
from giga_agent.modules.skills.service import SkillInstallError, SkillsService


class _FakeSandbox:
    def __init__(self) -> None:
        self.installed: list[str] = []
        self.payloads: dict[str, dict[str, bytes]] = {}

    async def install_skill_files(self, owner_id, skill_name, source_dir) -> str:
        _ = owner_id
        self.installed.append(skill_name)
        self.payloads[skill_name] = {
            path.relative_to(source_dir).as_posix(): path.read_bytes()
            for path in source_dir.rglob("*")
            if path.is_file()
        }
        return f"skills/{skill_name}"


class GithubSkillsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        await cache.delete_match("skills:github:index:v1:*")
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with self.session_factory() as session:
            user = User(
                email="github-skills@example.com",
                hashed_password="hash",
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            self.user_id = user.id

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    def _github_data(self, url: str) -> dict:
        alpha_manifest = """---
name: alpha-skill
description: Alpha description
---

Alpha instructions.
"""
        beta_manifest = """---
name: beta-skill
description: Beta description
---

Beta instructions.
"""
        blobs = {
            "https://api.github.com/repos/acme/skills/git/blobs/"
            + "a" * 40: alpha_manifest.encode(),
            "https://api.github.com/repos/acme/skills/git/blobs/"
            + "b" * 40: b"alpha data",
            "https://api.github.com/repos/acme/skills/git/blobs/"
            + "c" * 40: beta_manifest.encode(),
        }
        if url == "https://api.github.com/repos/acme/skills":
            return {"private": False, "default_branch": "main"}
        if url.endswith("/commits/main"):
            return {
                "sha": "a" * 40,
                "commit": {"tree": {"sha": "tree-a"}},
            }
        if url.endswith("/git/trees/tree-a?recursive=1"):
            return {
                "tree": [
                    {
                        "type": "tree",
                        "path": "skills/alpha-skill",
                        "sha": "d" * 40,
                    },
                    {
                        "type": "tree",
                        "path": "skills/beta-skill",
                        "sha": "e" * 40,
                    },
                    {
                        "type": "blob",
                        "path": "skills/alpha-skill/SKILL.md",
                        "size": len(alpha_manifest),
                        "sha": "a" * 40,
                    },
                    {
                        "type": "blob",
                        "path": "skills/alpha-skill/data.txt",
                        "size": 10,
                        "sha": "b" * 40,
                    },
                    {
                        "type": "blob",
                        "path": "skills/beta-skill/SKILL.md",
                        "size": len(beta_manifest),
                        "sha": "c" * 40,
                    },
                ]
            }
        if url in blobs:
            return {
                "encoding": "base64",
                "content": base64.b64encode(blobs[url]).decode(),
            }
        raise AssertionError(f"Unexpected GitHub URL: {url}")

    def _patch_github(self):
        async def response(_client, url: str, *, headers=None):
            _ = headers
            return httpx.Response(200, json=self._github_data(url))

        return patch(
            "giga_agent.modules.skills.github._github_response",
            new=AsyncMock(side_effect=response),
        )

    @staticmethod
    def _manifest(name: str) -> str:
        return f"""---
name: {name}
description: {name} description
---

{name} instructions.
"""

    @contextmanager
    def _patch_skills_sh_delivery(self):
        manifests = {
            "skills/alpha-skill": self._manifest("alpha-skill"),
            "skills/beta-skill": self._manifest("beta-skill"),
        }

        async def read_manifest(_client, _snapshot, candidate):
            return parse_skill_md(manifests[candidate.path])

        async def download(_client, _repository, slug):
            return {"SKILL.md": self._manifest(slug).encode()}

        with (
            patch(
                "giga_agent.modules.skills.github._read_raw_skill_manifest",
                new=AsyncMock(side_effect=read_manifest),
            ),
            patch(
                "giga_agent.modules.skills.github._download_skills_sh_snapshot",
                new=AsyncMock(side_effect=download),
            ) as snapshots,
        ):
            yield snapshots

    async def test_parse_supported_sources_and_reject_unsafe_paths(self) -> None:
        self.assertEqual(
            parse_github_source("acme/skills").repository,
            "acme/skills",
        )
        self.assertEqual(
            parse_github_source("https://github.com/acme/skills").repository,
            "acme/skills",
        )
        source = parse_github_source(
            "https://github.com/acme/skills/tree/main/skills/alpha-skill"
        )
        self.assertEqual(source.ref, "main")
        self.assertEqual(source.path, "skills/alpha-skill")

        with self.assertRaises(SkillInstallError):
            parse_github_source("https://gitlab.com/acme/skills")
        with self.assertRaises(SkillInstallError):
            parse_github_source("https://github.com/acme/skills/tree/main/../secret")

    async def test_preview_discovers_all_skills_and_filters_direct_path(self) -> None:
        async with self.session_factory() as session:
            service = SkillsService(session)
            with self._patch_github(), self._patch_skills_sh_delivery():
                preview = await preview_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                )
                direct = await preview_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="https://github.com/acme/skills/tree/main/skills/alpha-skill",
                )

        self.assertEqual(
            [item.name for item in preview.skills], ["alpha-skill", "beta-skill"]
        )
        self.assertEqual(len(direct.skills), 1)
        self.assertEqual(direct.skills[0].path, "skills/alpha-skill")
        self.assertEqual(preview.resolved_commit, "a" * 40)

    async def test_private_repository_is_rejected(self) -> None:
        async def private_response(_client, url: str, *, headers=None):
            _ = headers
            if url == "https://api.github.com/repos/acme/skills":
                return httpx.Response(
                    200, json={"private": True, "default_branch": "main"}
                )
            raise AssertionError(f"Unexpected GitHub URL: {url}")

        async with self.session_factory() as session:
            service = SkillsService(session)
            with patch(
                "giga_agent.modules.skills.github._github_response",
                new=AsyncMock(side_effect=private_response),
            ):
                with self.assertRaisesRegex(SkillInstallError, "public"):
                    await preview_github_skills(
                        service,
                        owner_id=self.user_id,
                        source="acme/skills",
                    )

    async def test_install_is_idempotent_and_requires_explicit_replace(self) -> None:
        sandbox = _FakeSandbox()
        async with self.session_factory() as session:
            service = SkillsService(session)
            with self._patch_github(), self._patch_skills_sh_delivery():
                first = await install_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                    selections=[GithubInstallSelection(path="skills/alpha-skill")],
                    sandbox=sandbox,
                )
                second = await install_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                    selections=[GithubInstallSelection(path="skills/alpha-skill")],
                    sandbox=sandbox,
                )

        self.assertEqual(first.results[0].status, "installed")
        self.assertEqual(second.results[0].status, "already-installed")
        self.assertEqual(sandbox.installed, ["alpha-skill"])

    async def test_conflicting_existing_skill_requires_replace(self) -> None:
        sandbox = _FakeSandbox()
        async with self.session_factory() as session:
            service = SkillsService(session)
            await service.repo.create(
                owner_id=self.user_id,
                name="alpha-skill",
                description="Existing upload",
                source_type="upload",
                storage_path="skills/alpha-skill",
            )
            with self._patch_github(), self._patch_skills_sh_delivery():
                batch = await install_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                    selections=[GithubInstallSelection(path="skills/alpha-skill")],
                    sandbox=sandbox,
                )

        self.assertEqual(batch.results[0].status, "error")
        self.assertIn("replace_existing", batch.results[0].error or "")
        self.assertEqual(sandbox.installed, [])

    async def test_preview_and_install_reuse_cached_index(self) -> None:
        async with self.session_factory() as session:
            service = SkillsService(session)
            with self._patch_github() as github, self._patch_skills_sh_delivery():
                await preview_github_skills(
                    service, owner_id=self.user_id, source="acme/skills"
                )
                await install_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                    selections=[GithubInstallSelection(path="skills/alpha-skill")],
                    sandbox=_FakeSandbox(),
                )

        urls = [call.args[1] for call in github.await_args_list]
        self.assertEqual(urls.count("https://api.github.com/repos/acme/skills"), 1)
        self.assertEqual(sum("/git/trees/" in url for url in urls), 1)
        self.assertEqual(sum("/git/blobs/" in url for url in urls), 0)

    async def test_install_stores_folder_hash(self) -> None:
        sandbox = _FakeSandbox()
        async with self.session_factory() as session:
            service = SkillsService(session)
            with self._patch_github(), self._patch_skills_sh_delivery():
                batch = await install_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                    selections=[GithubInstallSelection(path="skills/alpha-skill")],
                    sandbox=sandbox,
                )

        self.assertEqual(
            batch.results[0].install.skill.metadata_["folder_hash"], "d" * 40
        )

    async def test_skills_sh_snapshot_is_installed_without_tree_sha_validation(
        self,
    ) -> None:
        sandbox = _FakeSandbox()

        async def download(_client, repository, slug):
            self.assertEqual(repository, "acme/skills")
            self.assertEqual(slug, "alpha-skill")
            return {
                "SKILL.md": self._manifest("alpha-skill").encode(),
                "snapshot-only.txt": b"not present in GitHub tree",
            }

        async with self.session_factory() as session:
            service = SkillsService(session)
            with (
                self._patch_github(),
                self._patch_skills_sh_delivery(),
                patch(
                    "giga_agent.modules.skills.github._download_skills_sh_snapshot",
                    new=AsyncMock(side_effect=download),
                ),
                patch(
                    "giga_agent.modules.skills.github._partial_clone_deliveries",
                    new=AsyncMock(),
                ) as partial_clone,
            ):
                batch = await install_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                    selections=[GithubInstallSelection(path="skills/alpha-skill")],
                    sandbox=sandbox,
                )

        self.assertEqual(batch.results[0].status, "installed")
        self.assertIn("snapshot-only.txt", sandbox.payloads["alpha-skill"])
        self.assertEqual(
            batch.results[0].install.skill.metadata_["resolved_commit"], "a" * 40
        )
        partial_clone.assert_not_awaited()

    async def test_skills_sh_failure_uses_one_partial_clone_for_fallback_skills(
        self,
    ) -> None:
        sandbox = _FakeSandbox()

        async def download(_client, _repository, slug):
            if slug == "alpha-skill":
                raise SkillInstallError("skills.sh unavailable")
            return {"SKILL.md": self._manifest(slug).encode()}

        async def clone(_snapshot, candidates):
            self.assertEqual(
                [candidate.path for candidate in candidates], ["skills/alpha-skill"]
            )
            return {
                "skills/alpha-skill": SimpleNamespace(
                    files={
                        "SKILL.md": self._manifest("alpha-skill").encode(),
                        "data.txt": b"from partial clone",
                    }
                )
            }

        async with self.session_factory() as session:
            service = SkillsService(session)
            with (
                self._patch_github(),
                self._patch_skills_sh_delivery(),
                patch(
                    "giga_agent.modules.skills.github._download_skills_sh_snapshot",
                    new=AsyncMock(side_effect=download),
                ),
                patch(
                    "giga_agent.modules.skills.github._partial_clone_deliveries",
                    new=AsyncMock(side_effect=clone),
                ) as partial_clone,
            ):
                batch = await install_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                    selections=[
                        GithubInstallSelection(path="skills/alpha-skill"),
                        GithubInstallSelection(path="skills/beta-skill"),
                    ],
                    sandbox=sandbox,
                )

        self.assertEqual(
            [result.status for result in batch.results], ["installed", "installed"]
        )
        self.assertEqual(partial_clone.await_count, 1)
        self.assertIn("data.txt", sandbox.payloads["alpha-skill"])
        self.assertEqual(sandbox.installed, ["beta-skill", "alpha-skill"])

    async def test_update_check_groups_skills_by_source(self) -> None:
        async with self.session_factory() as session:
            service = SkillsService(session)
            for name, path, folder_hash in (
                ("alpha-skill", "skills/alpha-skill", "d" * 40),
                ("beta-skill", "skills/beta-skill", "e" * 40),
            ):
                await service.repo.create(
                    owner_id=self.user_id,
                    name=name,
                    description=name,
                    source_type="github",
                    storage_path=f"skills/{name}",
                    metadata_={
                        "github_source": "acme/skills",
                        "github_ref": "main",
                        "github_path": path,
                        "folder_hash": folder_hash,
                    },
                )
            with self._patch_github() as github:
                updates = await check_github_skill_updates(
                    service, owner_id=self.user_id
                )

        self.assertEqual(
            [item.status for item in updates], ["up_to_date", "up_to_date"]
        )
        urls = [call.args[1] for call in github.await_args_list]
        self.assertEqual(urls.count("https://api.github.com/repos/acme/skills"), 1)

    async def test_update_check_reuses_cached_etag(self) -> None:
        async def response(_client, url: str, *, headers=None):
            if (
                url.endswith("/commits/main")
                and headers
                and headers.get("If-None-Match")
            ):
                return httpx.Response(304)
            response_headers = (
                {"etag": '"commit-a"'} if url.endswith("/commits/main") else {}
            )
            return httpx.Response(
                200, json=self._github_data(url), headers=response_headers
            )

        async with self.session_factory() as session:
            service = SkillsService(session)
            with (
                patch(
                    "giga_agent.modules.skills.github._github_response",
                    new=AsyncMock(side_effect=response),
                ) as github,
                self._patch_skills_sh_delivery(),
            ):
                await preview_github_skills(
                    service, owner_id=self.user_id, source="acme/skills"
                )
                await install_github_skills(
                    service,
                    owner_id=self.user_id,
                    source="acme/skills",
                    selections=[GithubInstallSelection(path="skills/alpha-skill")],
                    sandbox=_FakeSandbox(),
                )
                github.reset_mock()
                updates = await check_github_skill_updates(
                    service, owner_id=self.user_id
                )

        self.assertEqual(updates[0].status, "up_to_date")
        self.assertEqual(len(github.await_args_list), 1)
        self.assertEqual(
            github.await_args_list[0].kwargs["headers"]["If-None-Match"], '"commit-a"'
        )


if __name__ == "__main__":
    unittest.main()
