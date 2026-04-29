from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from giga_agent.sandbox.secure_exec.errors import SecureExecUnsupportedError
from giga_agent.sandbox.secure_exec.policy import SandboxAccessPolicy

SecureExecBackend = Literal["auto", "macos_sandbox_exec", "linux_bwrap"]


class SecureProcessConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    command: list[str]
    policy: SandboxAccessPolicy
    backend: SecureExecBackend = "auto"
    cwd: Path | None = None
    env: dict[str, str] | None = None
    stdin: Any = None
    stdout: Any = None
    stderr: Any = None
    start_new_session: bool = True
    local_network_port: int | None = None
    profile_path: Path | None = None

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("command must not be empty")
        return value


@dataclass(slots=True)
class SecureExecLaunch:
    process: subprocess.Popen[bytes]
    command: list[str]
    backend: str
    metadata: dict[str, str]


def launch_secure_process(config: SecureProcessConfig) -> SecureExecLaunch:
    backend = _resolve_backend(config.backend)
    if backend == "macos_sandbox_exec":
        from giga_agent.sandbox.secure_exec.macos import launch_macos_sandbox

        return launch_macos_sandbox(config)
    if backend == "linux_bwrap":
        from giga_agent.sandbox.secure_exec.linux_bwrap import launch_linux_bwrap

        return launch_linux_bwrap(config)
    raise SecureExecUnsupportedError(f"Unsupported secure exec backend: {backend}")


def _resolve_backend(backend: SecureExecBackend) -> str:
    if backend != "auto":
        return backend

    system = platform.system()
    if system == "Darwin":
        return "macos_sandbox_exec"
    if system == "Linux":
        return "linux_bwrap"
    raise SecureExecUnsupportedError(
        f"Secure execution is not supported on platform: {system or 'unknown'}"
    )
