"""add_mcp_servers_and_oauth_tokens_tables

Revision ID: 3c5a1f9e2d77
Revises: 9a4f8d2e1c3b
Create Date: 2026-06-18 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.sqltypes import Text

# revision identifiers, used by Alembic.
revision: str = "3c5a1f9e2d77"
down_revision: Union[str, None] = "9a4f8d2e1c3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "core_mcp_servers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column(
            "settings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_local", sa.Boolean(), nullable=False),
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
            ["owner_id"], ["core_users.id"], name="fk_core_mcp_servers_owner_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_mcp_servers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_mcp_servers_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_mcp_servers_owner_id"), ["owner_id"], unique=False
        )

    op.create_table(
        "core_mcp_oauth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_type", sa.String(length=64), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("client_secret", sa.Text(), nullable=True),
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
            ["server_id"],
            ["core_mcp_servers.id"],
            name="fk_core_mcp_oauth_tokens_server_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "server_id", name="uq_mcp_oauth_user_server"),
    )
    with op.batch_alter_table("core_mcp_oauth_tokens", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_mcp_oauth_tokens_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_mcp_oauth_tokens_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_mcp_oauth_tokens_server_id"),
            ["server_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("core_mcp_oauth_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_mcp_oauth_tokens_server_id"))
        batch_op.drop_index(batch_op.f("ix_core_mcp_oauth_tokens_user_id"))
        batch_op.drop_index(batch_op.f("ix_core_mcp_oauth_tokens_id"))
    op.drop_table("core_mcp_oauth_tokens")

    with op.batch_alter_table("core_mcp_servers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_mcp_servers_owner_id"))
        batch_op.drop_index(batch_op.f("ix_core_mcp_servers_id"))
    op.drop_table("core_mcp_servers")
