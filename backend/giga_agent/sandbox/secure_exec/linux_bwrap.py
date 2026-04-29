from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from giga_agent.sandbox.secure_exec.errors import SecureExecBinaryMissingError
from giga_agent.sandbox.secure_exec.launch import SecureExecLaunch, SecureProcessConfig
from giga_agent.sandbox.secure_exec.policy import SandboxAccessPolicy

BWRAP_EXECUTABLE = "bwrap"


def build_linux_bwrap_command(
    *,
    command: list[str],
    policy: SandboxAccessPolicy,
    executable: str = BWRAP_EXECUTABLE,
) -> list[str]:
    cwd = policy.assert_valid_cwd()
    bwrap_command = [
        executable,
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
    ]
    if policy.network_mode == "none":
        bwrap_command.append("--unshare-net")

    bwrap_command.extend(_mount_args(policy))
    bwrap_command.extend(["--chdir", str(cwd), "--", *command])
    return bwrap_command


def launch_linux_bwrap(config: SecureProcessConfig) -> SecureExecLaunch:
    executable = shutil.which(BWRAP_EXECUTABLE)
    if executable is None:
        raise SecureExecBinaryMissingError("bubblewrap executable 'bwrap' was not found")

    policy = config.policy
    if config.cwd is not None:
        policy = policy.model_copy(update={"cwd": config.cwd})
    command = build_linux_bwrap_command(
        command=config.command,
        policy=policy,
        executable=executable,
    )
    process = subprocess.Popen(
        command,
        cwd=str(policy.assert_valid_cwd()),
        env=config.env,
        stdin=config.stdin,
        stdout=config.stdout,
        stderr=config.stderr,
        start_new_session=config.start_new_session,
    )
    return SecureExecLaunch(
        process=process,
        command=command,
        backend="linux_bwrap",
        metadata={"network_mode": policy.network_mode},
    )


def _mount_args(policy: SandboxAccessPolicy) -> list[str]:
    args: list[str] = []
    read_roots = list(dict.fromkeys(policy.read_roots))

    if Path("/") in read_roots:
        args.extend(["--ro-bind", "/", "/"])
    else:
        for path in read_roots:
            args.extend(["--ro-bind", str(path), str(path)])

    # Overmount pseudo-filesystems and writable locations after the read-only
    # root so they are usable inside the mount namespace.
    args.extend(["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"])

    for path in policy.deny_roots:
        args.extend(["--dir", str(path), "--tmpfs", str(path)])

    for path in policy.writable_roots():
        args.extend(["--bind", str(path), str(path)])

    return args
