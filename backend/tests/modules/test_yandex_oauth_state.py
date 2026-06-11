"""Тесты подписанного OAuth-state Яндекса — трастовый бордер callback-флоу.

verify_state — единственная защита cookieless-колбэка: баг здесь = принятие
подделанной identity. Покрываем round-trip, тампер, подпись, срок, формат и
fail-closed при отсутствии secret_key.
"""

import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from giga_agent.conf import reset_settings_cache
from giga_agent.modules.yandex_oauth import state


@contextmanager
def _env(values: dict, *, clear: bool = False):
    reset_settings_cache()
    with patch.dict(os.environ, values, clear=clear):
        reset_settings_cache()
        try:
            yield
        finally:
            reset_settings_cache()


class YandexOAuthStateTests(unittest.TestCase):
    def test_round_trip(self):
        with _env({"GIGA_AGENT_SECRET_KEY": "test-secret"}):
            token = state.issue_state(
                user_id="u-123", module_id="yandex_disk", flow="callback"
            )
            payload = state.verify_state(token)
            self.assertEqual(payload["u"], "u-123")
            self.assertEqual(payload["m"], "yandex_disk")
            self.assertEqual(payload["f"], "callback")

    def test_tampered_body_rejected(self):
        with _env({"GIGA_AGENT_SECRET_KEY": "test-secret"}):
            token = state.issue_state(
                user_id="u-1", module_id="yandex_disk", flow="callback"
            )
            body, sig = token.split(".", 1)
            forged = state._b64e(b'{"u":"attacker","m":"yandex_disk","f":"callback","exp":9999999999}')
            with self.assertRaises(ValueError):
                state.verify_state(f"{forged}.{sig}")

    def test_bad_signature_rejected(self):
        with _env({"GIGA_AGENT_SECRET_KEY": "test-secret"}):
            token = state.issue_state(
                user_id="u-1", module_id="yandex_disk", flow="callback"
            )
            body, _ = token.split(".", 1)
            with self.assertRaises(ValueError):
                state.verify_state(f"{body}.{state._b64e(b'wrong-sig')}")

    def test_different_secret_rejected(self):
        with _env({"GIGA_AGENT_SECRET_KEY": "secret-a"}):
            token = state.issue_state(
                user_id="u-1", module_id="yandex_disk", flow="callback"
            )
        with _env({"GIGA_AGENT_SECRET_KEY": "secret-b"}):
            with self.assertRaises(ValueError):
                state.verify_state(token)

    def test_expired_rejected(self):
        with _env({"GIGA_AGENT_SECRET_KEY": "test-secret"}):
            # issue at t=1000, verify at t=1000+TTL+1 → просрочен
            with patch.object(state.time, "time", return_value=1000.0):
                token = state.issue_state(
                    user_id="u-1", module_id="yandex_disk", flow="callback"
                )
            later = 1000.0 + state.STATE_TTL_SECONDS + 1
            with patch.object(state.time, "time", return_value=later):
                with self.assertRaises(ValueError):
                    state.verify_state(token)

    def test_malformed_no_dot_rejected(self):
        with _env({"GIGA_AGENT_SECRET_KEY": "test-secret"}):
            with self.assertRaises(ValueError):
                state.verify_state("not-a-valid-state")

    def test_missing_secret_fails_closed(self):
        # Нет secret_key → подпись невозможна, fail-closed (RuntimeError).
        with _env({}, clear=True):
            with self.assertRaises(RuntimeError):
                state.issue_state(
                    user_id="u-1", module_id="yandex_disk", flow="callback"
                )


if __name__ == "__main__":
    unittest.main()
