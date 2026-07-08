"""make core_mcp_oauth_tokens.access_token nullable

A token row may hold only DCR client credentials during the OAuth flow, before
any access token has been issued. Reconciles databases migrated by the initial
revision while ``access_token`` was still NOT NULL.

Revision ID: 4d6b2a0f3e88
Revises: 3c5a1f9e2d77
Create Date: 2026-06-18 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4d6b2a0f3e88"
down_revision: Union[str, None] = "3c5a1f9e2d77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_mcp_oauth_tokens", schema=None) as batch_op:
        batch_op.alter_column(
            "access_token", existing_type=sa.Text(), nullable=True
        )


def downgrade() -> None:
    with op.batch_alter_table("core_mcp_oauth_tokens", schema=None) as batch_op:
        batch_op.alter_column(
            "access_token", existing_type=sa.Text(), nullable=False
        )
