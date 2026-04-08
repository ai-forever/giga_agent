from __future__ import annotations

import json
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"


def _normalize_path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


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


_RW_DEVICE_SUBPATHS = [
    "/dev",
]


class MacSandboxExecConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    command: list[str]
    profile_path: Path
    cwd: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)
    read_roots: list[Path] = Field(default_factory=list)
    write_roots: list[Path] = Field(default_factory=list)
    deny_read_roots: list[Path] = Field(default_factory=list)
    allow_local_network: bool = True
    local_network_port: int | None = None
    allow_local_network_all_ports: bool = False
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
        return _normalize_path(value)

    @field_validator("read_roots", "write_roots", "deny_read_roots", mode="before")
    @classmethod
    def _validate_path_list(cls, value: Any) -> list[Path]:
        if value in (None, ""):
            return []
        return [_normalize_path(item) for item in value]

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
        f'(deny default (with message "{config.log_tag}"))',
        "",
        "; Process lifecycle",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow process-info* (target same-sandbox))",
        "(allow signal (target same-sandbox))",
        "",
        "; User preferences and logging",
        "(allow user-preference-read)",
        '(allow mach-lookup (global-name "com.apple.coreservices.launchservicesd"))',
        '(allow mach-lookup (global-name "com.apple.system.logger"))',
        '(allow mach-lookup (global-name "com.apple.logd"))',
        '(allow mach-lookup (global-name "com.apple.securityd.xpc"))',
        '(allow mach-lookup (global-name "com.apple.FontObjectsServer"))',
        '(allow mach-lookup (global-name "com.apple.fonts"))',
        '(allow mach-lookup (global-name "com.apple.system.notification_center"))',
        '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo"))',
        '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.membership"))',
        '(allow mach-lookup (global-name "com.apple.SystemConfiguration.configd"))',
        '(allow mach-lookup (global-name "com.apple.SystemConfiguration.DNSConfiguration"))',
        "",
        "; POSIX IPC",
        "(allow ipc-posix-shm)",
        "(allow ipc-posix-sem)",
        "",
        "; Device files",
        '(allow file-read* file-write* (literal "/dev/null"))',
        '(allow file-read* (literal "/dev/urandom"))',
        '(allow file-read* (literal "/dev/random"))',
        '(allow file-read* file-write* (literal "/dev/dtracehelper"))',
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

    for path in _RW_DEVICE_SUBPATHS:
        profile.append(f'(allow file-read* file-write* (subpath {_escape(path)}))')

    if deny_read_roots:
        profile.extend(["", "; Read deny policy"])
        for path in deny_read_roots:
            profile.append(_subpath_rule("file-read*", path, action="deny"))

    profile.extend(["", "; Write policy"])
    for path in write_roots:
        profile.append(_subpath_rule("file-write*", path))
        profile.append(_subpath_rule("file-write-unlink", path))

    profile.extend(["", "; Local server bindings"])
    if config.allow_local_network:
        profile.append('(allow network-bind (local ip "*:*"))')
        profile.append('(allow network-inbound (local ip "*:*"))')
        if config.allow_local_network_all_ports:
            profile.append('(allow network-outbound (remote ip "localhost:*"))')
        elif config.local_network_port is not None:
            profile.append(
                f'(allow network-outbound (remote ip "localhost:{config.local_network_port}"))'
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
    profile = build_macos_sandbox_profile(config)
    config.profile_path.parent.mkdir(parents=True, exist_ok=True)
    config.profile_path.write_text(profile, encoding="utf-8")

    command = [
        config.executable,
        "-f",
        str(config.profile_path),
        *config.command,
    ]
    process = subprocess.Popen(
        command,
        cwd=str(config.cwd) if config.cwd is not None else None,
        env=config.env or None,
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
