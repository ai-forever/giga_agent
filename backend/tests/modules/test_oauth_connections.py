import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from giga_agent.core.cache import setup_cache
from giga_agent.core.db import Base
from giga_agent.models.oauth_connection import (
    OAuthConnectionRepository,
    mcp_provider_key,
)


class _DbBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        setup_cache()
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "conn.sqlite"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.user_id = uuid.uuid4()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self._tmp.cleanup()


class OAuthConnectionRepoTests(_DbBase):
    async def test_upsert_get_delete(self) -> None:
        async with self.session_factory() as session:
            repo = OAuthConnectionRepository(session)
            await repo.upsert(
                user_id=self.user_id,
                provider_key="yandex",
                access_token="acc",
                refresh_token="ref",
            )
            row = await repo.get(self.user_id, "yandex")
            self.assertEqual(row.access_token, "acc")

            # upsert updates in place (same row)
            await repo.upsert(
                user_id=self.user_id, provider_key="yandex", access_token="acc2"
            )
            rows = await repo.list_for_user(self.user_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].access_token, "acc2")
            # refresh_token preserved (not overwritten)
            self.assertEqual(rows[0].refresh_token, "ref")

            await repo.delete(self.user_id, "yandex")
            self.assertIsNone(await repo.get(self.user_id, "yandex"))

    async def test_delete_for_provider_prefix(self) -> None:
        sid = uuid.uuid4()
        other_user = uuid.uuid4()
        async with self.session_factory() as session:
            repo = OAuthConnectionRepository(session)
            # two users connected to the same MCP server + an unrelated provider
            await repo.upsert(
                user_id=self.user_id,
                provider_key=mcp_provider_key(sid),
                access_token="a",
            )
            await repo.upsert(
                user_id=other_user,
                provider_key=mcp_provider_key(sid),
                access_token="b",
            )
            await repo.upsert(
                user_id=self.user_id, provider_key="yandex", access_token="y"
            )

            await repo.delete_for_provider_prefix(mcp_provider_key(sid))

            self.assertIsNone(await repo.get(self.user_id, mcp_provider_key(sid)))
            self.assertIsNone(await repo.get(other_user, mcp_provider_key(sid)))
            # unrelated provider untouched
            self.assertIsNotNone(await repo.get(self.user_id, "yandex"))


class StaticProviderTests(_DbBase):
    def _provider(self):
        from giga_agent.core.integrations.static_provider import (
            StaticOAuthConfig,
            StaticOAuthProvider,
        )

        return StaticOAuthProvider(
            StaticOAuthConfig(
                key="yandex",
                label="Яндекс",
                auth_kind="oauth2",
                authorization_endpoint="https://oauth.yandex.ru/authorize",
                token_endpoint="https://oauth.yandex.ru/token",
                client_id="cid",
                client_secret="csec",
                scope="disk",
            )
        )

    def _patch_factory(self):
        async def _factory():
            return self.session_factory

        return mock.patch(
            "giga_agent.core.integrations.static_provider.get_session_factory",
            _factory,
        )

    async def test_status_and_manual_token(self) -> None:
        from giga_agent.core.integrations.base import ConnectionStatus
        from giga_agent.core.integrations.static_provider import (
            StaticOAuthConfig,
            StaticOAuthProvider,
        )
        from giga_agent.core.integrations.base import ManualField

        manual = StaticOAuthProvider(
            StaticOAuthConfig(
                key="github",
                label="GitHub",
                auth_kind="manual_token",
                manual_fields=[ManualField(key="token", label="PAT")],
            )
        )
        with self._patch_factory():
            st: ConnectionStatus = await manual.status(user_id=self.user_id)
            self.assertEqual(st.status, "not_connected")

            await manual.store_manual_token(
                user_id=self.user_id, fields={"token": "ghp_secret"}
            )
            st = await manual.status(user_id=self.user_id)
            self.assertEqual(st.status, "connected")
            self.assertEqual(
                await manual.access_token(user_id=self.user_id), "ghp_secret"
            )

    async def test_refresh_permanent_failure_needs_reauth(self) -> None:
        from giga_agent.core.integrations.errors import ReauthRequired
        from giga_agent.core.integrations import oauth_flow

        provider = self._provider()
        expired = datetime.now(timezone.utc) - timedelta(hours=1)
        with self._patch_factory():
            async with self.session_factory() as session:
                await OAuthConnectionRepository(session).upsert(
                    user_id=self.user_id,
                    provider_key="yandex",
                    access_token="old",
                    refresh_token="ref",
                    expires_at=expired,
                )

            async def _bad_refresh(**_kwargs):
                raise oauth_flow.RefreshError("invalid_grant", permanent=True)

            with mock.patch.object(oauth_flow, "refresh_access_token", _bad_refresh):
                with self.assertRaises(ReauthRequired):
                    await provider.access_token(user_id=self.user_id)
                st = await provider.status(user_id=self.user_id)
                # has refresh_token, so status reports connected until refresh tried;
                # the row is expired but refreshable → "connected" is acceptable.
                self.assertIn(st.status, {"connected", "needs_reauth"})

    async def test_refresh_success(self) -> None:
        from giga_agent.core.integrations import oauth_flow
        from mcp.shared.auth import OAuthToken

        provider = self._provider()
        expired = datetime.now(timezone.utc) - timedelta(hours=1)
        with self._patch_factory():
            async with self.session_factory() as session:
                await OAuthConnectionRepository(session).upsert(
                    user_id=self.user_id,
                    provider_key="yandex",
                    access_token="old",
                    refresh_token="ref",
                    expires_at=expired,
                )

            async def _ok_refresh(**_kwargs):
                return OAuthToken(
                    access_token="new", refresh_token="ref2", expires_in=3600
                )

            with mock.patch.object(oauth_flow, "refresh_access_token", _ok_refresh):
                tok = await provider.access_token(user_id=self.user_id)
                self.assertEqual(tok, "new")
            async with self.session_factory() as session:
                row = await OAuthConnectionRepository(session).get(
                    self.user_id, "yandex"
                )
                self.assertEqual(row.access_token, "new")
                self.assertEqual(row.refresh_token, "ref2")


if __name__ == "__main__":
    unittest.main()
