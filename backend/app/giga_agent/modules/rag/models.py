import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from giga_agent.core.db import Base, JSON_VARIANT


class RagCollection(Base):
    __tablename__ = "rag_collections"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_rag_collections_owner_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_users.id",
            name="fk_rag_collections_owner_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    embedding_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_embeddings.id",
            name="fk_rag_collections_embedding_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_VARIANT(), default=dict
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    documents: Mapped[list["RagDocument"]] = relationship(
        "RagDocument",
        back_populates="collection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RagDocument(Base):
    __tablename__ = "rag_documents"

    # id is also used as `file_id` in chunk metadata and API.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, index=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "core_users.id",
            name="fk_rag_documents_owner_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "rag_collections.id",
            name="fk_rag_documents_collection_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    original_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    sandbox_path: Mapped[str] = mapped_column(String(2048), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), server_default=func.now()
    )

    collection: Mapped["RagCollection"] = relationship(
        "RagCollection",
        back_populates="documents",
    )


__all__ = ["RagCollection", "RagDocument"]
