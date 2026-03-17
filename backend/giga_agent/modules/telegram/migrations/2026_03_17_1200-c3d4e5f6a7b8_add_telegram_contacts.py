"""add telegram_contacts

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(), nullable=True),
        sa.Column("telegram_first_name", sa.String(), nullable=True),
        sa.Column("telegram_last_name", sa.String(), nullable=True),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default="false"),
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
            ["bot_id"],
            ["telegram_bots.id"],
            name="fk_telegram_contacts_bot_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telegram_contacts_id"), "telegram_contacts", ["id"])
    op.create_index(
        op.f("ix_telegram_contacts_bot_id"), "telegram_contacts", ["bot_id"]
    )
    op.create_index(
        op.f("ix_telegram_contacts_chat_id"),
        "telegram_contacts",
        ["telegram_chat_id"],
    )


def downgrade() -> None:
    op.drop_table("telegram_contacts")
