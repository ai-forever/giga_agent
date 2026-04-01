"""support telegram group chats

Revision ID: c03f40176fb8
Revises: c3d4e5f6a7b8
Create Date: 2026-04-01 01:35:21.105941

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
# revision identifiers, used by Alembic.
revision: str = "c03f40176fb8"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("telegram_contacts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("telegram_chat_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("telegram_chat_title", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("telegram_contacts", schema=None) as batch_op:
        batch_op.drop_column("telegram_chat_title")
        batch_op.drop_column("telegram_chat_type")

