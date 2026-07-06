from __future__ import annotations

from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


def load_dev_env() -> None:
    """Загрузить `.env` в окружение для локального dev-CLI (команды dev/cli).

    Уже выставленные переменные окружения имеют приоритет (`override=False`) —
    `.env` это dev-удобство, а не подмена реального окружения. No-op, если файл
    не найден.
    """
    from dotenv import find_dotenv, load_dotenv

    path = find_dotenv(usecwd=True)
    if not path:
        return
    load_dotenv(path, override=False)
    logger.info("Loaded environment from %s", path)
