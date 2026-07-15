"""add_scheduled_tasks_table

Revision ID: 6f8d2c4b1a90
Revises: 5e7c3b1a9f00
Create Date: 2026-06-28 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.sqltypes import Text

# revision identifiers, used by Alembic.
revision: str = "6f8d2c4b1a90"
down_revision: Union[str, None] = "5e7c3b1a9f00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "core_scheduled_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("cron", sa.String(length=255), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("targets", _JSON, nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_result", _JSON, nullable=True),
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
            name="fk_core_scheduled_tasks_owner_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_scheduled_tasks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_scheduled_tasks_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_scheduled_tasks_owner_id"),
            ["owner_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_core_scheduled_tasks_status"), ["status"], unique=False
        )
        batch_op.create_index(
            "ix_core_scheduled_tasks_status_run_at",
            ["status", "run_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("core_scheduled_tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_core_scheduled_tasks_status_run_at")
        batch_op.drop_index(batch_op.f("ix_core_scheduled_tasks_status"))
        batch_op.drop_index(batch_op.f("ix_core_scheduled_tasks_owner_id"))
        batch_op.drop_index(batch_op.f("ix_core_scheduled_tasks_id"))

    op.drop_table("core_scheduled_tasks")
