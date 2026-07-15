"""add_core_usage_events

Журнал вызовов LLM для страницы «Команда» (видимость потребления).

Revision ID: c3d4e5f60718
Revises: b2c3d4e5f607
Create Date: 2026-07-08 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f60718"
down_revision: Union[str, None] = "b2c3d4e5f607"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "core_usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_core_usage_events_user_id"),
        "core_usage_events",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_core_usage_events_created_at"),
        "core_usage_events",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_core_usage_events_created_at"), table_name="core_usage_events"
    )
    op.drop_index(op.f("ix_core_usage_events_user_id"), table_name="core_usage_events")
    op.drop_table("core_usage_events")
