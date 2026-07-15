"""Wire models for the SandboxAPI Server.

Форматы совместимы по смыслу с giga_agent.sandbox.mixins.code (ShellMeta /
ShellRunResult / ShellAwaitResult) и с чанками run_code из
giga_agent.sandbox.jupyter, чтобы тонкий клиент SandboxAPISandbox мог
переиспользовать существующую логику разбора почти без изменений.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ShellStatus = Literal["running", "completed", "failed"]


# --------------------------------------------------------------------------- #
# info / health
# --------------------------------------------------------------------------- #


class InfoResponse(BaseModel):
    server_version: str
    workdir: str
    skills_root: str
    default_kernel: str
    platform: str
    python_version: str
    uptime_sec: float
    active_kernels: int
    active_shells: int


# --------------------------------------------------------------------------- #
# kernels
# --------------------------------------------------------------------------- #


class CreateKernelRequest(BaseModel):
    kernel_name: str | None = Field(
        default=None, description="Kernel spec name (default: server default)"
    )
    cwd: str | None = Field(
        default=None, description="Working directory for the kernel"
    )
    env: dict[str, str] | None = Field(
        default=None, description="Extra environment variables for the kernel process"
    )


class KernelInfo(BaseModel):
    kernel_id: str
    kernel_name: str
    cwd: str | None = None
    last_activity_at: float
    execution_count: int = 0


class KernelListResponse(BaseModel):
    kernels: list[KernelInfo]


# --------------------------------------------------------------------------- #
# shell
# --------------------------------------------------------------------------- #


class ShellRunRequest(BaseModel):
    command: str
    working_directory: str | None = None
    block_until_ms: int = 30000
    description: str | None = None
    envs: dict[str, str] | None = None


class ShellRunResult(BaseModel):
    shell_id: str
    status: ShellStatus
    backgrounded: bool
    cwd: str
    description: str | None = None
    output: str
    output_path: str
    pid: int | None = None
    exit_code: int | None = None
    elapsed_ms: int | None = None
    await_hint: str | None = None


class ShellAwaitRequest(BaseModel):
    block_until_ms: int = 30000
    pattern: str | None = None


class ShellAwaitResult(BaseModel):
    shell_id: str
    status: Literal["running", "completed", "failed", "not_found"]
    output_delta: str
    matched_pattern: bool
    output_path: str | None = None
    exit_code: int | None = None
    elapsed_ms: int | None = None
    read_full_log_hint: str = ""


class ShellMeta(BaseModel):
    shell_id: str
    command: str
    description: str | None = None
    cwd: str
    status: ShellStatus
    started_at: str
    ended_at: str | None = None
    elapsed_ms: int | None = None
    exit_code: int | None = None
    pid: int | None = None
    output_path: str
    output_size_bytes: int = 0
    last_update_at: str


class ShellListResponse(BaseModel):
    shells: list[ShellMeta]


class ShellKilledResponse(BaseModel):
    shell_id: str
    status: ShellStatus
    killed: bool


# --------------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------------- #


class FileStat(BaseModel):
    path: str
    exists: bool
    is_dir: bool = False
    size: int = 0
    modified_at: float | None = None


class DirEntry(BaseModel):
    name: str
    is_dir: bool
    size: int


class DirListing(BaseModel):
    path: str
    entries: list[DirEntry]


class WrittenResponse(BaseModel):
    path: str
    size: int


class ErrorResponse(BaseModel):
    detail: str


# --------------------------------------------------------------------------- #
# skills (FS-backed; используется ТОЛЬКО нативным провайдером sandbox_api)
# --------------------------------------------------------------------------- #
# Важно: при переезде local_docker/e2b на это API их skill-операции сюда НЕ
# ходят — у них своя персистентность (локальная FS / S3). Эти ручки — про
# скиллы, которые хранятся прямо в файловой системе песочницы.


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    storage_path: str  # opaque id, напр. "skills/<name>"
    sandbox_path: str  # абсолютный путь директории скилла в песочнице


class SkillListResponse(BaseModel):
    skills: list[SkillInfo]


class SkillInstalledResponse(BaseModel):
    name: str
    storage_path: str
    sandbox_path: str
    files: list[str]


class SkillFilesResponse(BaseModel):
    name: str
    storage_path: str
    sandbox_path: str
    files: list[str]


# --------------------------------------------------------------------------- #
# execute WS message shapes (server -> client)
# --------------------------------------------------------------------------- #
# Отдаются как JSON-текст по WebSocket, ключи совпадают с чанками
# giga_agent.sandbox.jupyter.JupyterSandbox.run_code:
#   {"type": "stdout"|"stderr", "text": str}
#   {"type": "result", "data": {...}, "execution_count": int}
#   {"type": "display_data", "data": {...}}
#   {"type": "error", "ename": str, "evalue": str, "traceback": [str]}
#   {"type": "input_request", "prompt": str, "password": bool}
#   {"type": "done"}                         # выполнение завершилось (idle)
#   {"type": "fatal", "detail": str}         # серверная/kernel-ошибка
# Клиент -> сервер (ответ на input_request):
#   {"type": "input_reply", "value": str}
