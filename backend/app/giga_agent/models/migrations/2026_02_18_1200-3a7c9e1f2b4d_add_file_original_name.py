"""add file original_name

Revision ID: 3a7c9e1f2b4d
Revises: 1d2f3a4b5c6d
Create Date: 2026-02-18 12:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a7c9e1f2b4d"
down_revision: Union[str, None] = "1d2f3a4b5c6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("core_files", schema=None) as batch_op:
        batch_op.add_column(sa.Column("original_name", sa.String(length=1024), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, sandbox_path FROM core_files")).fetchall()
    for file_id, sandbox_path in rows:
        raw = (sandbox_path or "").rstrip("/")
        name = raw.split("/")[-1] if raw else ""
        conn.execute(
            sa.text("UPDATE core_files SET original_name=:name WHERE id=:id"),
            {"name": name or "download.bin", "id": file_id},
        )

    with op.batch_alter_table("core_files", schema=None) as batch_op:
        batch_op.alter_column("original_name", existing_type=sa.String(length=1024), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("core_files", schema=None) as batch_op:
        batch_op.drop_column("original_name")

