from __future__ import annotations

import asyncio
import mimetypes
import os
import platform
import secrets
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import aiofiles
import aiofiles.os
from langchain_core.runnables import RunnableConfig
from pydantic import Field, PrivateAttr

from giga_agent.conf import get_settings
from giga_agent.core.paths import ensure_giga_agent_dir
from giga_agent.models.sandbox import SandboxStatus
from giga_agent.sandbox.base import (
    LARGE_FILE_THRESHOLD,
    ContentResult,
    FileReadResult,
    RuntimeSkillInfo,
    StreamResult,
)
from giga_agent.sandbox.jupyter import JupyterSandbox
from giga_agent.sandbox.local_jupyter.dependencies import ensure_jupyter_dependencies
from giga_agent.sandbox.local_jupyter.manager import (
    LOCAL_JUPYTER_KERNEL_NAME,
    get_local_jupyter_server_manager,
)
from giga_agent.sandbox.local_jupyter.shell import LocalShellMixin
from giga_agent.sandbox.manager.types import SetSandboxStatusAction
from giga_agent.sandbox.registry import SandboxRegistry
from giga_agent.sandbox.secure_exec.policy import (
    NetworkMode,
    SandboxAccessPolicy,
    default_package_cache_write_roots,
    python_virtual_env_write_roots,
)

if TYPE_CHECKING:
    from giga_agent.core.agent.base import BaseAgent
    from giga_agent.core.agent.types import AgentState
    from giga_agent.models.users import UserShort

BUCKET_PREFIX = "/bucket/"
_EXTERNAL_AGENT_SKILL_PREFIX = "external/agent/"
_EXTERNAL_AGENT_SKILL_NAMESPACE = "agent/"
_LOCAL_FILE_SUFFIX_ALPHABET = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
)


def _describe_local_os() -> str:
    system = platform.system()
    if system == "Darwin":
        system = "macOS"
    elif not system:
        system = "Unknown OS"

    release = platform.release().strip()
    machine = platform.machine().strip() or "unknown-arch"

    if release:
        return f"{system} {release} ({machine})"
    return f"{system} ({machine})"


def _describe_shell() -> str:
    shell_path = os.environ.get("SHELL") or os.environ.get("COMSPEC") or ""
    shell_name = Path(shell_path).name if shell_path else ""

    if os.name == "nt":
        return shell_name or "cmd/PowerShell-compatible shell"
    return shell_name or "POSIX-compatible shell"


def _resolve_thread_id(config: RunnableConfig | None) -> str | None:
    if not isinstance(config, dict):
        return None

    metadata = config.get("metadata", {})
    thread_id = metadata.get("thread_id")
    if isinstance(thread_id, str) and thread_id.strip():
        return thread_id.strip().strip("/")

    configurable = config.get("configurable", {})
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str) and thread_id.strip():
        return thread_id.strip().strip("/")

    return None


def _format_directory(path: Path) -> str:
    return f"{path.as_posix().rstrip('/')}/"


def _default_exclude_read_dirs() -> list[str]:
    return [str((Path.home() / ".ssh").resolve())]


