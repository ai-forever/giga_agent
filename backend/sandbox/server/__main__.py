"""Entry point: ``python -m sandbox_server``."""

from __future__ import annotations

import uvicorn

from .config import get_settings
from .logs import setup_logging


def main() -> None:
    settings = get_settings()
    setup_logging()
    uvicorn.run(
        "sandbox_server.app:app",
        host=settings.host,
        port=settings.port,
        log_level="info" if settings.request_log else "warning",
        # uvicorn access-log выключен: он пишет полный path с query-строкой, куда
        # WS-клиенты кладут ?token=<secret>. Свой structured HTTP-лог (app.py,
        # log_event "http") токен не пишет.
        access_log=False,
        ws_max_size=32 * 1024 * 1024,  # соответствует WS_MAX_SIZE в jupyter.py
    )


if __name__ == "__main__":
    main()
