from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel

JUPYTER_PORT = 8888
BUCKET_PREFIX = "/bucket/"
_LOCAL_FILE_SUFFIX_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MANAGED_LABEL = "giga_agent.managed"
PROVIDER_TYPE_LABEL = "giga_agent.provider_type"
PROVIDER_ID_LABEL = "giga_agent.provider_id"
SANDBOX_ID_LABEL = "giga_agent.sandbox_id"
OWNER_ID_LABEL = "giga_agent.owner_id"
_CONTAINER_HOME_DIR = PurePosixPath("/root")
_SHELL_POLL_INTERVAL_SEC = 0.2
_SHELL_STATUS_RUNNING = "running"
_SHELL_STATUS_COMPLETED = "completed"
_SHELL_STATUS_FAILED = "failed"
_CONTAINER_PYTHON_BIN = "python"


class LocalDockerShellMeta(BaseModel):
    shell_id: str
    exec_id: str | None = None
    command: str
    description: str | None = None
    cwd: str
    status: Literal["running", "completed", "failed"]
    started_at: str
    ended_at: str | None = None
    elapsed_ms: int | None = None
    exit_code: int | None = None
    pid: int | None = None
    output_path: str
    exit_code_path: str | None = None
    output_size_bytes: int = 0
    last_delivered_offset: int = 0
    last_update_at: str
