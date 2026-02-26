import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =====================
# Collection Schemas
# =====================


class CollectionCreate(BaseModel):
    """Schema for creating a new collection."""

    name: str = Field(..., description="The unique name of the collection.")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Optional metadata for the collection."
    )


class CollectionUpdate(BaseModel):
    """Schema for updating an existing collection."""

    name: str | None = Field(None, description="New name for the collection.")
    metadata: dict[str, Any] | None = Field(
        None, description="Updated metadata for the collection."
    )


class CollectionResponse(BaseModel):
    """Schema for representing a user document collection."""

    model_config = ConfigDict(from_attributes=True)

    uuid: str = Field(
        ..., description="The unique identifier of the collection."
    )
    name: str = Field(..., description="The name of the collection.")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Metadata associated with the collection."
    )


# =====================
# Document Schemas
# =====================


class DocumentBase(BaseModel):
    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentCreate(DocumentBase):
    collection_id: str
    embedding: list[float] | None = (
        None  # Embedding can be added during creation or later
    )


class DocumentUpdate(BaseModel):
    page_content: str | None = None
    metadata: dict[str, Any] | None = None
    embedding: list[float] | None = None


class DocumentResponse(DocumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    collection_id: str
    embedding: list[float] | None = None  # Represent embedding as list of floats
    created_at: datetime.datetime
    updated_at: datetime.datetime
