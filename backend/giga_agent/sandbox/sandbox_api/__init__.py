"""Client for the in-guest SandboxAPI Server (see backend/sandbox/server).

Тонкий клиент + миксин, через которые рантаймы (local_docker, e2b, а также
будущий нативный провайдер sandbox_api) выполняют код, shell и файловые
операции над НЕ-persisted путями песочницы, обращаясь к SandboxAPI Server.
"""

from .client import SandboxAPIClient

__all__ = ["SandboxAPIClient"]
