import mimetypes
import uuid

from fastapi import UploadFile
from langchain_community.document_loaders.parsers import BS4HTMLParser, PDFMinerParser
from langchain_community.document_loaders.parsers.generic import MimeTypeBasedParser
# from langchain_community.document_loaders.parsers.msword import MsWordParser
from langchain_community.document_loaders.parsers.txt import TextParser
from langchain_core.documents.base import Blob, Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from giga_agent.core.logging import get_logger

logger = get_logger(__name__)

# Document Parser Configuration
HANDLERS = {
    "application/pdf": PDFMinerParser(),
    "text/plain": TextParser(),
    "text/markdown": TextParser(),
    "text/x-markdown": TextParser(),
    "text/html": BS4HTMLParser(),
    # "application/msword": MsWordParser(),
    # "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
    #     MsWordParser()
    # ),
}

SUPPORTED_MIMETYPES = sorted(HANDLERS.keys())

MIMETYPE_BASED_PARSER = MimeTypeBasedParser(
    handlers=HANDLERS,
    fallback_parser=None,
)

# Text Splitter
TEXT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    add_start_index=True,
)


async def process_document(
    file: UploadFile,
    metadata: dict | None = None,
    *,
    file_id: uuid.UUID | str | None = None,
) -> tuple[str, str, list[Document]]:
    """Process an uploaded file into chunked LangChain documents.

    Returns:
        (file_id, full_text, split_docs)
    """
    # A file_id identifies the original file from which the chunks were generated.
    if file_id is None:
        file_uuid = uuid.uuid4()
    else:
        file_uuid = file_id if isinstance(file_id, uuid.UUID) else uuid.UUID(str(file_id))

    contents = await file.read()
    content_type = file.content_type
    if not content_type or content_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(file.filename or "")
        if guessed:
            content_type = guessed
    blob = Blob(data=contents, mimetype=content_type or "text/plain")

    docs = MIMETYPE_BASED_PARSER.parse(blob)
    full_text = "\n\n".join((d.page_content or "") for d in docs).strip()

    base_metadata: dict = {}
    if metadata:
        base_metadata.update(metadata)
    base_metadata.setdefault("name", file.filename or "document")

    split_docs = TEXT_SPLITTER.create_documents([full_text], metadatas=[base_metadata])

    # Add the file_id + end_index to all split documents' metadata
    for split_doc in split_docs:
        if not hasattr(split_doc, "metadata") or not isinstance(split_doc.metadata, dict):
            split_doc.metadata = {}
        split_doc.metadata["file_id"] = str(file_uuid)
        start_index = int(split_doc.metadata.get("start_index") or 0)
        split_doc.metadata["end_index"] = start_index + len(split_doc.page_content or "")

    return str(file_uuid), full_text, split_docs
