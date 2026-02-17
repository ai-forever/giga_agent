"""add user secrets

Revision ID: 1d2f3a4b5c6d
Revises: 8f3a9d2c1b7e
Create Date: 2026-02-17 23:50:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1d2f3a4b5c6d"
down_revision: Union[str, None] = "8f3a9d2c1b7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "secrets",
                sa.JSON().with_variant(
                    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
                ),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("core_users", schema=None) as batch_op:
        batch_op.drop_column("secrets")
