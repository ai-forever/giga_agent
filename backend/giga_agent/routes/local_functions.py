from __future__ import annotations

import asyncio
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from giga_agent.modules.auth.api import get_current_active_user
from giga_agent.models.users import User

DIRECTORY_PICKER_TIMEOUT_SEC = 300

router = APIRouter(prefix="/local-functions", tags=["local-functions"])


class DirectoryPickerResponse(BaseModel):
    path: str | None


class DirectoryPickerUnavailableError(RuntimeError):
    pass


class DirectoryPickerFailedError(RuntimeError):
    pass


def _run_picker_command(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=DIRECTORY_PICKER_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise DirectoryPickerFailedError("Directory picker timed out") from exc
    except OSError as exc:
        raise DirectoryPickerUnavailableError(str(exc)) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip().lower()
        stdout = (result.stdout or "").strip().lower()
        if "cancel" in stderr or "cancel" in stdout or result.returncode == 1:
            return None
        raise DirectoryPickerFailedError(
            (result.stderr or "").strip() or "Picker failed"
        )

    selected_path = (result.stdout or "").strip()
    if not selected_path:
        return None
    return str(Path(selected_path).expanduser())


def _pick_directory_macos() -> str | None:
    if shutil.which("osascript") is None:
        raise DirectoryPickerUnavailableError("osascript is not available")

    return _run_picker_command(
        [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Укажите директорию")',
        ],
    )


def _pick_directory_linux() -> str | None:
    zenity = shutil.which("zenity")
    if zenity:
        return _run_picker_command(
            [zenity, "--file-selection", "--directory", "--title=Укажите директорию"],
        )

    kdialog = shutil.which("kdialog")
    if kdialog:
        return _run_picker_command(
            [kdialog, "--title", "Укажите директорию", "--getexistingdirectory", "/"],
        )

    raise DirectoryPickerUnavailableError("zenity or kdialog is required")


def _pick_directory_windows() -> str | None:
    powershell = (
        shutil.which("powershell")
        or shutil.which("powershell.exe")
        or shutil.which("pwsh")
        or shutil.which("pwsh.exe")
    )
    if not powershell:
        raise DirectoryPickerUnavailableError("PowerShell is not available")

    script = "\n".join(
        [
            "Add-Type -AssemblyName System.Windows.Forms",
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog",
            "$dialog.Description = 'Укажите директорию'",
            "$dialog.ShowNewFolderButton = $true",
            "$result = $dialog.ShowDialog()",
            "if ($result -eq [System.Windows.Forms.DialogResult]::OK) {",
            "  [Console]::WriteLine($dialog.SelectedPath)",
            "  exit 0",
            "}",
            "exit 1",
        ],
    )
    command = [powershell, "-NoProfile", "-Command", script]
    if Path(powershell).name.lower().startswith("powershell"):
        command.insert(2, "-STA")
    return _run_picker_command(command)


def pick_directory() -> str | None:
    system = platform.system()
    if system == "Darwin":
        return _pick_directory_macos()
    if system == "Linux":
        return _pick_directory_linux()
    if system == "Windows":
        return _pick_directory_windows()
    raise DirectoryPickerUnavailableError(
        f"Unsupported platform: {system or 'unknown'}"
    )


@router.post("/directory-picker", response_model=DirectoryPickerResponse)
async def open_directory_picker(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> DirectoryPickerResponse:
    _ = current_user
    try:
        selected_path = await asyncio.to_thread(pick_directory)
    except DirectoryPickerUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc
    except DirectoryPickerFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return DirectoryPickerResponse(path=selected_path)
