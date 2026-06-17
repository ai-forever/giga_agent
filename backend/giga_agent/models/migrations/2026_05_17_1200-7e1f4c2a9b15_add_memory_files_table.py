"""add_memory_files_table

Revision ID: 7e1f4c2a9b15
Revises: b3ce2589d775
Create Date: 2026-05-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7e1f4c2a9b15"
down_revision: Union[str, None] = "b3ce2589d775"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "core_memory_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("tag", sa.String(length=255), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("indexed_hash", sa.String(length=64), nullable=True),
        sa.Column("indexed_embedding_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["core_users.id"],
            name="fk_core_memory_files_owner_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "path", name="uq_core_memory_files_owner_path"
        ),
    )
    with op.batch_alter_table("core_memory_files", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_memory_files_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_memory_files_owner_id"),
            ["owner_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_core_memory_files_owner_tag",
            ["owner_id", "tag"],
            unique=False,
        )
        batch_op.create_index(
            "ix_core_memory_files_owner_indexed",
            ["owner_id", "indexed_hash", "content_hash"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("core_memory_files", schema=None) as batch_op:
        batch_op.drop_index("ix_core_memory_files_owner_indexed")
        batch_op.drop_index("ix_core_memory_files_owner_tag")
        batch_op.drop_index(batch_op.f("ix_core_memory_files_owner_id"))
        batch_op.drop_index(batch_op.f("ix_core_memory_files_id"))
    op.drop_table("core_memory_files")
