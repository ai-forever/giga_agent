# Импорт провайдеров для регистрации в SandboxRegistry.
# Каждый модуль при импорте выполняет @SandboxRegistry.register(...).
import giga_agent.sandbox.e2b.runtime  # noqa: F401
import giga_agent.sandbox.local_docker.runtime  # noqa: F401
import giga_agent.sandbox.local_jupyter.runtime  # noqa: F401
