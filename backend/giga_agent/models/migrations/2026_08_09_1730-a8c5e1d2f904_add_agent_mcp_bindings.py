"""add direct MCP bindings for custom agent profiles

Revision ID: a8c5e1d2f904
Revises: ff60fb3fd873
Create Date: 2026-08-09 17:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8c5e1d2f904"
down_revision: Union[str, None] = "ff60fb3fd873"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The previous revision may already have been applied from an interim
    # working-tree version that contained this table. Keep the forward
    # migration safe for that database state as well.
    inspector = sa.inspect(op.get_bind())
    if "core_agent_mcp_bindings" in inspector.get_table_names():
        return

    op.create_table(
        "core_agent_mcp_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["core_mcp_servers.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["core_agent_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id", "mcp_server_id", name="uq_agent_mcp_binding"
        ),
    )
    with op.batch_alter_table("core_agent_mcp_bindings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_agent_mcp_bindings_profile_id"),
            ["profile_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_core_agent_mcp_bindings_mcp_server_id"),
            ["mcp_server_id"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "core_agent_mcp_bindings" not in inspector.get_table_names():
        return

    with op.batch_alter_table("core_agent_mcp_bindings", schema=None) as batch_op:
        indexes = {
            item["name"] for item in inspector.get_indexes("core_agent_mcp_bindings")
        }
        for index_name in (
            "ix_core_agent_mcp_bindings_mcp_server_id",
            "ix_core_agent_mcp_bindings_profile_id",
        ):
            if index_name in indexes:
                batch_op.drop_index(index_name)
    op.drop_table("core_agent_mcp_bindings")
