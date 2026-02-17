"""connectors refactor

Revision ID: c6f53f2288f4
Revises: 9a0d4ddf11c2
Create Date: 2026-02-17 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c6f53f2288f4"
down_revision: Union[str, None] = "9a0d4ddf11c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Create connectors table.
    op.create_table(
        "core_connectors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "settings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
            ["owner_id"],
            ["core_users.id"],
            name="fk_core_connectors_owner_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_connectors", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_core_connectors_id"), ["id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_core_connectors_owner_id"), ["owner_id"], unique=False
        )

    # 2) Copy existing LLM providers into connectors.
    op.execute(
        sa.text(
            """
            INSERT INTO core_connectors (
                id, owner_id, type, name, settings, is_active, created_at, updated_at
            )
            SELECT
                id, owner_id, type, name, settings, is_active, created_at, updated_at
            FROM core_llm_providers
            """
        )
    )

    # 3) core_llms: add explicit type + provider_id -> connector_id (cascade FK).
    with op.batch_alter_table("core_llms", schema=None) as batch_op:
        batch_op.add_column(sa.Column("type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("connector_id", sa.Uuid(), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE core_llms
            SET
                type = (
                    SELECT p.type
                    FROM core_llm_providers AS p
                    WHERE p.id = core_llms.provider_id
                ),
                connector_id = provider_id
            """
        )
    )

    with op.batch_alter_table("core_llms", schema=None) as batch_op:
        batch_op.alter_column("type", existing_type=sa.String(length=50), nullable=False)
        batch_op.alter_column("connector_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.drop_index(batch_op.f("ix_core_llms_provider_id"))
        batch_op.create_index(
            batch_op.f("ix_core_llms_connector_id"),
            ["connector_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_core_llms_connector_id",
            "core_connectors",
            ["connector_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_column("provider_id")

    # 4) core_image_generators: llm_provider_id -> connector_id (cascade FK).
    with op.batch_alter_table("core_image_generators", schema=None) as batch_op:
        batch_op.add_column(sa.Column("connector_id", sa.Uuid(), nullable=True))

    op.execute(sa.text("UPDATE core_image_generators SET connector_id = llm_provider_id"))

    with op.batch_alter_table("core_image_generators", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_image_generators_connector_id"),
            ["connector_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_core_image_generators_connector_id",
            "core_connectors",
            ["connector_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_index(batch_op.f("ix_core_image_generators_llm_provider_id"))
        batch_op.drop_column("llm_provider_id")

    # 5) core_search_engines: add optional connector_id (cascade FK).
    with op.batch_alter_table("core_search_engines", schema=None) as batch_op:
        batch_op.add_column(sa.Column("connector_id", sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_core_search_engines_connector_id"),
            ["connector_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_core_search_engines_connector_id",
            "core_connectors",
            ["connector_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # 6) Remove legacy providers table.
    with op.batch_alter_table("core_llm_providers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_llm_providers_owner_id"))
        batch_op.drop_index(batch_op.f("ix_core_llm_providers_id"))
    op.drop_table("core_llm_providers")


def downgrade() -> None:
    # 1) Restore legacy providers table.
    op.create_table(
        "core_llm_providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "settings",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["owner_id"], ["core_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("core_llm_providers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_llm_providers_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_llm_providers_owner_id"), ["owner_id"], unique=False
        )

    # Copy connectors back into providers.
    op.execute(
        sa.text(
            """
            INSERT INTO core_llm_providers (
                id, owner_id, type, name, settings, is_active, created_at, updated_at
            )
            SELECT
                id, owner_id, type, name, settings, is_active, created_at, updated_at
            FROM core_connectors
            """
        )
    )

    # 2) core_llms: connector_id -> provider_id, remove type.
    with op.batch_alter_table("core_llms", schema=None) as batch_op:
        batch_op.add_column(sa.Column("provider_id", sa.Uuid(), nullable=True))

    op.execute(sa.text("UPDATE core_llms SET provider_id = connector_id"))

    with op.batch_alter_table("core_llms", schema=None) as batch_op:
        batch_op.alter_column("provider_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_index(
            batch_op.f("ix_core_llms_provider_id"),
            ["provider_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            None,
            "core_llm_providers",
            ["provider_id"],
            ["id"],
        )
        batch_op.drop_index(batch_op.f("ix_core_llms_connector_id"))
        batch_op.drop_column("connector_id")
        batch_op.drop_column("type")

    # 3) core_image_generators: connector_id -> llm_provider_id.
    with op.batch_alter_table("core_image_generators", schema=None) as batch_op:
        batch_op.add_column(sa.Column("llm_provider_id", sa.Uuid(), nullable=True))

    op.execute(
        sa.text("UPDATE core_image_generators SET llm_provider_id = connector_id")
    )

    with op.batch_alter_table("core_image_generators", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_image_generators_llm_provider_id"),
            ["llm_provider_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_core_image_generators_llm_provider_id",
            "core_llm_providers",
            ["llm_provider_id"],
            ["id"],
        )
        batch_op.drop_index(batch_op.f("ix_core_image_generators_connector_id"))
        batch_op.drop_column("connector_id")

    # 4) core_search_engines: drop connector_id.
    with op.batch_alter_table("core_search_engines", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_search_engines_connector_id"))
        batch_op.drop_column("connector_id")

    # 5) Drop connectors table.
    with op.batch_alter_table("core_connectors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_connectors_owner_id"))
        batch_op.drop_index(batch_op.f("ix_core_connectors_id"))
    op.drop_table("core_connectors")
