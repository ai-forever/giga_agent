"""Подписанный `state` для OAuth-редиректа Яндекса.

Минтится только на аутентифицированном `/start`, поэтому в нём можно безопасно
переносить identity пользователя: callback не полагается на куки (top-level
редирект со стороннего домена), а доверяет HMAC-подписи на серверном secret_key.
Зависимостей нет — base64url(JSON) + HMAC-SHA256.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from giga_agent.conf import get_settings

# Время жизни state: пользователь должен успеть пройти согласие.
STATE_TTL_SECONDS = 600


def _signing_key() -> bytes:
    # Fail-closed: тот же secret_key, что подписывает auth-JWT (security.py).
    # Без него state стал бы подделываемым (подмена identity в callback) —
    # поэтому не падаем на дефолт, а требуем ключ, как и JWT-подпись.
    secret = get_settings().giga_agent_secret_key
    if not secret:
        raise RuntimeError(
            "GIGA_AGENT_SECRET_KEY не задан — подпись OAuth-state невозможна."
        )
    return secret.encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_state(*, user_id: str, module_id: str, flow: str) -> str:
    payload = {
        "u": user_id,
        "m": module_id,
        "f": flow,
        "exp": int(time.time()) + STATE_TTL_SECONDS,
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_state(state: str) -> dict[str, Any]:
    """Проверяет подпись и срок жизни. Бросает ValueError при любой проблеме."""
    try:
        body, sig = state.split(".", 1)
    except ValueError as exc:
        raise ValueError("Некорректный state") from exc

    expected = _b64e(
        hmac.new(_signing_key(), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Подпись state не совпала")

    payload = json.loads(_b64d(body))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Срок действия state истёк")
    return payload
