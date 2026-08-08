"""add nullable context window to llms

Revision ID: 5a7c9e1f3b20
Revises: 0db16d763b28
Create Date: 2026-08-01 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5a7c9e1f3b20"
down_revision: Union[str, None] = "0db16d763b28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_llms") as batch_op:
        batch_op.add_column(sa.Column("context_window", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("core_llms") as batch_op:
        batch_op.drop_column("context_window")
