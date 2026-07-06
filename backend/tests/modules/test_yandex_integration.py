import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from giga_agent.modules.integrations.yandex_disk import YandexDiskModule
from giga_agent.modules.integrations.yandex_disk.provider import (
    build_yandex_disk_provider,
)
from giga_agent.modules.integrations.yandex_mail import YandexMailModule
from giga_agent.modules.integrations.yandex_mail.provider import (
    build_yandex_mail_provider,
)
from giga_agent.modules.integrations.yandex_tracker import YandexTrackerModule
from giga_agent.modules.integrations.yandex_tracker.auth import YANDEX_TRACKER_ORG_ID
from giga_agent.modules.integrations.yandex_tracker.provider import (
    build_yandex_tracker_provider,
)
from giga_agent.modules.integrations.yandex_calendar import YandexCalendarModule
from giga_agent.modules.integrations.yandex_calendar.provider import (
    build_yandex_calendar_provider,
)

_CAL_PKG = "giga_agent.modules.integrations.yandex_calendar.provider"


class YandexProviderContractTests(unittest.TestCase):
    def test_disk_provider(self):
        info = build_yandex_disk_provider().info()
        self.assertEqual(info.key, "yandex_disk")
        self.assertEqual(info.auth_kind, "oauth2")
        self.assertIn("cloud_api:disk.read", build_yandex_disk_provider()._cfg.scope)

    def test_tracker_provider(self):
        p = build_yandex_tracker_provider()
        self.assertEqual(p.key, "yandex_tracker")
        self.assertIn("tracker:read", p._cfg.scope)

    def test_mail_provider_scope(self):
        scope = build_yandex_mail_provider()._cfg.scope
        for token in ("mail:imap_full", "mail:smtp", "login:email"):
            self.assertIn(token, scope)

    def test_client_creds_from_env(self):
        # Креды читаются из окружения, не из conf.py.
        with patch.dict(
            "os.environ",
            {"YANDEX_DISK_CLIENT_ID": "cid", "YANDEX_DISK_CLIENT_SECRET": "sec"},
        ):
            cfg = build_yandex_disk_provider()._cfg
            self.assertEqual(cfg.client_id, "cid")
            self.assertEqual(cfg.client_secret, "sec")


class YandexModuleGatingTests(unittest.IsolatedAsyncioTestCase):
    async def test_hidden_when_app_not_configured(self):
        # Без env-кредов приложения провайдер не объявляется, модуль скрыт.
        for module in (YandexDiskModule(), YandexTrackerModule(), YandexMailModule()):
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(module.get_providers(), [])
                self.assertFalse(
                    await module.is_enabled(types.SimpleNamespace(id=uuid.uuid4()))
                )

    async def test_disk_tools_when_connected(self):
        module = YandexDiskModule()
        user = types.SimpleNamespace(id=uuid.uuid4(), secrets={})
        with patch.object(
            YandexDiskModule, "get_providers", return_value=[object()]
        ), patch.object(
            YandexDiskModule, "providers_connected", AsyncMock(return_value=True)
        ):
            names = [t.name for t in await module._get_tools(user, agent=object())]
        self.assertIn("disk_list_files", names)

    async def test_tracker_tools_require_org(self):
        module = YandexTrackerModule()
        with patch.object(
            YandexTrackerModule, "get_providers", return_value=[object()]
        ), patch.object(
            YandexTrackerModule, "providers_connected", AsyncMock(return_value=True)
        ):
            no_org = types.SimpleNamespace(id=uuid.uuid4(), secrets={})
            self.assertEqual(await module._get_tools(no_org, agent=object()), [])
            with_org = types.SimpleNamespace(
                id=uuid.uuid4(), secrets={YANDEX_TRACKER_ORG_ID: "org-1"}
            )
            names = [t.name for t in await module._get_tools(with_org, agent=object())]
        self.assertTrue(any(n.startswith("tracker_") for n in names))


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class YandexCalendarProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_provider_contract(self):
        info = build_yandex_calendar_provider().info()
        self.assertEqual(info.key, "yandex_calendar")
        self.assertEqual(info.auth_kind, "manual_token")
        self.assertEqual(
            [f.key for f in info.manual_fields], ["email", "app_password"]
        )

    async def test_store_requires_both_fields(self):
        provider = build_yandex_calendar_provider()
        with self.assertRaisesRegex(ValueError, "email"):
            await provider.store_manual_token(
                user_id=uuid.uuid4(), fields={"email": "a@ya.ru"}
            )

    async def test_store_rejects_invalid_caldav(self):
        provider = build_yandex_calendar_provider()
        with patch(f"{_CAL_PKG}._validate_caldav", return_value=False):
            with self.assertRaisesRegex(ValueError, "Календарь"):
                await provider.store_manual_token(
                    user_id=uuid.uuid4(),
                    fields={"email": "a@ya.ru", "app_password": "bad"},
                )

    async def test_store_persists_on_valid_caldav(self):
        provider = build_yandex_calendar_provider()
        captured = {}

        class _FakeRepo:
            def __init__(self, _session):
                pass

            async def upsert(self, **kwargs):
                captured.update(kwargs)

        with patch(f"{_CAL_PKG}._validate_caldav", return_value=True), patch(
            f"{_CAL_PKG}.get_session_factory", AsyncMock(return_value=_FakeSession)
        ), patch(f"{_CAL_PKG}.OAuthConnectionRepository", _FakeRepo):
            await provider.store_manual_token(
                user_id=uuid.uuid4(),
                fields={"email": "a@ya.ru", "app_password": "secret"},
            )
        self.assertEqual(captured["provider_key"], "yandex_calendar")
        self.assertEqual(captured["access_token"], "secret")
        self.assertEqual(captured["metadata_json"]["email"], "a@ya.ru")
