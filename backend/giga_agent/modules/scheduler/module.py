from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter
from langchain_core.tools import BaseTool

from giga_agent.conf import get_settings
from giga_agent.core.agent.base import BaseAgent
from giga_agent.core.agent.connectors.tools import (
    CALL_TOOL_NAME,
    GET_INFO_TOOL_NAME,
)
from giga_agent.core.module import BaseModule
from giga_agent.utils.thread_metadata import (
    get_thread_id_from_config,
    get_thread_metadata,
)
from giga_agent.models.users import UserShort

SCHEDULER_CONNECTOR = "scheduler"

SCHEDULER_INSTRUCTIONS = f"""
# Отложенные задачи

Инструменты планировщика вызываются через коннектор `{SCHEDULER_CONNECTOR}`:
сначала `{GET_INFO_TOOL_NAME}(connector='{SCHEDULER_CONNECTOR}')`, чтобы узнать точные имена
инструментов и поля `params`, затем
`{CALL_TOOL_NAME}(connector='{SCHEDULER_CONNECTOR}', tool='<имя>', params='<JSON-строка>')`.

Инструменты коннектора `{SCHEDULER_CONNECTOR}`:
- `list_task_recipients` — возможные получатели результата (одобренные контакты каналов).
- `schedule_task(prompt, when, name, recipient_ids)` — запланировать выполнение задачи позже или
  периодически. `when` это либо ISO-дата (`2026-06-29T09:00`) для разового запуска, либо
  cron-выражение (`0 9 * * 1`) для периодического. В `prompt` опиши задачу так, как поставил бы её
  агенту. `recipient_ids` — кому слать результат (см. ниже).
- `list_scheduled_tasks` — показать запланированные задачи.
- `edit_scheduled_task(task_id, prompt, when, name, recipient_ids)` — изменить задачу. Меняются
  только переданные поля; изменение `when` снова активирует задачу.
- `cancel_scheduled_task(task_id)` — отменить задачу.

## Кому отправлять результат

Перед тем как планировать задачу, ты можешь предложить пользователю выбрать получателей:
1. вызови `list_task_recipients`, чтобы получить список доступных контактов;
2. предложи пользователю выбрать, кому отправить результат, и передай выбранные `recipient_id`
   в `schedule_task` (поле `recipient_ids`);
3. либо, если пользователь не уточнял, не передавай `recipient_ids` — результат уйдёт всем
   получателям по умолчанию.

Если получателей нет вообще (ни выбранных, ни дефолтных) — задача всё равно выполнится, но
результат не будет доставлен.
""".strip()

# Inside a channel chat the result always goes back to the current chat, so the
# recipient-picking flow is dropped entirely.
SCHEDULER_INSTRUCTIONS_CHANNEL = f"""
# Отложенные задачи

Инструменты планировщика вызываются через коннектор `{SCHEDULER_CONNECTOR}`, например
`{CALL_TOOL_NAME}(connector='{SCHEDULER_CONNECTOR}', tool='schedule_task', params='<JSON-строка>')`.

- `schedule_task(prompt, when, name)` — запланировать задачу. Результат придёт в ЭТОТ чат.
  `when` это ISO-дата (`2026-06-29T09:00`) для разового запуска или cron-выражение (`0 9 * * 1`)
  для периодического. В `prompt` опиши задачу так, как поставил бы её агенту.
- `list_scheduled_tasks` — показать запланированные задачи.
- `edit_scheduled_task(task_id, prompt, when, name)` — изменить свою задачу (текст, время или
  название). Редактировать можно только задачи, созданные этим пользователем.
- `cancel_scheduled_task(task_id)` — отменить задачу.
""".strip()


class SchedulerModule(BaseModule):
    id: str = SCHEDULER_CONNECTOR
    label: str = "Отложенные задачи"
    description: str = "Планирование отложенных и периодических фоновых задач"
    icon: str = "Clock"
    lazy_tools: bool = True

    def get_api_router(self, **kwargs: Any) -> Optional[APIRouter]:
        from giga_agent.modules.scheduler.api import router

        return router

    async def is_enabled(
        self, user: UserShort | None, *, config=None, **kwargs: Any
    ) -> bool:
        # В CLI-режиме планировщик не работает (нет фонового sweeper'а/каналов
        # для доставки результатов), поэтому модуль отключаем целиком.
        _ = user, config, kwargs
        if get_settings().giga_agent_runtime == "cli":
            return False
        return True

    @staticmethod
    async def _is_scheduled_run(config: Any) -> bool:
        """True if this run is itself a scheduled-task run.

        The scheduled thread carries ``is_scheduled``/``type`` in its metadata
        (set by the runner), which langgraph surfaces in ``config.metadata``.
        Inside such a run we expose neither the tools nor the prompt, so a
        background task can't recursively schedule more tasks.
        """
        if not isinstance(config, dict):
            return False
        metadata = await get_thread_metadata(config, get_thread_id_from_config(config))
        return (
            bool(metadata.get("is_scheduled"))
            or metadata.get("type") == "scheduled_task"
        )

    @staticmethod
    async def _is_channel_run(config: Any) -> bool:
        """True if the conversation happens inside a channel chat.

        Such runs schedule only for the current chat — no recipient picking.
        """
        if not isinstance(config, dict):
            return False
        metadata = await get_thread_metadata(config, get_thread_id_from_config(config))
        return bool(metadata.get("is_channel"))

    async def _get_tools(
        self, user: UserShort | None, agent: BaseAgent, *, config=None, **kwargs
    ) -> List[BaseTool]:
        _ = user, agent, kwargs
        if await self._is_scheduled_run(config):
            return []
        from giga_agent.modules.scheduler.tools import (
            cancel_scheduled_task,
            cancel_scheduled_task_in_chat,
            edit_scheduled_task,
            edit_scheduled_task_in_chat,
            list_scheduled_tasks,
            list_scheduled_tasks_in_chat,
            list_task_recipients,
            schedule_task,
            schedule_task_in_chat,
        )

        if await self._is_channel_run(config):
            # Result always goes to the current chat: no recipient picking, and
            # list/edit/cancel are scoped to tasks created in this chat.
            return [
                schedule_task_in_chat,
                list_scheduled_tasks_in_chat,
                edit_scheduled_task_in_chat,
                cancel_scheduled_task_in_chat,
            ]

        return [
            schedule_task,
            list_task_recipients,
            list_scheduled_tasks,
            edit_scheduled_task,
            cancel_scheduled_task,
        ]

    async def get_instructions(
        self, user, agent, state=None, config=None, **kwargs
    ) -> str | None:
        _ = user, agent, state, kwargs
        if get_settings().giga_agent_runtime == "cli":
            return None
        if await self._is_scheduled_run(config):
            return None
        if await self._is_channel_run(config):
            return SCHEDULER_INSTRUCTIONS_CHANNEL
        return SCHEDULER_INSTRUCTIONS
