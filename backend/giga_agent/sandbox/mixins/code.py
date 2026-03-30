from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator


class CodeMixin(ABC):
    """Миксин для окружений, поддерживающих выполнение кода."""

    @abstractmethod
    async def run_code(
        self,
        code: str,
        kernel_id: str | None = None,
        *,
        allow_stdin: bool = True,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], str]:
        """
        Запускает выполнение кода.

        :param code: Исходный код для выполнения.
        :param kernel_id: Kernel ID.
        :param allow_stdin: Разрешить ли интерактивный stdin во время выполнения.
        :param kwargs: Дополнительные параметры выполнения, поддерживаемые реализацией.
        :return: Асинхронный генератор, возвращающий результаты выполнения.
        """
        pass
