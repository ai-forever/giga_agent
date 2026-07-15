"""Business logic for Agent Skills management."""

from __future__ import annotations

import hashlib
import os
import tarfile
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cashews import cache

from giga_agent.core.logging import get_logger
from giga_agent.models.skill import (
    Skill,
    SkillActivation,
    SkillFile,
    SkillRepository,
    SkillSourceType,
    SkillSummary,
)
from giga_agent.modules.skills.manifest import (
    find_skill_manifest_path,
    is_skill_manifest_filename,
    select_skill_manifest_file,
)
from giga_agent.modules.skills.parser import parse_skill_md

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from giga_agent.sandbox.base import BaseSandbox

logger = get_logger(__name__)

MAX_ARCHIVE_SIZE = 10 * 1024 * 1024  # 10 MB
_SKILLS_LIST_CACHE_ENABLED = (
    os.getenv("GIGA_AGENT_SKILLS_LIST_CACHE_ENABLED", "true").lower() != "false"
)
_SKILLS_LIST_CACHE_TTL = int(os.getenv("GIGA_AGENT_SKILLS_LIST_CACHE_TTL", "300"))
_RUNTIME_SKILL_CREATED_AT = datetime(1970, 1, 1, tzinfo=timezone.utc)


class SkillInstallError(ValueError):
    pass


class SkillNotFoundError(KeyError):
    pass


class SkillsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SkillRepository(session)

    @staticmethod
    def _get_skill_root_path(
        sandbox: BaseSandbox,
        owner_id: uuid.UUID,
        storage_path: str,
    ) -> str:
        return sandbox.get_skill_sandbox_path(owner_id, storage_path, "").rstrip("/")

    @staticmethod
    def list_cache_key(owner_id: uuid.UUID) -> str:
        return f"skills:list:{owner_id}"

    @classmethod
    async def invalidate_list_cache(cls, owner_id: uuid.UUID) -> None:
        await cache.delete(cls.list_cache_key(owner_id))

    @staticmethod
    def _runtime_skill_id(owner_id: uuid.UUID, skill_name: str) -> uuid.UUID:
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"giga-agent:skill:{owner_id}:{skill_name}",
        )

    @staticmethod
    def _runtime_skill_storage_path(skill_name: str) -> str:
        return f"skills/{skill_name}"

    async def install_from_upload(
        self,
        owner_id: uuid.UUID,
        archive_bytes: bytes,
        filename: str,
        sandbox: BaseSandbox,
    ) -> Skill:
        if len(archive_bytes) > MAX_ARCHIVE_SIZE:
            raise SkillInstallError(
                f"Archive exceeds {MAX_ARCHIVE_SIZE // (1024 * 1024)} MB limit"
            )

        with tempfile.TemporaryDirectory(prefix="skill_upload_") as tmpdir:
            tmp_path = Path(tmpdir)
            self._extract_archive(archive_bytes, filename, tmp_path)

            skill_root = self._find_skill_root(tmp_path)
            skill_md_path = self._find_skill_manifest_path(skill_root)
            parsed = parse_skill_md(skill_md_path.read_text(encoding="utf-8"))

            existing = await self.repo.get_by_owner_and_name(owner_id, parsed.name)
            if existing:
                await sandbox.remove_skill_files(owner_id, existing.storage_path)
                await self.repo.delete(existing)

            storage_path = await sandbox.install_skill_files(
                owner_id, parsed.name, skill_root
            )
            skill = await self.repo.create(
                owner_id=owner_id,
                name=parsed.name,
                description=parsed.description,
                source_type=SkillSourceType.UPLOAD,
                storage_path=storage_path,
                metadata_=parsed.metadata,
            )
            if skill is None:
                raise SkillInstallError(
                    f"Skill '{parsed.name}' already exists for this user"
                )
            await self.invalidate_list_cache(owner_id)
            return skill

    async def install_builtin(
        self,
        owner_id: uuid.UUID,
        skill_name: str,
        sandbox: BaseSandbox,
    ) -> Skill:
        from giga_agent.modules.skills.builtins import get_builtin_skill_dir

        builtin_dir = get_builtin_skill_dir(skill_name)
        if builtin_dir is None:
            raise SkillNotFoundError(f"Built-in skill '{skill_name}' not found")

        skill_md = self._find_skill_manifest_path(builtin_dir)
        parsed = parse_skill_md(skill_md.read_text(encoding="utf-8"))

        existing = await self.repo.get_by_owner_and_name(owner_id, parsed.name)
        if existing:
            await sandbox.remove_skill_files(owner_id, existing.storage_path)
            await self.repo.delete(existing)

        storage_path = await sandbox.install_skill_files(
            owner_id, parsed.name, builtin_dir
        )
        skill = await self.repo.create(
            owner_id=owner_id,
            name=parsed.name,
            description=parsed.description,
            source_type=SkillSourceType.BUILTIN,
            storage_path=storage_path,
            metadata_=parsed.metadata,
        )
        if skill is None:
            raise SkillInstallError(
                f"Skill '{parsed.name}' already exists for this user"
            )
        await self.invalidate_list_cache(owner_id)
        return skill

    async def sync_local_dirs(
        self,
        owner_id: uuid.UUID,
        sandbox: BaseSandbox,
        extra_dirs: list[str] | None = None,
    ) -> list[Skill]:
        """Sync LOCAL_DIR skills from the filesystem (Local Jupyter only)."""
        from giga_agent.sandbox.local_jupyter.runtime import LocalJupyterSandbox

        if not isinstance(sandbox, LocalJupyterSandbox):
            return []

        found = await sandbox.scan_skill_dirs(
            owner_id,
            extra_dirs,
            include_agent_skills=False,
        )
        found_names: set[str] = set()
        result: list[Skill] = []

        for info in found:
            name = info["name"]
            found_names.add(name)
            description = info["description"]
            source_dir = info["source_dir"]

            existing = await self.repo.get_by_owner_and_name(owner_id, name)
            if existing and existing.source_type == SkillSourceType.LOCAL_DIR:
                md_hash = self._hash_skill_md(Path(source_dir))
                old_hash = (existing.metadata_ or {}).get("md_hash")
                if md_hash != old_hash:
                    storage_path = await sandbox.install_skill_files(
                        owner_id, name, source_dir
                    )
                    existing = await self.repo.update(
                        existing,
                        description=description,
                        storage_path=storage_path,
                        source_url=source_dir,
                        metadata_={**(existing.metadata_ or {}), "md_hash": md_hash},
                    )
                result.append(existing)
            elif existing is None:
                storage_path = await sandbox.install_skill_files(
                    owner_id, name, source_dir
                )
                md_hash = self._hash_skill_md(Path(source_dir))
                skill = await self.repo.create(
                    owner_id=owner_id,
                    name=name,
                    description=description,
                    source_type=SkillSourceType.LOCAL_DIR,
                    storage_path=storage_path,
                    source_url=source_dir,
                    metadata_={"md_hash": md_hash},
                )
                if skill:
                    result.append(skill)

        await self.repo.delete_local_dir_not_in(owner_id, found_names)
        await self.invalidate_list_cache(owner_id)
        return result

    async def list_skills(
        self,
        owner_id: uuid.UUID,
        sandbox: BaseSandbox | None = None,
    ) -> list[SkillSummary]:
        if sandbox is not None and sandbox.supports_runtime_skill_listing():
            return await self._list_runtime_skills(owner_id, sandbox)
        return await self._list_db_skills(owner_id)

    async def _list_db_skills(self, owner_id: uuid.UUID) -> list[SkillSummary]:
        if _SKILLS_LIST_CACHE_ENABLED:
            cached = await cache.get(self.list_cache_key(owner_id))
            if cached is not None:
                return [SkillSummary.model_validate(item) for item in cached]

        skills = await self.repo.get_by_owner(owner_id)
        summaries = [
            SkillSummary(
                id=s.id,
                name=s.name,
                description=s.description,
                is_enabled=s.is_enabled,
                source_type=s.source_type,
                created_at=s.created_at,
            )
            for s in skills
        ]
        if _SKILLS_LIST_CACHE_ENABLED and _SKILLS_LIST_CACHE_TTL > 0:
            await cache.set(
                self.list_cache_key(owner_id),
                [s.model_dump(mode="json") for s in summaries],
                expire=_SKILLS_LIST_CACHE_TTL,
            )
        return summaries

    async def _list_runtime_skills(
        self,
        owner_id: uuid.UUID,
        sandbox: BaseSandbox,
    ) -> list[SkillSummary]:
        skills = await sandbox.list_skills(owner_id)
        return [
            SkillSummary(
                id=self._runtime_skill_id(owner_id, s.name),
                name=s.name,
                description=s.description,
                is_enabled=True,
                source_type=SkillSourceType.LOCAL_DIR,
                created_at=_RUNTIME_SKILL_CREATED_AT,
                is_readonly=False,
                can_toggle=False,
            )
            for s in sorted(skills, key=lambda item: item.name)
        ]

    @staticmethod
    def _tolerant_name_match(requested: str, available: list[str]) -> str | None:
        """Find a single skill name match using tolerant rules.

        Order: (1) exact case-insensitive match; (2) single skill whose name
        ends with `/<requested>`; (3) if requested has a `/`, single skill
        whose name equals the tail after the last `/`. Returns None if zero
        or ambiguous (>1) matches.
        """
        req = requested.lower()

        for name in available:
            if name.lower() == req:
                return name

        suffix_matches = [n for n in available if n.lower().endswith("/" + req)]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        if len(suffix_matches) > 1:
            return None

        if "/" in req:
            tail = req.rsplit("/", 1)[1]
            tail_matches = [n for n in available if n.lower() == tail]
            if len(tail_matches) == 1:
                return tail_matches[0]

        return None

    async def get_skill_body(
        self,
        owner_id: uuid.UUID,
        skill_name: str,
        sandbox: BaseSandbox,
    ) -> SkillActivation:
        if sandbox.supports_runtime_skill_listing():
            runtime_activation = await self._get_runtime_skill_body(
                owner_id,
                skill_name,
                sandbox,
            )
            if runtime_activation is not None:
                return runtime_activation

        skill = await self.repo.get_by_owner_and_name(owner_id, skill_name)
        if skill is None:
            all_skills = await self.repo.get_by_owner(owner_id)
            matched_name = self._tolerant_name_match(
                skill_name, [s.name for s in all_skills]
            )
            if matched_name is not None:
                skill = next(s for s in all_skills if s.name == matched_name)
        if skill is None:
            raise SkillNotFoundError(f"Skill '{skill_name}' not found")
        if not skill.is_enabled:
            raise SkillNotFoundError(f"Skill '{skill_name}' is disabled")

        file_list = await sandbox.list_skill_files(owner_id, skill.storage_path)
        manifest_path = self._select_skill_manifest_file(file_list)
        body = await sandbox.read_skill_file(
            owner_id, skill.storage_path, manifest_path
        )

        files = [
            SkillFile(
                relative_path=rel,
                sandbox_path=sandbox.get_skill_sandbox_path(
                    owner_id, skill.storage_path, rel
                ),
            )
            for rel in file_list
            if not self._is_skill_manifest_file(rel)
        ]

        # The body is the full content; strip frontmatter for the agent prompt
        parsed = parse_skill_md(body)

        return SkillActivation(
            name=skill.name,
            sandbox_path=self._get_skill_root_path(
                sandbox,
                owner_id,
                skill.storage_path,
            ),
            body=parsed.body,
            files=files,
        )

    async def _get_runtime_skill_body(
        self,
        owner_id: uuid.UUID,
        skill_name: str,
        sandbox: BaseSandbox,
    ) -> SkillActivation | None:
        all_skills = await sandbox.list_skills(owner_id)
        matched_name = self._tolerant_name_match(
            skill_name, [s.name for s in all_skills]
        )
        if matched_name is None:
            return None
        runtime_skill = next(s for s in all_skills if s.name == matched_name)

        storage_path = runtime_skill.storage_path or self._runtime_skill_storage_path(
            runtime_skill.name
        )
        file_list = await sandbox.list_skill_files(owner_id, storage_path)
        manifest_path = self._select_skill_manifest_file(file_list)
        body = await sandbox.read_skill_file(owner_id, storage_path, manifest_path)
        files = [
            SkillFile(
                relative_path=rel,
                sandbox_path=sandbox.get_skill_sandbox_path(
                    owner_id,
                    storage_path,
                    rel,
                ),
            )
            for rel in file_list
            if not self._is_skill_manifest_file(rel)
        ]
        parsed = parse_skill_md(body)
        return SkillActivation(
            name=runtime_skill.name,
            sandbox_path=self._get_skill_root_path(sandbox, owner_id, storage_path),
            body=parsed.body,
            files=files,
        )

    async def enable_skill(self, owner_id: uuid.UUID, skill_id: uuid.UUID) -> Skill:
        skill = await self._get_owned_skill(owner_id, skill_id)
        updated = await self.repo.update(skill, is_enabled=True)
        await self.invalidate_list_cache(owner_id)
        return updated

    async def disable_skill(self, owner_id: uuid.UUID, skill_id: uuid.UUID) -> Skill:
        skill = await self._get_owned_skill(owner_id, skill_id)
        updated = await self.repo.update(skill, is_enabled=False)
        await self.invalidate_list_cache(owner_id)
        return updated

    async def remove_skill(
        self,
        owner_id: uuid.UUID,
        skill_id: uuid.UUID,
        sandbox: BaseSandbox,
    ) -> None:
        if sandbox.supports_runtime_skill_listing():
            runtime_skill = await self._get_runtime_skill_by_id(
                owner_id,
                skill_id,
                sandbox,
            )
            if runtime_skill is not None:
                storage_path = (
                    runtime_skill.storage_path
                    or self._runtime_skill_storage_path(runtime_skill.name)
                )
                await sandbox.remove_skill_files(owner_id, storage_path)
                await self.invalidate_list_cache(owner_id)
                return

        skill = await self._get_owned_skill(owner_id, skill_id)
        try:
            await sandbox.remove_skill_files(owner_id, skill.storage_path)
        except Exception:
            logger.warning(
                "Failed to remove skill files for %s", skill.name, exc_info=True
            )
        await self.repo.delete(skill)
        await self.invalidate_list_cache(owner_id)

    async def get_skill_detail(
        self,
        owner_id: uuid.UUID,
        skill_id: uuid.UUID,
        sandbox: BaseSandbox,
    ) -> dict:
        if sandbox.supports_runtime_skill_listing():
            runtime_detail = await self._get_runtime_skill_detail(
                owner_id,
                skill_id,
                sandbox,
            )
            if runtime_detail is not None:
                return runtime_detail

        skill = await self._get_owned_skill(owner_id, skill_id)
        try:
            file_list = await sandbox.list_skill_files(owner_id, skill.storage_path)
            manifest_path = self._select_skill_manifest_file(file_list)
            body = await sandbox.read_skill_file(
                owner_id, skill.storage_path, manifest_path
            )
        except (FileNotFoundError, NotImplementedError):
            body = ""
        return {
            "skill": skill,
            "body": body,
        }

    async def _get_runtime_skill_detail(
        self,
        owner_id: uuid.UUID,
        skill_id: uuid.UUID,
        sandbox: BaseSandbox,
    ) -> dict | None:
        for skill in await sandbox.list_skills(owner_id):
            if self._runtime_skill_id(owner_id, skill.name) != skill_id:
                continue

            storage_path = skill.storage_path or self._runtime_skill_storage_path(
                skill.name
            )
            try:
                file_list = await sandbox.list_skill_files(owner_id, storage_path)
                manifest_path = self._select_skill_manifest_file(file_list)
                body = await sandbox.read_skill_file(
                    owner_id,
                    storage_path,
                    manifest_path,
                )
            except (FileNotFoundError, NotImplementedError):
                body = ""

            return {
                "skill": {
                    "id": skill_id,
                    "owner_id": owner_id,
                    "name": skill.name,
                    "description": skill.description,
                    "source_type": SkillSourceType.LOCAL_DIR,
                    "source_url": skill.source_url,
                    "storage_path": storage_path,
                    "is_enabled": True,
                    "metadata": {"runtime": True},
                    "created_at": _RUNTIME_SKILL_CREATED_AT,
                    "updated_at": _RUNTIME_SKILL_CREATED_AT,
                },
                "body": body,
            }
        return None

    async def _get_runtime_skill_by_id(
        self,
        owner_id: uuid.UUID,
        skill_id: uuid.UUID,
        sandbox: BaseSandbox,
    ):
        for skill in await sandbox.list_skills(owner_id):
            if self._runtime_skill_id(owner_id, skill.name) == skill_id:
                return skill
        return None

    async def _get_owned_skill(self, owner_id: uuid.UUID, skill_id: uuid.UUID) -> Skill:
        skill = await self.repo.get_by_id(skill_id)
        if skill is None or skill.owner_id != owner_id:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")
        return skill

    @staticmethod
    def _extract_archive(archive_bytes: bytes, filename: str, dest: Path) -> None:
        lower = filename.lower()
        if lower.endswith(".zip"):
            import io

            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
                zf.extractall(dest)
        elif lower.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
            import io

            with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as tf:
                tf.extractall(dest, filter="data")
        else:
            raise SkillInstallError(
                f"Unsupported archive format: {filename}. Use .zip or .tar.gz"
            )

    @staticmethod
    def _find_skill_root(extracted: Path) -> Path:
        """Find the directory containing a skill manifest in an extracted archive."""
        if find_skill_manifest_path(extracted) is not None:
            return extracted
        # Check one level of nesting (common in archives)
        for child in extracted.iterdir():
            if child.is_dir() and find_skill_manifest_path(child) is not None:
                return child
        raise SkillInstallError(
            "Skill manifest not found in archive (checked root and one level deep)"
        )

    @staticmethod
    def _find_skill_manifest_path(directory: Path) -> Path:
        skill_md_path = find_skill_manifest_path(directory)
        if skill_md_path is None:
            raise SkillInstallError(
                "Skill manifest file not found. Expected SKILL.md or casing variants"
            )
        return skill_md_path

    @staticmethod
    def _select_skill_manifest_file(file_list: list[str]) -> str:
        manifest_path = select_skill_manifest_file(file_list)
        if manifest_path is None:
            raise FileNotFoundError(
                "Skill manifest file not found. Expected SKILL.md or casing variants"
            )
        return manifest_path

    @staticmethod
    def _is_skill_manifest_file(relative_path: str) -> bool:
        return (
            "/" not in relative_path
            and "\\" not in relative_path
            and is_skill_manifest_filename(Path(relative_path).name)
        )

    @staticmethod
    def _hash_skill_md(directory: Path) -> str:
        path = find_skill_manifest_path(directory)
        if path is None:
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
