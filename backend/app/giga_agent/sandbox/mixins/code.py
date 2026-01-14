from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any

class CodeMixin(ABC):
    """Миксин для окружений, поддерживающих выполнение кода."""
    
    @abstractmethod
    async def run_code(self, code: str) -> AsyncGenerator[Dict[str, Any], str]:
        """
        Запускает выполнение кода.
        
        :param code: Исходный код для выполнения.
        :return: Асинхронный генератор, возвращающий результаты выполнения.
        """
        pass