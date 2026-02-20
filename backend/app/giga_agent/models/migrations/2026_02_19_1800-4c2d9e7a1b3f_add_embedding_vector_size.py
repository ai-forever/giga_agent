"""add embeddings vector_size

Revision ID: 4c2d9e7a1b3f
Revises: 3a7c9e1f2b4d
Create Date: 2026-02-19 18:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c2d9e7a1b3f"
down_revision: Union[str, None] = "3a7c9e1f2b4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_embeddings", schema=None) as batch_op:
        batch_op.add_column(
            # SQLite не умеет добавлять NOT NULL колонку без server_default,
            # если в таблице уже есть строки.
            sa.Column("vector_size", sa.Integer(), nullable=False, server_default="0")
        )

    # Не оставляем дефолт, чтобы новые записи обязаны были задавать vector_size явно.
    with op.batch_alter_table("core_embeddings", schema=None) as batch_op:
        batch_op.alter_column("vector_size", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("core_embeddings", schema=None) as batch_op:
        batch_op.drop_column("vector_size")
