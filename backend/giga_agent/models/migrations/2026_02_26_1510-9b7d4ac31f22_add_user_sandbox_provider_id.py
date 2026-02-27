"""add user sandbox_provider_id

Revision ID: 9b7d4ac31f22
Revises: a34df67f135a
Create Date: 2026-02-26 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b7d4ac31f22"
down_revision: Union[str, None] = "a34df67f135a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sandbox_provider_id", sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_core_users_sandbox_provider_id"),
            ["sandbox_provider_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_core_users_sandbox_provider_id",
            "core_sandbox_providers",
            ["sandbox_provider_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_core_users_sandbox_provider_id",
            type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_core_users_sandbox_provider_id"))
        batch_op.drop_column("sandbox_provider_id")
