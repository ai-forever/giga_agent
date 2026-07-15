"""scheduled_task_name_nullable

Revision ID: 8b0a4e6d3c12
Revises: 7a9e3d5c2b01
Create Date: 2026-06-29 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b0a4e6d3c12"
down_revision: Union[str, None] = "7a9e3d5c2b01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_scheduled_tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "name",
            existing_type=sa.String(length=255),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("core_scheduled_tasks", schema=None) as batch_op:
        batch_op.alter_column(
            "name",
            existing_type=sa.String(length=255),
            nullable=False,
        )
