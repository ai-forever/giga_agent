"""Unit tests for the DB-server ``config_sig`` (giga_agent.modules.mcp.resolved).

The sig must change when the connection *identity* changes (url / auth_type /
settings) but must NOT change when only an OAuth token is refreshed — tokens
live in ``core_oauth_connections``, not in ``McpServer.settings``, so a token
refresh never touches the hashed input. This anti-churn property is what keeps
warm OAuth sessions from being recycled on every refresh.
"""

from __future__ import annotations

import unittest
import uuid

from giga_agent.models.mcp_server import McpServer
from giga_agent.modules.mcp.resolved import resolve_db_server


def _server(**over) -> McpServer:
    kwargs = dict(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Srv",
        url="https://example.com/mcp",
        auth_type="none",
        settings={},
        is_active=True,
        is_local=False,
    )
    kwargs.update(over)
    return McpServer(**kwargs)


class ConfigSigTests(unittest.TestCase):
    def test_same_row_same_sig(self) -> None:
        sid = uuid.uuid4()
        a = resolve_db_server(_server(id=sid))
        b = resolve_db_server(_server(id=sid))
        self.assertIsNotNone(a.config_sig)
        self.assertEqual(a.config_sig, b.config_sig)

    def test_url_change_changes_sig(self) -> None:
        a = resolve_db_server(_server(url="https://a.example.com/mcp"))
        b = resolve_db_server(_server(url="https://b.example.com/mcp"))
        self.assertNotEqual(a.config_sig, b.config_sig)

    def test_auth_type_change_changes_sig(self) -> None:
        a = resolve_db_server(_server(auth_type="none"))
        b = resolve_db_server(_server(auth_type="bearer", settings={"token": "x"}))
        self.assertNotEqual(a.config_sig, b.config_sig)

    def test_bearer_token_edit_changes_sig(self) -> None:
        a = resolve_db_server(_server(auth_type="bearer", settings={"token": "old"}))
        b = resolve_db_server(_server(auth_type="bearer", settings={"token": "new"}))
        self.assertNotEqual(a.config_sig, b.config_sig)

    def test_oauth_client_identity_change_changes_sig(self) -> None:
        a = resolve_db_server(
            _server(auth_type="oauth2", settings={"client_id": "c1", "scope": "r"})
        )
        b = resolve_db_server(
            _server(auth_type="oauth2", settings={"client_id": "c2", "scope": "r"})
        )
        self.assertNotEqual(a.config_sig, b.config_sig)

    def test_oauth_token_refresh_keeps_sig(self) -> None:
        # Tokens live in core_oauth_connections, never in McpServer.settings, so
        # a refresh (which only rewrites that table) leaves the row identical.
        sid = uuid.uuid4()
        settings = {"client_id": "c1", "scope": "r"}
        a = resolve_db_server(_server(id=sid, auth_type="oauth2", settings=settings))
        b = resolve_db_server(_server(id=sid, auth_type="oauth2", settings=settings))
        self.assertEqual(a.config_sig, b.config_sig)

    def test_name_change_keeps_sig(self) -> None:
        # ``name`` is model-facing only and must not recycle the warm session.
        sid = uuid.uuid4()
        a = resolve_db_server(_server(id=sid, name="Alpha"))
        b = resolve_db_server(_server(id=sid, name="Beta"))
        self.assertEqual(a.config_sig, b.config_sig)


if __name__ == "__main__":
    unittest.main()
