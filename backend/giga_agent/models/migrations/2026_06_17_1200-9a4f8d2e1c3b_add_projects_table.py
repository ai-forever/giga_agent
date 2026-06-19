"""add_projects_table

Revision ID: 9a4f8d2e1c3b
Revises: 7e1f4c2a9b15
Create Date: 2026-05-27 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a4f8d2e1c3b"
down_revision: Union[str, None] = "ed56338cb9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "core_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("collection_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_id"], ["core_users.id"]),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["core_rag_collections.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_project_owner_name"),
    )
    with op.batch_alter_table("core_projects", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_core_projects_id"), ["id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_core_projects_owner_id"), ["owner_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("core_projects", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_projects_owner_id"))
        batch_op.drop_index(batch_op.f("ix_core_projects_id"))

    op.drop_table("core_projects")
