"""add rag document file/provider links

Revision ID: 1d2b3c4d5e6f
Revises: 6c2f0f4a9b12
Create Date: 2026-03-02 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1d2b3c4d5e6f"
down_revision: Union[str, None] = "6c2f0f4a9b12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_rag_documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("file_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("sandbox_provider_id", sa.Uuid(), nullable=True))
        batch_op.alter_column(
            "sandbox_path", existing_type=sa.String(length=2048), nullable=True
        )
        batch_op.create_index(
            batch_op.f("ix_core_rag_documents_file_id"), ["file_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_rag_documents_sandbox_provider_id"),
            ["sandbox_provider_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_core_rag_documents_file_id",
            "core_files",
            ["file_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_core_rag_documents_sandbox_provider_id",
            "core_sandbox_providers",
            ["sandbox_provider_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        sa.text(
            """
            UPDATE core_rag_documents
            SET
                file_id = (
                    SELECT f.id
                    FROM core_files AS f
                    WHERE f.owner_id = core_rag_documents.owner_id
                      AND f.sandbox_path = core_rag_documents.sandbox_path
                    ORDER BY f.created_at DESC
                    LIMIT 1
                ),
                sandbox_provider_id = (
                    SELECT f.provider_id
                    FROM core_files AS f
                    WHERE f.owner_id = core_rag_documents.owner_id
                      AND f.sandbox_path = core_rag_documents.sandbox_path
                    ORDER BY f.created_at DESC
                    LIMIT 1
                )
            WHERE core_rag_documents.sandbox_path IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("core_rag_documents", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_core_rag_documents_sandbox_provider_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_core_rag_documents_file_id",
            type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_core_rag_documents_sandbox_provider_id"))
        batch_op.drop_index(batch_op.f("ix_core_rag_documents_file_id"))
        batch_op.alter_column(
            "sandbox_path", existing_type=sa.String(length=2048), nullable=False
        )
        batch_op.drop_column("sandbox_provider_id")
        batch_op.drop_column("file_id")
