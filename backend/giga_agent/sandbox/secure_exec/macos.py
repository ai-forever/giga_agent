from __future__ import annotations

import json
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from giga_agent.sandbox.secure_exec.errors import SecureExecBinaryMissingError
from giga_agent.sandbox.secure_exec.launch import SecureExecLaunch, SecureProcessConfig
from giga_agent.sandbox.secure_exec.policy import normalize_path

SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"


def _escape(value: str) -> str:
    return json.dumps(value)


def _literal_rule(operation: str, path: Path, *, action: str = "allow") -> str:
    return f"({action} {operation} (literal {_escape(str(path))}))"


def _subpath_rule(operation: str, path: Path, *, action: str = "allow") -> str:
    return f"({action} {operation} (subpath {_escape(str(path))}))"


def _ancestor_directories(path: Path) -> list[Path]:
    ancestors: list[Path] = []
    current = path.resolve().parent
    while current != current.parent:
        if str(current) == "/":
            break
        ancestors.append(current)
        current = current.parent
    return ancestors


class MacSandboxExecConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    command: list[str]
    profile_path: Path
    cwd: Path | None = None
    env: dict[str, str] | None = None
    read_roots: list[Path] = Field(default_factory=list)
    write_roots: list[Path] = Field(default_factory=list)
    deny_read_roots: list[Path] = Field(default_factory=list)
    allow_local_network: bool = True
    local_network_port: int | None = None
    allow_outbound_network: bool = False
    start_new_session: bool = True
    stdin: Any = None
    stdout: Any = None
    stderr: Any = None
    executable: str = SANDBOX_EXECUTABLE
    log_tag: str = Field(default_factory=lambda: f"GA_SANDBOX_{secrets.token_hex(8)}")

    @field_validator("command")
    @classmethod
    def _validate_command(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("command must not be empty")
        return value

    @field_validator("profile_path", "cwd", mode="before")
    @classmethod
    def _validate_optional_path(cls, value: Any) -> Any:
        if value is None:
            return None
        return normalize_path(value)

    @field_validator("read_roots", "write_roots", "deny_read_roots", mode="before")
    @classmethod
    def _validate_path_list(cls, value: Any) -> list[Path]:
        if value in (None, ""):
            return []
        return [normalize_path(item) for item in value]

    @field_validator("local_network_port")
    @classmethod
    def _validate_port(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0 or value > 65535:
            raise ValueError("local_network_port must be in range 1..65535")
        return value


@dataclass(slots=True)
class MacSandboxExecLaunch:
    process: subprocess.Popen[bytes]
    profile_path: Path
    profile: str
    command: list[str]


def build_macos_sandbox_profile(config: MacSandboxExecConfig) -> str:
    read_roots = list(dict.fromkeys(config.read_roots))
    write_roots = list(dict.fromkeys(config.write_roots))
    deny_read_roots = list(dict.fromkeys(config.deny_read_roots))

    ancestor_paths: list[Path] = []
    for path in [*read_roots, *write_roots, *deny_read_roots]:
        ancestor_paths.extend(_ancestor_directories(path))
    unique_ancestors = list(dict.fromkeys(ancestor_paths))

    profile: list[str] = [
        "(version 1)",
        f"(deny default (with message {_escape(config.log_tag)}))",
        "",
        "; Process lifecycle",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow process-info* (target same-sandbox))",
        "(allow signal (target same-sandbox))",
        "",
        "; Shared library loading (dlopen) — required for native addons",
        "(allow file-map-executable)",
        "",
        "; User preferences and logging",
        "(allow user-preference-read)",
        '(allow mach-lookup (global-name "com.apple.coreservices.launchservicesd"))',
        '(allow mach-lookup (global-name "com.apple.system.logger"))',
        '(allow mach-lookup (global-name "com.apple.logd"))',
        '(allow mach-lookup (global-name "com.apple.securityd"))',
        '(allow mach-lookup (global-name "com.apple.securityd.xpc"))',
        '(allow mach-lookup (global-name "com.apple.trustd"))',
        '(allow mach-lookup (global-name "com.apple.trustd.agent"))',
        '(allow mach-lookup (global-name "com.apple.FontObjectsServer"))',
        '(allow mach-lookup (global-name "com.apple.fonts"))',
        '(allow mach-lookup (global-name "com.apple.system.notification_center"))',
        '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo"))',
        '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.membership"))',
        '(allow mach-lookup (global-name "com.apple.SystemConfiguration.configd"))',
        '(allow mach-lookup (global-name "com.apple.SystemConfiguration.DNSConfiguration"))',
        "",
        "; POSIX and System V IPC",
        "(allow ipc-posix-shm*)",
        "(allow ipc-posix-sem*)",
        "(allow ipc-sysv-sem)",
        "",
        "; Device files",
        '(allow file-read* file-write* (literal "/dev/null"))',
        '(allow file-read* (literal "/dev/urandom"))',
        '(allow file-read* (literal "/dev/random"))',
        "",
        "; sysctl reads commonly used by Python and Jupyter",
        "(allow sysctl-read)",
        "",
        "; Read policy",
        '(allow file-read* (literal "/"))',
    ]

    for path in unique_ancestors:
        profile.append(_literal_rule("file-read-metadata", path))

    for path in read_roots:
        profile.append(_subpath_rule("file-read*", path))

    if deny_read_roots:
        profile.extend(["", "; Read deny policy"])
        for path in deny_read_roots:
            profile.append(_subpath_rule("file-read*", path, action="deny"))

    profile.extend(["", "; Write policy"])
    for path in write_roots:
        profile.append(_subpath_rule("file-write*", path))
        profile.append(_subpath_rule("file-write-unlink", path))
        profile.append(_subpath_rule("file-ioctl", path))

    profile.extend(["", "; Local server bindings"])
    if config.allow_local_network:
        profile.append('(allow network-bind (local ip "*:*"))')
        profile.append('(allow network-inbound (local ip "*:*"))')
        if config.local_network_port is not None:
            profile.append(
                "(allow network-outbound "
                f'(remote ip "localhost:{config.local_network_port}"))'
            )
        else:
            profile.append('(allow network-outbound (remote ip "localhost:*"))')

    profile.extend(["", "; External outbound network policy"])
    if config.allow_outbound_network:
        profile.append("(allow network-outbound)")

    return "\n".join(profile) + "\n"


def launch_with_macos_sandbox(
    config: MacSandboxExecConfig,
) -> MacSandboxExecLaunch:
    executable = shutil.which(config.executable) or config.executable
    if not Path(executable).is_file():
        raise SecureExecBinaryMissingError(
            f"macOS sandbox executable was not found: {config.executable}"
        )

    profile = build_macos_sandbox_profile(config)
    config.profile_path.parent.mkdir(parents=True, exist_ok=True)
    config.profile_path.write_text(profile, encoding="utf-8")

    command = [
        executable,
        "-f",
        str(config.profile_path),
        *config.command,
    ]
    process = subprocess.Popen(
        command,
        cwd=str(config.cwd) if config.cwd is not None else None,
        env=config.env,
        stdin=config.stdin,
        stdout=config.stdout,
        stderr=config.stderr,
        start_new_session=config.start_new_session,
    )
    return MacSandboxExecLaunch(
        process=process,
        profile_path=config.profile_path,
        profile=profile,
        command=command,
    )


def launch_macos_sandbox(config: SecureProcessConfig) -> SecureExecLaunch:
    policy = config.policy
    if config.cwd is not None:
        policy = policy.model_copy(update={"cwd": config.cwd})
    cwd = policy.assert_valid_cwd()
    profile_path = config.profile_path
    if profile_path is None:
        profile_path = policy.workspace_root / ".giga-agent-sandbox.sb"

    launch = launch_with_macos_sandbox(
        MacSandboxExecConfig(
            command=config.command,
            profile_path=profile_path,
            cwd=cwd,
            env=config.env,
            read_roots=policy.read_roots,
            write_roots=policy.writable_roots(),
            deny_read_roots=policy.deny_roots,
            allow_local_network=True,
            local_network_port=config.local_network_port,
            allow_outbound_network=policy.network_mode == "host",
            stdin=config.stdin,
            stdout=config.stdout,
            stderr=config.stderr,
            start_new_session=config.start_new_session,
        )
    )
    return SecureExecLaunch(
        process=launch.process,
        command=launch.command,
        backend="macos_sandbox_exec",
        metadata={"profile_path": str(launch.profile_path)},
    )
