"""add_scheduled_task_memory_tags

Revision ID: 9c1b5f7e4d23
Revises: 8b0a4e6d3c12
Create Date: 2026-06-29 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.sqltypes import Text

# revision identifiers, used by Alembic.
revision: str = "9c1b5f7e4d23"
down_revision: Union[str, None] = "8b0a4e6d3c12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("core_scheduled_tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("memory_tags", _JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("core_scheduled_tasks", schema=None) as batch_op:
        batch_op.drop_column("memory_tags")
