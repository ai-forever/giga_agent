import uuid
from dataclasses import dataclass
from typing import Literal, TypedDict

from giga_agent.models.file import File, FileType
from giga_agent.models.sandbox import (
    SandboxStatus,
    Sandbox,
    SandboxProvider,
    SandboxProviderSnapshot,
    SandboxSnapshot,
)


class UploadFileSpec(TypedDict):
    file_name: str
    content: bytes
    file_type: FileType


@dataclass(frozen=True)
class SandboxResolved:
    provider: SandboxProvider | SandboxProviderSnapshot
    sandbox: Sandbox | SandboxSnapshot


@dataclass(frozen=True, slots=True)
class UploadBatchError:
    index: int
    file_name: str
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class UploadBatchResult:
    files: list[File]
    errors: list[UploadBatchError]


@dataclass(frozen=True, slots=True)
class StopExternalRuntimeAction:
    provider_type: str
    provider_id: uuid.UUID | None
    sandbox_id: uuid.UUID | None
    external_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class RemoveExternalRuntimeAction:
    provider_type: str
    provider_id: uuid.UUID | None
    sandbox_id: uuid.UUID | None
    external_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SetSandboxStatusAction:
    provider_type: str
    provider_id: uuid.UUID | None
    sandbox_id: uuid.UUID
    status: SandboxStatus
    reason: str
    clear_runtime_connection: bool = False


@dataclass(frozen=True, slots=True)
class LogOnlyOrphanAction:
    provider_type: str
    provider_id: uuid.UUID | None
    sandbox_id: uuid.UUID | None
    external_id: str | None
    reason: str
    level: Literal["info", "warning", "error"] = "info"


OrphanAction = (
    StopExternalRuntimeAction
    | RemoveExternalRuntimeAction
    | SetSandboxStatusAction
    | LogOnlyOrphanAction
)
