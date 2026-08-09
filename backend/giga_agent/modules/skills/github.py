from __future__ import annotations

import base64
import hashlib
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import httpx

from giga_agent.models.skill import Skill, SkillSourceType
from giga_agent.modules.skills.parser import parse_skill_md
from giga_agent.modules.skills.service import SkillInstallError, SkillsService

GITHUB_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_GITHUB_SKILL_FILES = 256
MAX_GITHUB_SKILL_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class GithubSkillInstall:
    skill: Skill
    resolved_commit: str
    content_hash: str


def _headers() -> dict[str, str]:
    result = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "giga-agent-skill-installer",
    }
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        result["Authorization"] = f"Bearer {token}"
    return result


async def _github_json(client: httpx.AsyncClient, url: str) -> dict:
    response = await client.get(url)
    if response.status_code >= 400:
        raise SkillInstallError(
            f"GitHub request failed ({response.status_code}) for {url}"
        )
    value = response.json()
    if not isinstance(value, dict):
        raise SkillInstallError("Unexpected GitHub response")
    return value


async def install_github_skill(
    service: SkillsService,
    *,
    owner_id: uuid.UUID,
    requirement_name: str,
    source: str,
    ref: str | None,
    sandbox,
) -> GithubSkillInstall:
    """Install one skill using GitHub's tree/blob APIs, never executing repository code."""

    if not GITHUB_SOURCE_RE.fullmatch(source):
        raise SkillInstallError("GitHub source must use owner/repository syntax")
    requested_ref = ref or "HEAD"
    api = f"https://api.github.com/repos/{source}"
    async with httpx.AsyncClient(
        headers=_headers(), follow_redirects=False, timeout=30.0
    ) as client:
        commit = await _github_json(client, f"{api}/commits/{requested_ref}")
        commit_sha = str(commit.get("sha") or "")
        tree_sha = str(
            ((commit.get("commit") or {}).get("tree") or {}).get("sha") or ""
        )
        if not commit_sha or not tree_sha:
            raise SkillInstallError("GitHub commit does not contain a tree")
        tree = await _github_json(client, f"{api}/git/trees/{tree_sha}?recursive=1")
        entries = tree.get("tree")
        if not isinstance(entries, list) or tree.get("truncated"):
            raise SkillInstallError("GitHub repository tree is too large or truncated")

        manifests: list[str] = []
        blobs: dict[str, dict] = {}
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            path = str(entry.get("path") or "")
            blobs[path] = entry
            if PurePosixPath(path).name.lower() == "skill.md" and (
                PurePosixPath(path).parent.name == requirement_name
                or path == "SKILL.md"
            ):
                manifests.append(path)
        if len(manifests) != 1:
            raise SkillInstallError(
                f"Expected one SKILL.md for {requirement_name!r}, found {len(manifests)}"
            )
        root = PurePosixPath(manifests[0]).parent
        selected = {
            path: entry
            for path, entry in blobs.items()
            if PurePosixPath(path).is_relative_to(root)
        }
        if len(selected) > MAX_GITHUB_SKILL_FILES:
            raise SkillInstallError("GitHub skill contains too many files")
        declared_bytes = sum(int(entry.get("size") or 0) for entry in selected.values())
        if declared_bytes > MAX_GITHUB_SKILL_BYTES:
            raise SkillInstallError("GitHub skill exceeds the allowed size")

        with tempfile.TemporaryDirectory(prefix="github_skill_") as tmp:
            skill_root = Path(tmp) / "skill"
            skill_root.mkdir()
            digest = hashlib.sha256()
            total = 0
            for source_path, entry in sorted(selected.items()):
                relative = PurePosixPath(source_path).relative_to(root)
                if relative.is_absolute() or ".." in relative.parts:
                    raise SkillInstallError("Unsafe GitHub skill path")
                blob = await _github_json(client, str(entry.get("url") or ""))
                if blob.get("encoding") != "base64":
                    raise SkillInstallError("Unsupported GitHub blob encoding")
                try:
                    encoded = "".join(str(blob.get("content") or "").split())
                    content = base64.b64decode(encoded, validate=True)
                except ValueError as exc:
                    raise SkillInstallError("Invalid GitHub blob content") from exc
                total += len(content)
                if total > MAX_GITHUB_SKILL_BYTES:
                    raise SkillInstallError("GitHub skill exceeds the allowed size")
                target = (skill_root / Path(*relative.parts)).resolve()
                if not target.is_relative_to(skill_root.resolve()):
                    raise SkillInstallError("Unsafe GitHub skill path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                digest.update(str(relative).encode())
                digest.update(b"\0")
                digest.update(content)

            manifest = service._find_skill_manifest_path(skill_root)
            parsed = parse_skill_md(manifest.read_text(encoding="utf-8"))
            if parsed.name != requirement_name:
                raise SkillInstallError(
                    f"Skill name mismatch: expected {requirement_name!r}, got {parsed.name!r}"
                )
            existing = await service.repo.get_by_owner_and_name(owner_id, parsed.name)
            metadata = {
                **parsed.metadata,
                "github_source": source,
                "github_ref": requested_ref,
                "resolved_commit": commit_sha,
                "content_hash": digest.hexdigest(),
            }
            if existing is not None:
                old = existing.metadata_ or {}
                if (
                    existing.source_type == SkillSourceType.GITHUB
                    and old.get("github_source") == source
                    and old.get("resolved_commit") == commit_sha
                    and old.get("content_hash") == digest.hexdigest()
                ):
                    return GithubSkillInstall(existing, commit_sha, digest.hexdigest())
                raise SkillInstallError(
                    f"Skill {parsed.name!r} already exists from another source or commit"
                )
            storage_path = await sandbox.install_skill_files(
                owner_id, parsed.name, skill_root
            )
            skill = await service.repo.create(
                owner_id=owner_id,
                name=parsed.name,
                description=parsed.description,
                source_type=SkillSourceType.GITHUB,
                source_url=f"https://github.com/{source}/tree/{commit_sha}/{root}",
                storage_path=storage_path,
                metadata_=metadata,
            )
            if skill is None:
                raise SkillInstallError(f"Skill {parsed.name!r} already exists")
            await service.invalidate_list_cache(owner_id)
            return GithubSkillInstall(skill, commit_sha, digest.hexdigest())
