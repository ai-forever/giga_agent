# Импорт провайдеров для регистрации в ImageGeneratorRegistry.
# Каждый модуль при импорте выполняет @ImageGeneratorRegistry.register(...).
import giga_agent.generators.image.openai  # noqa: F401
import giga_agent.generators.image.gigachat  # noqa: F401
import giga_agent.generators.image.fusion_brain  # noqa: F401
import giga_agent.generators.image.grok  # noqa: F401
import giga_agent.generators.image.nano_banana  # noqa: F401
