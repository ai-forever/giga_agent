"""add search engines

Revision ID: 9a0d4ddf11c2
Revises: 22147ede27d9
Create Date: 2026-02-17 01:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9a0d4ddf11c2"
down_revision: Union[str, None] = "22147ede27d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "core_search_engines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
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
            ["owner_id"], ["core_users.id"], name="fk_core_search_engines_owner_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_search_engines", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_search_engines_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_search_engines_owner_id"), ["owner_id"], unique=False
        )

    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("search_engine_id", sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_core_users_search_engine_id"),
            ["search_engine_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_core_users_search_engine_id",
            "core_search_engines",
            ["search_engine_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.drop_constraint("fk_core_users_search_engine_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_core_users_search_engine_id"))
        batch_op.drop_column("search_engine_id")

    with op.batch_alter_table("core_search_engines", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_search_engines_owner_id"))
        batch_op.drop_index(batch_op.f("ix_core_search_engines_id"))

    op.drop_table("core_search_engines")
