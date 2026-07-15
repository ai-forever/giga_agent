"""generalize mcp oauth tokens into core_oauth_connections

Replaces the MCP-specific ``core_mcp_oauth_tokens`` (FK to ``core_mcp_servers``)
with a provider-agnostic ``core_oauth_connections`` keyed by a free-form
``provider_key`` string. Existing MCP token rows are migrated with
``provider_key = "mcp:<server_id>"``.

The backfill runs in Python (not SQL string concat) so the UUID is normalized to
its canonical dashed form on every dialect — on SQLite ``Uuid`` is stored as a
32-char hex string without dashes, but the runtime key is ``f"mcp:{uuid}"``
(dashed), so a raw ``'mcp:' || server_id`` would not match.

Revision ID: 5e7c3b1a9f00
Revises: 4d6b2a0f3e88
Create Date: 2026-06-24 12:00:00.000000

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.sqltypes import Text

# revision identifiers, used by Alembic.
revision: str = "5e7c3b1a9f00"
down_revision: Union[str, None] = "4d6b2a0f3e88"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")


def _connections_table() -> sa.Table:
    return sa.table(
        "core_oauth_connections",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("provider_key", sa.String(length=255)),
        sa.column("access_token", sa.Text()),
        sa.column("refresh_token", sa.Text()),
        sa.column("expires_at", sa.DateTime(timezone=True)),
        sa.column("token_type", sa.String(length=64)),
        sa.column("scope", sa.Text()),
        sa.column("client_id", sa.Text()),
        sa.column("client_secret", sa.Text()),
        sa.column("metadata_json", _JSON),
    )


def _old_tokens_table() -> sa.Table:
    return sa.table(
        "core_mcp_oauth_tokens",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("server_id", sa.Uuid()),
        sa.column("access_token", sa.Text()),
        sa.column("refresh_token", sa.Text()),
        sa.column("expires_at", sa.DateTime(timezone=True)),
        sa.column("token_type", sa.String(length=64)),
        sa.column("scope", sa.Text()),
        sa.column("client_id", sa.Text()),
        sa.column("client_secret", sa.Text()),
    )


def upgrade() -> None:
    op.create_table(
        "core_oauth_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_type", sa.String(length=64), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("client_secret", sa.Text(), nullable=True),
        sa.Column("metadata_json", _JSON, nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider_key", name="uq_oauth_conn_user_provider"
        ),
    )
    with op.batch_alter_table("core_oauth_connections", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_core_oauth_connections_id"), ["id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_core_oauth_connections_user_id"),
            ["user_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_core_oauth_connections_provider_key"),
            ["provider_key"],
            unique=False,
        )

    # --- backfill MCP tokens as provider_key="mcp:<server_id>" --------------- #
    bind = op.get_bind()
    old = _old_tokens_table()
    rows = bind.execute(
        sa.select(
            old.c.user_id,
            old.c.server_id,
            old.c.access_token,
            old.c.refresh_token,
            old.c.expires_at,
            old.c.token_type,
            old.c.scope,
            old.c.client_id,
            old.c.client_secret,
        )
    ).fetchall()
    if rows:
        payload = [
            {
                "id": uuid.uuid4(),
                "user_id": r.user_id,
                "provider_key": f"mcp:{uuid.UUID(str(r.server_id))}",
                "access_token": r.access_token,
                "refresh_token": r.refresh_token,
                "expires_at": r.expires_at,
                "token_type": r.token_type,
                "scope": r.scope,
                "client_id": r.client_id,
                "client_secret": r.client_secret,
                "metadata_json": {},
            }
            for r in rows
        ]
        op.bulk_insert(_connections_table(), payload)

    with op.batch_alter_table("core_mcp_oauth_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_mcp_oauth_tokens_server_id"))
        batch_op.drop_index(batch_op.f("ix_core_mcp_oauth_tokens_user_id"))
        batch_op.drop_index(batch_op.f("ix_core_mcp_oauth_tokens_id"))
    op.drop_table("core_mcp_oauth_tokens")


def downgrade() -> None:
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

    # --- back-copy only the mcp:* connections ------------------------------- #
    bind = op.get_bind()
    conns = _connections_table()
    rows = bind.execute(
        sa.select(
            conns.c.user_id,
            conns.c.provider_key,
            conns.c.access_token,
            conns.c.refresh_token,
            conns.c.expires_at,
            conns.c.token_type,
            conns.c.scope,
            conns.c.client_id,
            conns.c.client_secret,
        ).where(conns.c.provider_key.like("mcp:%"))
    ).fetchall()
    payload = []
    for r in rows:
        try:
            server_id = uuid.UUID(r.provider_key[len("mcp:") :])
        except (ValueError, TypeError):
            continue
        payload.append(
            {
                "id": uuid.uuid4(),
                "user_id": r.user_id,
                "server_id": server_id,
                "access_token": r.access_token,
                "refresh_token": r.refresh_token,
                "expires_at": r.expires_at,
                "token_type": r.token_type,
                "scope": r.scope,
                "client_id": r.client_id,
                "client_secret": r.client_secret,
            }
        )
    if payload:
        op.bulk_insert(_old_tokens_table(), payload)

    with op.batch_alter_table("core_oauth_connections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_core_oauth_connections_provider_key"))
        batch_op.drop_index(batch_op.f("ix_core_oauth_connections_user_id"))
        batch_op.drop_index(batch_op.f("ix_core_oauth_connections_id"))
    op.drop_table("core_oauth_connections")
