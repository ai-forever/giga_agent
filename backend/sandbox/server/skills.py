"""FS-backed skills API.

ВАЖНО ПРО ГРАНИЦЫ ПРИМЕНИМОСТИ.
Это самостоятельная механика скиллов, живущих прямо в файловой системе
песочницы, — для НАТИВНОГО провайдера ``sandbox_api``. Когда local_docker и e2b
переедут на это API, их skill-операции сюда НЕ ходят: у них своя
персистентность (локальная FS с cashews / S3 с cashews), и клиентская сторона
продолжает обслуживать скиллы сама. Сервер просто предлагает опциональный
FS-based skills-API; он ничего не знает о провайдерах.

Семантика повторяет giga_agent.sandbox.base (install/read/list/remove +
runtime-листинг), а формат манифеста — giga_agent.modules.skills.parser
(YAML-frontmatter ``name``/``description`` в SKILL.md/skill.md/Skill.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import aiofiles
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import PlainTextResponse

from .auth import require_token
from .config import get_settings
from .models import (
    SkillFilesResponse,
    SkillInfo,
    SkillInstalledResponse,
    SkillListResponse,
)

# --- manifest detection (портирование giga_agent.modules.skills.manifest) --- #

_MANIFEST_PRIORITY = {"SKILL.md": 0, "skill.md": 1, "Skill.md": 2}
_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_manifest(name: str) -> bool:
    return name.lower() == "skill.md"


def _find_manifest(directory: Path) -> Path | None:
    matches = [c for c in directory.iterdir() if c.is_file() and _is_manifest(c.name)]
    if not matches:
        return None
    return min(
        matches,
        key=lambda p: (_MANIFEST_PRIORITY.get(p.name, 99), p.name.lower(), p.name),
    )


@dataclass(frozen=True, slots=True)
class _ParsedManifest:
    name: str
    description: str


def _parse_manifest(content: str) -> _ParsedManifest | None:
    """Минимальный парсер YAML-frontmatter: нужны только name/description."""
    content = content.strip()
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    frontmatter = content[3:end]
    try:
        import yaml

        data = yaml.safe_load(frontmatter) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    description = data.get("description", "")
    if not isinstance(description, str):
        description = str(description)
    return _ParsedManifest(name=name.strip(), description=description.strip())


# --------------------------------------------------------------------------- #
# manager
# --------------------------------------------------------------------------- #


def _validate_skill_name(skill_name: str) -> str:
    clean = skill_name.strip()
    if not clean or not _SEGMENT_RE.match(clean) or clean in {".", ".."}:
        raise HTTPException(
            status_code=400, detail=f"Invalid skill name: {skill_name!r}"
        )
    return clean


def _validate_relative(relative_path: str) -> Path:
    clean = relative_path.strip().replace("\\", "/").lstrip("/")
    rel = Path(clean)
    if not clean or any(part in {"", ".", ".."} for part in rel.parts):
        raise HTTPException(
            status_code=400, detail=f"Invalid relative path: {relative_path!r}"
        )
    return rel


class SkillsManager:
    def __init__(self, settings=None) -> None:
        self._settings = settings or get_settings()

    def _root(self, owner_id: str | None) -> Path:
        base = Path(self._settings.skills_root)
        if owner_id:
            base = base / _validate_skill_name(owner_id)
        return base

    def _skill_dir(self, owner_id: str | None, skill_name: str) -> Path:
        return self._root(owner_id) / _validate_skill_name(skill_name)

    @staticmethod
    def _storage_path(skill_name: str) -> str:
        return f"skills/{skill_name}"

    def _list_files(self, skill_dir: Path) -> list[str]:
        if not skill_dir.is_dir():
            return []
        out: list[str] = []
        for p in skill_dir.rglob("*"):
            if p.is_file():
                out.append(p.relative_to(skill_dir).as_posix())
        out.sort()
        return out

    # -- install (from a streamed tar archive) --

    def install_from_tar(
        self, owner_id: str | None, skill_name: str, tar_path: str
    ) -> SkillInstalledResponse:
        skill_name = _validate_skill_name(skill_name)
        dest = self._skill_dir(owner_id, skill_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(name=tar_path, mode="r:*") as tar:
                # filter="data" (py3.12) блокирует абсолютные пути, ".." и спецфайлы
                tar.extractall(path=dest, filter="data")
        except tarfile.TarError as exc:
            shutil.rmtree(dest, ignore_errors=True)
            raise HTTPException(
                status_code=400, detail=f"Invalid tar archive: {exc}"
            ) from exc

        # если архив содержал единственную обёрточную папку — разворачиваем её
        self._flatten_single_wrapper_dir(dest)

        return SkillInstalledResponse(
            name=skill_name,
            storage_path=self._storage_path(skill_name),
            sandbox_path=str(dest.resolve()),
            files=self._list_files(dest),
        )

    @staticmethod
    def _flatten_single_wrapper_dir(dest: Path) -> None:
        entries = list(dest.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            inner = entries[0]
            for child in inner.iterdir():
                shutil.move(str(child), str(dest / child.name))
            inner.rmdir()

    # -- list / read / remove --

    def list_skills(self, owner_id: str | None) -> list[SkillInfo]:
        root = self._root(owner_id)
        if not root.is_dir():
            return []
        result: list[SkillInfo] = []
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            manifest = _find_manifest(entry)
            if manifest is None:
                continue
            try:
                parsed = _parse_manifest(manifest.read_text(encoding="utf-8"))
            except OSError:
                parsed = None
            if parsed is None:
                continue
            result.append(
                SkillInfo(
                    name=parsed.name,
                    description=parsed.description,
                    storage_path=self._storage_path(entry.name),
                    sandbox_path=str(entry.resolve()),
                )
            )
        return result

    def list_files(self, owner_id: str | None, skill_name: str) -> SkillFilesResponse:
        skill_dir = self._skill_dir(owner_id, skill_name)
        if not skill_dir.is_dir():
            raise HTTPException(
                status_code=404, detail=f"Skill not found: {skill_name}"
            )
        return SkillFilesResponse(
            name=skill_name,
            storage_path=self._storage_path(skill_name),
            sandbox_path=str(skill_dir.resolve()),
            files=self._list_files(skill_dir),
        )

    def read_file(
        self, owner_id: str | None, skill_name: str, relative_path: str
    ) -> str:
        skill_dir = self._skill_dir(owner_id, skill_name).resolve()
        rel = _validate_relative(relative_path)
        target = (skill_dir / rel).resolve()
        if skill_dir != target and skill_dir not in target.parents:
            raise HTTPException(status_code=400, detail="Path escapes skill directory")
        if not target.is_file():
            raise HTTPException(
                status_code=404, detail=f"Skill file not found: {relative_path}"
            )
        return target.read_text(encoding="utf-8")

    def remove(self, owner_id: str | None, skill_name: str) -> bool:
        skill_dir = self._skill_dir(owner_id, skill_name)
        if not skill_dir.is_dir():
            return False
        shutil.rmtree(skill_dir, ignore_errors=True)
        return True


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #

router = APIRouter(
    prefix="/v1/skills", tags=["skills"], dependencies=[Depends(require_token)]
)


def _mgr(request: Request) -> SkillsManager:
    return request.app.state.skills_manager


@router.get("", response_model=SkillListResponse)
async def list_skills(request: Request, owner_id: str | None = Query(default=None)):
    return SkillListResponse(skills=_mgr(request).list_skills(owner_id))


@router.put("/{skill_name}", response_model=SkillInstalledResponse)
async def install_skill(
    skill_name: str,
    request: Request,
    owner_id: str | None = Query(default=None),
):
    """Загрузить/заменить скилл. Тело запроса — tar/tar.gz архив с файлами
    скилла (SKILL.md в корне, опционально scripts/, references/ и т.д.).

    Тело стримится во временный файл, а не грузится целиком в память —
    распаковка идёт с диска."""
    fd, tmp_path = tempfile.mkstemp(prefix="skill-", suffix=".tar")
    os.close(fd)
    written = 0
    try:
        async with aiofiles.open(tmp_path, "wb") as handle:
            async for chunk in request.stream():
                if chunk:
                    await handle.write(chunk)
                    written += len(chunk)
        if written == 0:
            raise HTTPException(
                status_code=400, detail="empty request body (expected tar archive)"
            )
        return await asyncio.to_thread(
            _mgr(request).install_from_tar, owner_id, skill_name, tmp_path
        )
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp_path)


@router.get("/{skill_name}/files", response_model=SkillFilesResponse)
async def list_skill_files(
    skill_name: str, request: Request, owner_id: str | None = Query(default=None)
):
    return _mgr(request).list_files(owner_id, skill_name)


@router.get("/{skill_name}/file", response_class=PlainTextResponse)
async def read_skill_file(
    skill_name: str,
    request: Request,
    path: str = Query(..., description="relative path inside the skill"),
    owner_id: str | None = Query(default=None),
):
    return PlainTextResponse(_mgr(request).read_file(owner_id, skill_name, path))


@router.delete("/{skill_name}")
async def remove_skill(
    skill_name: str, request: Request, owner_id: str | None = Query(default=None)
):
    removed = _mgr(request).remove(owner_id, skill_name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    return {"name": skill_name, "removed": True}
