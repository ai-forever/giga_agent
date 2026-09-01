"""Python executable environments shared by local sandbox executors."""

from __future__ import annotations

import os
from pathlib import Path


class LocalPythonEnvironment:
    """Build a shell environment for one concrete Python executable.

    The executable and shim directory are intentionally explicit.  This keeps
    worker mode independent from the Jupyter server manager while preserving
    one implementation for ``python``/``pip`` command resolution.
    """

    def __init__(self, *, python_executable: str, shims_dir: Path) -> None:
        # Preserve the configured executable spelling (and venv symlink) in
        # kernel specs and shim targets; only the shim directory needs
        # canonicalization.
        self.python_executable = str(Path(python_executable).expanduser())
        self.shims_dir = shims_dir.expanduser()

    def shell_env(
        self,
        *,
        extra_envs: dict[str, str] | None = None,
    ) -> dict[str, str]:
        self.ensure_command_shims()

        env = os.environ.copy()
        python_bin_dir = Path(self.python_executable).parent
        path_entries = [str(self.shims_dir), str(python_bin_dir)]
        existing_path = env.get("PATH")
        if existing_path:
            path_entries.append(existing_path)
        env["PATH"] = os.pathsep.join(path_entries)

        venv_dir = self._virtual_env_dir()
        if venv_dir is not None:
            env["VIRTUAL_ENV"] = str(venv_dir)
        env["PYTHONNOUSERSITE"] = "1"
        env["PIP_REQUIRE_VIRTUALENV"] = "1"
        if extra_envs:
            env.update({str(key): str(value) for key, value in extra_envs.items()})
        return env

    def jupyter_env(
        self,
        *,
        config_dir: Path,
        data_dir: Path,
        runtime_dir: Path,
        extra_envs: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = self.shell_env(extra_envs=extra_envs)
        env["JUPYTER_NO_CONFIG"] = "1"
        env["JUPYTER_CONFIG_DIR"] = str(config_dir)
        env["JUPYTER_DATA_DIR"] = str(data_dir)
        env["JUPYTER_RUNTIME_DIR"] = str(runtime_dir)
        return env

    def _virtual_env_dir(self) -> Path | None:
        python_bin_dir = Path(self.python_executable).parent
        if python_bin_dir.name.lower() in {"bin", "scripts"}:
            return python_bin_dir.parent.resolve()
        return None

    def ensure_command_shims(self) -> None:
        self.shims_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            shim_targets = {
                "python.cmd": f'@"{self.python_executable}" %*\r\n',
                "python3.cmd": f'@"{self.python_executable}" %*\r\n',
                "pip.cmd": f'@"{self.python_executable}" -m pip %*\r\n',
                "pip3.cmd": f'@"{self.python_executable}" -m pip %*\r\n',
            }
        else:
            shim_targets = {
                "python": f'#!/bin/sh\nexec "{self.python_executable}" "$@"\n',
                "python3": f'#!/bin/sh\nexec "{self.python_executable}" "$@"\n',
                "pip": f'#!/bin/sh\nexec "{self.python_executable}" -m pip "$@"\n',
                "pip3": f'#!/bin/sh\nexec "{self.python_executable}" -m pip "$@"\n',
            }

        for name, content in shim_targets.items():
            path = self.shims_dir / name
            path.write_text(content, encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o755)
