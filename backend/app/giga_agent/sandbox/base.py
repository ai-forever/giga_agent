from abc import ABC, abstractmethod
from typing_extensions import override

from langchain_core.load.serializable import Serializable


class BaseSandbox(Serializable, ABC):
    """Абстрактный базовый класс для виртуальных окружений."""

    @classmethod
    @override
    def is_lc_serializable(cls) -> bool:
        return True

    @abstractmethod
    async def up(self) -> None:
        """Поднимает (запускает) виртуальное окружение."""
        pass

    @abstractmethod
    async def is_up(self) -> bool:
        """Проверяет, поднято ли окружение."""
        pass
