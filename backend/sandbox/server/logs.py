"""Structured logging for the SandboxAPI Server.

Пишем в stdout (для `docker logs` в local_docker; в e2b тот же вывод
перенаправляется в файл при запуске). Формат событий — JSON-строки, чтобы
логи парсились машинно. Логируем ошибки + пооперационные метаданные (без
дублирования полных выводов кода/команд — они и так возвращаются вызывающему).
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid

_EVENTS_LOGGER = "sandbox.events"
_configured = False


def setup_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(level)
    # не плодим дубли, если uvicorn уже добавил handler
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)

    events = logging.getLogger(_EVENTS_LOGGER)
    events.setLevel(logging.INFO)
    events.propagate = False
    if not events.handlers:
        ev_handler = logging.StreamHandler(sys.stdout)
        ev_handler.setFormatter(logging.Formatter("%(message)s"))
        events.addHandler(ev_handler)
    _configured = True


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def log_event(kind: str, **fields: object) -> None:
    """Записать одно событие как JSON-строку в stdout."""
    payload = {"ts": round(time.time(), 3), "evt": kind}
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    logging.getLogger(_EVENTS_LOGGER).info(
        json.dumps(payload, ensure_ascii=False, default=str)
    )
