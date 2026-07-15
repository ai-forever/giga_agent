"""add_contact_default_recipient

Revision ID: 7a9e3d5c2b01
Revises: 6f8d2c4b1a90
Create Date: 2026-06-28 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a9e3d5c2b01"
down_revision: Union[str, None] = "6f8d2c4b1a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_channel_contacts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_default_task_recipient",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("core_channel_contacts", schema=None) as batch_op:
        batch_op.drop_column("is_default_task_recipient")
