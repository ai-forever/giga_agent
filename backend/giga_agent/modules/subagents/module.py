from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from giga_agent.conf import get_settings
from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.db import get_session_factory
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserShort
from giga_agent.modules.subagents.tools import subtask, thread_result
from giga_agent.subagents.execution import configured_subagent_ref


SUBAGENTS_INSTRUCTIONS = """## Суб-агенты

Суб-агент — это отдельный специализированный исполнитель со своими
инструкциями, инструментами и изолированным контекстом. История текущего
диалога ему автоматически не передаётся. Используй суб-агентов для
самостоятельных частей работы, а в основной ответ включай проверенный
результат, а не весь журнал промежуточных действий.

### Правило выбора

Делегируй задачу, если она:

- достаточно самостоятельна и может быть выполнена без постоянных уточнений;
- соответствует специализации доступного суб-агента;
- требует много шагов, поиска, проверки файлов или отдельного review;
- создаёт большой объём промежуточных материалов, из которых в основном
  контексте нужен только вывод.

Не делегируй задачу, если она короткая, тесно связана с текущим рассуждением,
требует ответа пользователя посреди выполнения или быстрее решается напрямую.
Не запускай параллельно одинаковую работу в основном агенте и суб-агенте.

### Как ставить задачу

Каждый вызов `subtask` формулируй как самостоятельный brief. В `task` укажи:

1. цель и конкретный вопрос, который нужно решить;
2. необходимый контекст, исходные данные и точные пути/идентификаторы;
3. ограничения и критерии готовности;
4. требуемый формат ответа: например, выводы, список изменений, риски,
   ссылки на файлы и результаты проверок.

Не проси суб-агента «разобраться» без описания ожидаемого результата. Если
нужна проверка кода, попроси отделить наблюдения от предположений и привести
доказательства: конкретные места в коде, команды или тесты. После завершения
самостоятельно оцени результат и не выдавай непроверенное утверждение за факт.

Новый вызов имеет форму `subtask(task, agent_id)`. В structured result будут
`thread_id`, `agent_id`, `status`, текст результата и `child_run_id` — сохрани
`thread_id`, если работа может потребовать продолжения.

### Наблюдение и продолжение

Для проверки уже существующего пользовательского треда используй
`thread_result(thread_id)`. Он только читает состояние и не ждёт завершения.
Тред может быть обычным пользовательским тредом или subagent-тредом.

Интерпретируй статусы строго:

- `completed` — найден финальный ответ суб-агента;
- `running` — выполнение ещё идёт, результат нельзя считать готовым;
- `empty` — тред существует, но сообщений пока нет;
- `failed` — последнее выполнение завершилось ошибкой;
- `not_found` — тред недоступен или не существует.

`running`, `empty` и `failed` не являются успешным результатом. Если статус
`running` содержит `active_tool`, это только информация о текущем вызове
инструмента, а не его финальный результат.

По умолчанию `thread_result` возвращает human-сообщения и финальные AI-ответы
без `tool_calls`. Для просмотра промежуточных вызовов и их результатов передай
`include=["tool_calls"]`. Для истории используй `limit` и `offset`; выдача
идёт от новых сообщений к старым, поэтому `offset=0` — самая свежая страница,
а продолжение страницы нужно брать из `next_offset`, если `has_more=true`.

Чтобы дать дополнительное указание тому же суб-агенту, используй
`subtask(task, thread_id=thread_id)`. Это не новый запуск: исходные агент,
проект и настройки треда сохраняются. `agent_id` при continuation обычно не
передавай; если передаёшь, он должен совпадать с исходным профилем. Continuation
разрешён только для subagent-тредов, и при активном выполнении вернётся `busy`.
Не пытайся продолжать обычный пользовательский тред через `subtask`.

### Итеративная работа с суб-агентом

Суб-агента можно вызывать итеративно, продолжая один и тот же диалог. Это
полезно, если первый ответ неполный, не прошёл проверку или требует доработки:

1. Создай работу через `subtask(task, agent_id)` и сохрани возвращённый
   `thread_id`.
2. Проверь состояние через `thread_result(thread_id)`. Не считай работу
   завершённой при статусе `running`, `empty` или `failed`.
3. Если результат требует уточнения, проверки или исправлений, сформулируй
   конкретное follow-up указание с учётом предыдущего ответа и вызови
   `subtask(task, thread_id=thread_id)`.
4. Снова проверь тот же `thread_id` через `thread_result` и повторяй цикл до
   получения результата, который соответствует критериям готовности.

В follow-up явно указывай, что именно нужно исправить или проверить, почему
предыдущий результат недостаточен и каким должен быть новый результат. Не
создавай новый thread и не меняй `agent_id`, если требуется продолжение той
же работы. Если continuation вернул `busy`, не повторяй вызов немедленно:
сначала снова используй `thread_result`, дождись окончания текущего запуска и
только затем отправляй следующее указание. Если получен `failed`, сначала
изучи доступную ошибку, а затем либо отправь исправляющее follow-up указание,
либо сообщи о невозможности продолжения.

### Доступные суб-агенты

Передавай в `agent_id` точное значение из списка ниже. Выбирай наиболее
подходящую специализацию и не меняй профиль ради уже созданного треда.

{available_agents}"""


class SubagentsModule(BaseModule):
    id: str = "subagents"
    label: str = "Суб-агенты"
    description: str = "Делегирование изолированных задач специализированным агентам"
    icon: str = "Bot"

    def get_agents(self, **kwargs: Any) -> list[str]:
        _ = kwargs
        return [
            "agents/researcher/AGENT.md",
        ]

    async def _get_tools(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        *,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ):
        _ = kwargs
        if configured_subagent_ref(config):
            return []
        if user is None:
            return [subtask, thread_result]
        definitions = await self._ready_definitions(user, agent, config=config)
        return [subtask, thread_result] if definitions else []

    async def _ready_definitions(
        self,
        user: UserShort | None,
        agent: BaseAgent,
        *,
        config: RunnableConfig | None = None,
    ):
        if user is None:
            return []
        if get_settings().giga_agent_runtime == "cli":
            definitions = await agent.subagent_registry.list_for_cli(
                user,
                config=config,
            )
            return [
                item
                for item in definitions
                if item.enabled and item.readiness == "ready"
            ]
        factory = await get_session_factory()
        async with factory() as session:
            definitions = await agent.subagent_registry.list_for_user(
                session,
                user,
                cli=get_settings().giga_agent_runtime == "cli",
                config=config,
            )
        return [
            item
            for item in definitions
            if item.enabled and item.readiness == "ready"
        ]

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
        ready = await self._ready_definitions(user, agent, config=config)
        if not ready:
            return None
        available_agents = "\n".join(
            f"- `{item.ref}` — **{item.name}**: {item.description}"
            for item in ready
        )
        return SUBAGENTS_INSTRUCTIONS.format(available_agents=available_agents)
