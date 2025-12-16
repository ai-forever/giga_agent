from collections.abc import Mapping
from typing import IO, Literal, TypedDict, Union

FileContent = Union[IO[bytes], bytes, str]
FileTypes = Union[
    # file (or bytes)
    FileContent,
    # (filename, file (or bytes))
    tuple[str | None, FileContent],
    # (filename, file (or bytes), content_type)
    tuple[str | None, FileContent, str | None],
    # (filename, file (or bytes), content_type, headers)
    tuple[str | None, FileContent, str | None, Mapping[str, str]],
]

UploadedFileType = Literal["image", "plotly_graph", "html", "text", "audio", "other"]


class UploadedFile(TypedDict):
    path: str
    size: int
    file_type: UploadedFileType
    image_id: str | None
    image_path: str | None


class CollectionMetadata(TypedDict):
    description: str


class Collection(TypedDict):
    name: str
    uuid: str
    metadata: CollectionMetadata
