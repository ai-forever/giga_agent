import uuid
from dataclasses import dataclass
from typing import TypedDict

from giga_agent.models.file import File, FileType
from giga_agent.models.sandbox import (
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
