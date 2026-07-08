"""add_core_invites

Приглашения в команду: токен хранится как SHA-256 хэш, поддерживаются
персональные (max_uses=1) и командные (max_uses=N) ссылки.

Revision ID: b2c3d4e5f607
Revises: a1b2c3d4e5f6
Create Date: 2026-07-08 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.sqltypes import Text

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f607"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "core_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column(
            "role", sa.String(length=16), nullable=False, server_default="member"
        ),
        sa.Column("group_ids", _JSON, nullable=True),
        sa.Column(
            "copy_runtime_ids", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "copy_module_secrets",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
            ["created_by"], ["core_users.id"], name="fk_core_invites_created_by"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_core_invites_id"), "core_invites", ["id"], unique=False)
    op.create_index(
        op.f("ix_core_invites_token_hash"),
        "core_invites",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_core_invites_created_by"),
        "core_invites",
        ["created_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_core_invites_created_by"), table_name="core_invites")
    op.drop_index(op.f("ix_core_invites_token_hash"), table_name="core_invites")
    op.drop_index(op.f("ix_core_invites_id"), table_name="core_invites")
    op.drop_table("core_invites")
