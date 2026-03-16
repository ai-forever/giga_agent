from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional


class CodeMixin(ABC):
    """Миксин для окружений, поддерживающих выполнение кода."""

    @abstractmethod
    async def run_code(
        self, code: str, kernel_id: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], str]:
        """
        Запускает выполнение кода.

        :param code: Исходный код для выполнения.
        :param kernel_id: Kernel ID.
        :return: Асинхронный генератор, возвращающий результаты выполнения.
        """
        pass