@SandboxRegistry.register("local_jupyter")
class LocalJupyterSandbox(LocalShellMixin, JupyterSandbox):
    owner_id: uuid.UUID | None = Field(
        default=None,
        description="Sandbox owner id injected by runtime factory",
    )
    external_id: str | None = Field(
        default=None,
        description="Managed Jupyter process pid",
    )
    jupyter_token: str | None = Field(
        default=None,
        description="Managed Jupyter auth token",
    )
    runtime_dir: str | None = Field(
        default=None,
        description="Managed Jupyter runtime directory",
    )
    base_url: str = Field(
        default="",
        description="Base URL of the managed local Jupyter server",
    )
    safe_execution: bool = Field(
        default_factory=lambda: (
            get_settings().giga_agent_local_jupyter_secure_exec_default
        ),
        description="Run local Jupyter processes under OS-level filesystem sandboxing",
    )
    write_dirs: list[str] = Field(
        default_factory=list,
        description="Additional host directories explicitly granted for writes",
    )
    exclude_read_dirs: list[str] = Field(
        default_factory=_default_exclude_read_dirs,
        description="Additional host directories explicitly denied for reads",
    )

    _runtime_fields = JupyterSandbox._runtime_fields | {
        "owner_id",
        "jupyter_token",
        "runtime_dir",
    }
    _sandbox_root_dir: Path = PrivateAttr(default_factory=Path)

    def model_post_init(self, __context: Any) -> None:
        if self.jupyter_token:
            self._token = self.jupyter_token

        root_dir_raw = get_settings().giga_agent_local_jupyter_files_path
        if root_dir_raw:
            self._sandbox_root_dir = Path(root_dir_raw).expanduser().resolve()
        else:
            self._sandbox_root_dir = (
                ensure_giga_agent_dir() / "local_jupyter" / "files"
            ).resolve()

    @classmethod
    async def validate_settings(cls, settings: dict) -> dict:
        schema = cls.settings_schema()
        validated = schema(**settings).model_dump(
            exclude_none=True,
            exclude_defaults=True,
        )
        ensure_jupyter_dependencies()

        return validated

    def get_connection_settings(self) -> dict:
        settings: dict[str, Any] = {
            "external_id": self.external_id,
            "jupyter_token": self._token or self.jupyter_token,
            "runtime_dir": self.runtime_dir,
            "base_url": self.base_url or None,
        }
        return {key: value for key, value in settings.items() if value is not None}

    def _recommended_workdir(self, config: RunnableConfig | None) -> Path:
        thread_id = _resolve_thread_id(config)
        if thread_id:
            return (self._sandbox_root_dir / thread_id).resolve()
        return self._sandbox_root_dir.resolve()

    def get_prompt(
        self,
        user: "UserShort | None" = None,
        agent: "BaseAgent | None" = None,
        state: "AgentState | None" = None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str:
        _ = user, agent, state, kwargs
        python_version = platform.python_version()
        # workdir = self._recommended_workdir(config)

        # workdir_prompt = (
        #     f"- Директория для сохранения файлов: {_format_directory(workdir)}\n"
        #     "- Старайся сохранять создаваемые файлы именно в эту директорию и по "
        #     "возможности использовать пути относительно неё.\n"
        # )

        return (
            "\nОсобенности локального окружения выполнения:\n"
            f"- ОС и платформа: {_describe_local_os()}.\n"
            f"- Python runtime: Python {python_version}.\n"
            f"- Shell и команды должны быть совместимы с {_describe_shell()}.\n"
            # + workdir_prompt
            + "- Это локальное окружение пользователя, поэтому учитывай OS-specific "
            "синтаксис команд, доступность утилит и различия между macOS/Linux/Windows.\n"
            + "- При выборе зависимостей и бинарников учитывай архитектуру CPU и "
            "совместимость с локальной ОС.\n"
        )

    def _get_kernel_request_payload(self) -> dict[str, Any] | None:
        return {"name": LOCAL_JUPYTER_KERNEL_NAME}

    async def up(self) -> None:
        ensure_jupyter_dependencies()
        policy = (
            self._build_access_policy(network_mode="host")
            if self.safe_execution
            else None
        )
        handle = await get_local_jupyter_server_manager().ensure_started(
            safe_execution=self.safe_execution,
            policy=policy,
            secure_exec_backend=get_settings().giga_agent_local_jupyter_secure_exec_backend,
        )
        self.base_url = handle.base_url
        self.runtime_dir = handle.runtime_dir
        self._token = handle.token
        self.jupyter_token = handle.token
        self.external_id = str(handle.pid)

    async def stop(self) -> None:
        return None

    async def is_up(self) -> bool:
        if not self.base_url or not self._token:
            handle = await get_local_jupyter_server_manager().get_active_handle()
            if handle is None:
                return False
            self.base_url = handle.base_url
            self.runtime_dir = handle.runtime_dir
            self._token = handle.token
            self.jupyter_token = handle.token
            self.external_id = str(handle.pid)
        return await super().is_up()

    @classmethod
    async def cleanup_orphans(
        cls,
        *,
        providers: list[Any],
        sandboxes: list[Any],
    ) -> list[SetSandboxStatusAction]:
        del providers
        handle = await get_local_jupyter_server_manager().get_active_handle()
        if handle is not None:
            return []

        actions: list[SetSandboxStatusAction] = []
        for sandbox in sandboxes:
            if sandbox.status not in (
                SandboxStatus.RUNNING,
                SandboxStatus.STARTING,
                SandboxStatus.STOPPING,
            ):
                continue
            actions.append(
                SetSandboxStatusAction(
                    provider_type="local_jupyter",
                    provider_id=sandbox.provider_id,
                    sandbox_id=sandbox.id,
                    status=SandboxStatus.STOPPED,
                    reason="managed_local_jupyter_server_missing",
                    clear_runtime_connection=True,
                )
            )
        return actions

    @classmethod
    async def stop_external_runtime(cls, external_id: str) -> None:
        try:
            pid = int(external_id)
        except ValueError:
            return
        await get_local_jupyter_server_manager().stop_pid(pid)

    async def upload_file(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
        content: bytes,
    ) -> str:
        rel_path = self._uniquify_bucket_rel_path(
            owner_id=owner_id, file_name=file_name
        )
        target = self._user_root_dir(owner_id) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "wb") as file_obj:
            await file_obj.write(content)
        return str(target.resolve())

    def requires_running_for_upload(self) -> bool:
        return False

    async def read_file(self, sandbox_path: str) -> FileReadResult:
        local_path = self._resolve_readable_path(sandbox_path)
        self._build_access_policy().assert_can_read(local_path)
        if not local_path.exists() or not local_path.is_file():
            raise FileNotFoundError(f"File not found: {sandbox_path}")

        media_type, _ = mimetypes.guess_type(local_path.name)
        if not media_type:
            media_type = "application/octet-stream"
        inline = local_path.suffix.lower() in {".html", ".htm"}

        size = local_path.stat().st_size
        if size >= LARGE_FILE_THRESHOLD:
            return StreamResult(
                stream=self._stream_local_file(local_path),
                media_type=media_type,
                inline=inline,
                content_length=size,
            )

        async with aiofiles.open(local_path, "rb") as file_obj:
            data = await file_obj.read()

        return ContentResult(data=data, media_type=media_type, inline=inline)

    def requires_running_for_read(self, sandbox_path: str) -> bool:
        return False

    async def delete_file(self, sandbox_path: str) -> None:
        local_path = self._resolve_readable_path(sandbox_path)
        self._build_access_policy().assert_can_delete(local_path)
        try:
            await aiofiles.os.remove(local_path)
        except FileNotFoundError:
            pass

    def requires_running_for_delete(self, sandbox_path: str) -> bool:
        return False

    async def write_file_content(self, sandbox_path: str, content: bytes) -> None:
        local_path = self._resolve_readable_path(sandbox_path)
        self._build_access_policy().assert_can_write(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(local_path, "wb") as file_obj:
            await file_obj.write(content)

    async def file_exists(self, sandbox_path: str) -> bool:
        local_path = self._resolve_readable_path(sandbox_path)
        self._build_access_policy().assert_can_read(local_path)
        return local_path.exists() and local_path.is_file()

    def requires_running_for_write(self, sandbox_path: str) -> bool:
        return False

    def requires_running_for_file_exists(self, sandbox_path: str) -> bool:
        return False

    async def _stream_local_file(
        self,
        path: Path,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        async with aiofiles.open(path, "rb") as file_obj:
            while True:
                chunk = await file_obj.read(chunk_size)
                if not chunk:
                    break
                yield chunk
                await asyncio.sleep(0)

    def _validate_relative_file_name(self, file_name: str) -> PurePosixPath:
        clean = file_name.strip().replace("\\", "/").lstrip("/")
        path = PurePosixPath(clean)
        if path.name in {"", ".", ".."}:
            raise ValueError("file_name must contain a valid file name")
        if any(part in {".", ".."} for part in path.parts):
            raise ValueError("file_name must not contain '.' or '..' path segments")
        return path

    def _uniquify_bucket_rel_path(
        self,
        *,
        owner_id: uuid.UUID,
        file_name: str,
    ) -> PurePosixPath:
        path = self._validate_relative_file_name(file_name)
        plotly_json_suffix = ".plotly.json"
        name = path.name
        if name.lower().endswith(plotly_json_suffix) and len(name) > len(
            plotly_json_suffix
        ):
            suffix_start = len(name) - len(plotly_json_suffix)
            stem = name[:suffix_start]
            suffix = name[suffix_start:]
        else:
            stem = path.stem or path.name
            suffix = path.suffix

        parent = path.parent
        parent_parts = (
            []
            if str(parent) in {"", "."}
            else [part for part in parent.parts if part not in {"", "."}]
        )
        user_root = self._user_root_dir(owner_id)
        for _ in range(10):
            suffix_id = self._random_key_suffix()
            candidate_name = (
                f"{stem}--{suffix_id}{suffix}" if suffix else f"{stem}--{suffix_id}"
            )
            rel_path = (
                PurePosixPath(*parent_parts, candidate_name)
                if parent_parts
                else PurePosixPath(candidate_name)
            )
            target = user_root / Path(*rel_path.parts)
            if not target.exists():
                return rel_path

        raise RuntimeError(
            "Failed to generate unique local upload file name after retries"
        )

    def _random_key_suffix(self) -> str:
        return "".join(secrets.choice(_LOCAL_FILE_SUFFIX_ALPHABET) for _ in range(8))

    def _user_root_dir(self, owner_id: uuid.UUID) -> Path:
        root = self._sandbox_root_dir
        root.mkdir(parents=True, exist_ok=True)
        user_root = (root / str(owner_id)).resolve()
        user_root.mkdir(parents=True, exist_ok=True)
        return user_root

    def _build_access_policy(
        self,
        *,
        cwd: Path | str | None = None,
        network_mode: NetworkMode | None = None,
    ) -> SandboxAccessPolicy:
        settings = get_settings()
        manager = get_local_jupyter_server_manager()
        workspace_root = manager._working_dir()
        runtime_roots = [
            manager._runtime_dir(),
            manager._config_dir(),
            manager._data_dir(),
            manager._shims_dir(),
            manager._shell_sessions_root(),
            self._sandbox_root_dir,
        ]
        write_roots = [
            *default_package_cache_write_roots(),
            *python_virtual_env_write_roots(manager._python_executable()),
            *settings.giga_agent_local_jupyter_allowed_write_roots,
            *[Path(path) for path in self.write_dirs],
        ]
        deny_roots = [
            *settings.giga_agent_local_jupyter_deny_read_roots,
            *[Path(path) for path in self.exclude_read_dirs],
        ]
        return SandboxAccessPolicy(
            workspace_root=workspace_root,
            runtime_roots=runtime_roots,
            read_roots=settings.giga_agent_local_jupyter_allowed_read_roots,
            write_roots=write_roots,
            deny_roots=deny_roots,
            cwd=Path(cwd) if cwd is not None else None,
            network_mode=network_mode or settings.giga_agent_local_jupyter_network_mode,
        )

    def _local_path_from_bucket_path(self, sandbox_path: str) -> Path:
        if self.owner_id is None:
            raise RuntimeError("owner_id is required to resolve sandbox path")
        if not sandbox_path.startswith(BUCKET_PREFIX):
            raise ValueError(f"Invalid bucket path: {sandbox_path}")

        key = sandbox_path[len(BUCKET_PREFIX) :].strip("/")
        if not key:
            raise ValueError(f"Invalid bucket path: {sandbox_path}")

        rel = PurePosixPath(key)
        if any(part in {".", ".."} for part in rel.parts):
            raise ValueError(f"Invalid bucket path: {sandbox_path}")

        user_root = self._user_root_dir(self.owner_id).resolve()
        local_path = (user_root / Path(*rel.parts)).resolve()
        if user_root != local_path and user_root not in local_path.parents:
            raise ValueError(f"Path escapes user sandbox root: {sandbox_path}")
        return local_path

    def _resolve_readable_path(self, sandbox_path: str) -> Path:
        if sandbox_path.startswith(BUCKET_PREFIX):
            return self._local_path_from_bucket_path(sandbox_path)
        return Path(sandbox_path).expanduser().resolve()

    # ---- Skill file operations ----

    def _skill_dir(self, owner_id: uuid.UUID, skill_name: str) -> Path:
        return self._user_root_dir(owner_id) / "skills" / skill_name

    @staticmethod
    def _external_agent_skills_dir() -> Path:
        return (Path.home() / ".agents" / "skills").expanduser().resolve()

    @classmethod
    def _external_agent_skill_dirs(cls) -> list[Path]:
        roots = [
            cls._external_agent_skills_dir(),
            (Path.home() / ".agent" / "skills").expanduser().resolve(),
        ]
        result: list[Path] = []
        for root in roots:
            if root not in result:
                result.append(root)
        return result

    @staticmethod
    def _external_agent_skill_name(skill_name: str) -> str:
        return f"{_EXTERNAL_AGENT_SKILL_NAMESPACE}{skill_name}"

    def _external_agent_skill_dir(self, storage_path: str) -> Path:
        rel = PurePosixPath(storage_path)
        if (
            len(rel.parts) != 3
            or rel.parts[0] != "external"
            or rel.parts[1] != "agent"
            or rel.parts[2] in {"", ".", ".."}
        ):
            raise ValueError(f"Invalid external skill storage path: {storage_path}")

        fallback: Path | None = None
        for root in self._external_agent_skill_dirs():
            skill_dir = (root / rel.parts[2]).resolve()
            if root != skill_dir and root not in skill_dir.parents:
                raise ValueError(
                    f"External skill path escapes skills root: {storage_path}"
                )
            if fallback is None:
                fallback = skill_dir
            if skill_dir.exists():
                return skill_dir
        if fallback is None:
            raise ValueError(f"No external skill roots configured: {storage_path}")
        return fallback

    def _resolve_skill_dir(self, owner_id: uuid.UUID, storage_path: str) -> Path:
        if storage_path.startswith(_EXTERNAL_AGENT_SKILL_PREFIX):
            return self._external_agent_skill_dir(storage_path)

        skill_name = storage_path.split("/")[-1]
        return self._skill_dir(owner_id, skill_name)

    async def install_skill_files(
        self,
        owner_id: uuid.UUID,
        skill_name: str,
        source_dir: str | Path,
    ) -> str:
        source = Path(source_dir)
        if not source.is_dir():
            raise FileNotFoundError(f"Source directory not found: {source}")
        dest = self._skill_dir(owner_id, skill_name)
        if dest.exists():
            shutil.rmtree(dest)
        await asyncio.to_thread(shutil.copytree, source, dest)
        return f"skills/{skill_name}"

    async def read_skill_file(
        self, owner_id: uuid.UUID, storage_path: str, relative_path: str
    ) -> str:
        file_path = self._resolve_skill_dir(owner_id, storage_path) / relative_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Skill file not found: {relative_path}")
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            return await f.read()

    async def list_skill_files(
        self, owner_id: uuid.UUID, storage_path: str
    ) -> list[str]:
        skill_dir = self._resolve_skill_dir(owner_id, storage_path)
        if not skill_dir.is_dir():
            return []
        result: list[str] = []
        for root, _dirs, files in os.walk(skill_dir):
            for fname in files:
                full = Path(root) / fname
                result.append(str(full.relative_to(skill_dir)))
        return sorted(result)

    async def remove_skill_files(self, owner_id: uuid.UUID, storage_path: str) -> None:
        skill_dir = self._resolve_skill_dir(owner_id, storage_path)
        if skill_dir.is_dir():
            await asyncio.to_thread(shutil.rmtree, skill_dir)

    def get_skill_sandbox_path(
        self, owner_id: uuid.UUID, storage_path: str, relative_path: str
    ) -> str:
        return str(self._resolve_skill_dir(owner_id, storage_path) / relative_path)

    def supports_runtime_skill_listing(self) -> bool:
        return True

    async def list_skills(self, owner_id: uuid.UUID) -> list[RuntimeSkillInfo]:
        found = await self.scan_skill_dirs(owner_id)
        return [
            RuntimeSkillInfo(
                name=info["name"],
                description=info["description"],
                storage_path=info["storage_path"],
                source_url=info["source_dir"],
            )
            for info in found
        ]

    async def scan_skill_dirs(
        self,
        owner_id: uuid.UUID,
        extra_dirs: list[str] | None = None,
        include_agent_skills: bool = True,
    ) -> list[dict]:
        """
        Scan the user skills directory (and optionally extra dirs)
        for folders containing SKILL.md. Returns list of dicts with
        ``name``, ``description``, ``source_dir``, ``storage_path``.
        """
        from giga_agent.modules.skills.parser import parse_skill_md, SkillParseError

        dirs_to_scan: list[tuple[Path, str]] = []
        user_skills = self._user_root_dir(owner_id) / "skills"
        if user_skills.is_dir():
            dirs_to_scan.append((user_skills, "sandbox"))
        if include_agent_skills:
            for agent_skills in self._external_agent_skill_dirs():
                if agent_skills.is_dir():
                    dirs_to_scan.append((agent_skills, "agent"))
        for d in extra_dirs or []:
            p = Path(d).expanduser().resolve()
            if p.is_dir():
                dirs_to_scan.append((p, "sandbox"))

        found: list[dict] = []
        found_names: set[str] = set()
        for scan_root, source in dirs_to_scan:
            for entry in scan_root.iterdir():
                if not entry.is_dir():
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.is_file():
                    continue
                try:
                    content = skill_md.read_text(encoding="utf-8")
                    parsed = parse_skill_md(content)
                    name = parsed.name
                    storage_path = f"skills/{name}"
                    if source == "agent":
                        name = self._external_agent_skill_name(parsed.name)
                        storage_path = f"{_EXTERNAL_AGENT_SKILL_PREFIX}{entry.name}"
                    if name in found_names:
                        continue
                    found_names.add(name)
                    found.append(
                        {
                            "name": name,
                            "description": parsed.description,
                            "source_dir": str(entry),
                            "storage_path": storage_path,
                        }
                    )
                except (SkillParseError, OSError):
                    continue
        return found
