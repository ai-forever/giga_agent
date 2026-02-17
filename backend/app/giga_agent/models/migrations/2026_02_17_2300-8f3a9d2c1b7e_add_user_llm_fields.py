"""add user llm fields

Revision ID: 8f3a9d2c1b7e
Revises: b3a1c4e9d7f2
Create Date: 2026-02-17 23:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f3a9d2c1b7e"
down_revision: Union[str, None] = "b3a1c4e9d7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("llm_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("fast_llm_id", sa.Uuid(), nullable=True))
        batch_op.create_index(batch_op.f("ix_core_users_llm_id"), ["llm_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_core_users_fast_llm_id"), ["fast_llm_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_core_users_llm_id",
            "core_llms",
            ["llm_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_core_users_fast_llm_id",
            "core_llms",
            ["fast_llm_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.drop_constraint("fk_core_users_fast_llm_id", type_="foreignkey")
        batch_op.drop_constraint("fk_core_users_llm_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_core_users_fast_llm_id"))
        batch_op.drop_index(batch_op.f("ix_core_users_llm_id"))
        batch_op.drop_column("fast_llm_id")
        batch_op.drop_column("llm_id")
