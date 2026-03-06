"""change resource permissions owner_id to text

Revision ID: 6c2f0f4a9b12
Revises: a6243e1c9b3f
Create Date: 2026-02-28 21:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6c2f0f4a9b12"
down_revision: Union[str, None] = "a6243e1c9b3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "core_resource_permissions",
            "owner_id",
            existing_type=sa.Uuid(),
            type_=sa.Text(),
            existing_nullable=False,
            postgresql_using="owner_id::text",
        )
        return

    with op.batch_alter_table("core_resource_permissions", schema=None) as batch_op:
        batch_op.alter_column(
            "owner_id",
            existing_type=sa.Uuid(),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Public ACL rows cannot be represented by UUID; remove them before cast-back.
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM core_resource_permissions WHERE owner_id = :public_owner_id"),
        {"public_owner_id": "*"},
    )

    if bind.dialect.name == "postgresql":
        op.alter_column(
            "core_resource_permissions",
            "owner_id",
            existing_type=sa.Text(),
            type_=sa.Uuid(),
            existing_nullable=False,
            postgresql_using="owner_id::uuid",
        )
        return

    with op.batch_alter_table("core_resource_permissions", schema=None) as batch_op:
        batch_op.alter_column(
            "owner_id",
            existing_type=sa.Text(),
            type_=sa.Uuid(),
            existing_nullable=False,
        )
