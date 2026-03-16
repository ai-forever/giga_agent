"""init telegram

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-16 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_bots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("bot_token", sa.String(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("bot_username", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core_users.id"],
            name="fk_telegram_bots_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telegram_bots_id"), "telegram_bots", ["id"])
    op.create_index(
        op.f("ix_telegram_bots_user_id"), "telegram_bots", ["user_id"], unique=True
    )

    op.create_table(
        "telegram_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("langgraph_thread_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["telegram_bots.id"],
            name="fk_telegram_threads_bot_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telegram_threads_id"), "telegram_threads", ["id"])
    op.create_index(
        op.f("ix_telegram_threads_bot_id"), "telegram_threads", ["bot_id"]
    )


def downgrade() -> None:
    op.drop_table("telegram_threads")
    op.drop_table("telegram_bots")
