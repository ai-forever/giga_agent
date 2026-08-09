from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.subagents.tools import subtask
from giga_agent.subagents.execution import configured_subagent_ref


class SubagentsModule(BaseModule):
    id: str = "subagents"
    label: str = "Суб-агенты"
    description: str = "Делегирование изолированных задач специализированным агентам"
    icon: str = "Bot"

    def get_agents(self, **kwargs: Any) -> list[str]:
        _ = kwargs
        return [
            "agents/researcher/AGENT.md",
            "agents/frontend-reviewer/AGENT.md",
        ]

    async def _get_tools(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        *,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ):
        _ = user, agent, kwargs
        return [] if configured_subagent_ref(config) else [subtask]

    async def get_instructions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        state=None,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> str | None:
        _ = state, kwargs
        if user is None or configured_subagent_ref(config):
            return None
        factory = await get_session_factory()
        async with factory() as session:
            definitions = await agent.subagent_registry.list_for_user(
                session,
                user,
                cli=(config or {}).get("configurable", {}).get("cli_mode", False),
            )
        ready = [
            item for item in definitions if item.enabled and item.readiness == "ready"
        ]
        if not ready:
            return None
        lines = [
            "## Суб-агенты",
            "Суб-агент — отдельный специализированный исполнитель со своими "
            "инструкциями, инструментами и изолированным контекстом. Вызови его "
            "через `subtask(task, agent_id)`; в основной диалог вернётся только "
            "итоговый ответ, а не вся история его работы.",
            "",
            "### Когда делегировать",
            "- Задача самостоятельна, требует нескольких шагов и может быть "
            "выполнена без постоянного участия основного агента.",
            "- У доступного суб-агента есть подходящая специализация, инструкции "
            "или инструменты.",
            "- Нужно исследовать тему, проверить много файлов или источников, "
            "провести review либо подготовить отдельный законченный результат.",
            "- Рабочие материалы будут объёмными, но в основном контексте нужен "
            "только вывод. Это главный способ экономии контекста: поиск, вызовы "
            "инструментов и промежуточные материалы остаются у суб-агента.",
            "",
            "### Когда не делегировать",
            "- Действие простое, короткое или быстрее выполняется напрямую.",
            "- Задача тесно связана с текущим ходом диалога, требует уточнений у "
            "пользователя или постоянного обмена результатами.",
            "- Нет суб-агента с подходящей специализацией либо нужный результат "
            "уже получен. Не дублируй одну работу в основном агенте и суб-агенте.",
            "",
            "### Как поставить задачу",
            "Суб-агент не получает историю родительского диалога автоматически, "
            "поэтому `task` должен быть самодостаточным. Укажи:",
            "- конкретную цель и ожидаемый результат;",
            "- только необходимый контекст и исходные данные;",
            "- точные пути, ссылки или идентификаторы вместо пересказа лишних "
            "материалов;",
            "- ограничения, критерии готовности и желаемый формат ответа.",
            "После выполнения проверь существенные утверждения и используй итог "
            "суб-агента в своём ответе, не повторяя без необходимости всю его работу.",
            "",
            "### Доступные суб-агенты",
            "Передавай точный `agent_id` из списка:",
        ]
        for item in ready:
            lines.append(f"- `{item.ref}` — **{item.name}**: {item.description}")
        return "\n".join(lines)
