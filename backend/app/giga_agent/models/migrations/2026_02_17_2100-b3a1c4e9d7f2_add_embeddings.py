"""add embeddings

Revision ID: b3a1c4e9d7f2
Revises: c6f53f2288f4
Create Date: 2026-02-17 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b3a1c4e9d7f2"
down_revision: Union[str, None] = "c6f53f2288f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "core_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "settings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
            name="fk_core_embeddings_owner_id",
        ),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["core_connectors.id"],
            name="fk_core_embeddings_connector_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("core_embeddings", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_core_embeddings_id"), ["id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_core_embeddings_owner_id"),
            ["owner_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_core_embeddings_connector_id"),
            ["connector_id"],
            unique=False,
        )

    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("embedding_id", sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_core_users_embedding_id"),
            ["embedding_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_core_users_embedding_id",
            "core_embeddings",
            ["embedding_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.drop_constraint("fk_core_users_embedding_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_core_users_embedding_id"))
        batch_op.drop_column("embedding_id")

    with op.batch_alter_table("core_embeddings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_embeddings_connector_id"))
        batch_op.drop_index(batch_op.f("ix_core_embeddings_owner_id"))
        batch_op.drop_index(batch_op.f("ix_core_embeddings_id"))

    op.drop_table("core_embeddings")
