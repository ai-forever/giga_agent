from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import Field

from giga_agent.core.agent.tool_policy import ToolEffect, tool_extras
from giga_agent.core.agent.tool_results import build_widget_tool_message
from giga_agent.core.db import get_session_factory
from giga_agent.models.channel import ChannelBotRepository, ChannelContact
from giga_agent.models.scheduled_task import (
    STATUS_CANCELLED,
    STATUS_PENDING,
    ScheduledTaskRepository,
)
from giga_agent.memory.runtime import get_memory_tags
from giga_agent.modules.scheduler.service import ScheduleParseError, parse_when
from giga_agent.utils.langgraph_sdk import get_user_id_from_config
from giga_agent.utils.thread_metadata import (
    get_thread_id_from_config,
    get_thread_metadata,
)


def _owner_id(runtime: ToolRuntime) -> uuid.UUID:
    if runtime is None:
        raise ValueError("Tool runtime is required.")
    user_id = get_user_id_from_config(runtime.config)
    return uuid.UUID(user_id) if isinstance(user_id, str) else user_id


def _current_memory_tags(runtime: ToolRuntime) -> list[str]:
    """Memory tags of the run scheduling the task, to inherit its memory scope."""
    config = getattr(runtime, "config", None)
    return get_memory_tags(config)


async def _thread_metadata(runtime: ToolRuntime) -> dict:
    config = getattr(runtime, "config", None)
    return await get_thread_metadata(config, get_thread_id_from_config(config))


async def _channel_memory_tags(runtime: ToolRuntime) -> list[str]:
    """Inherited tags plus the initiator's personal tag in group chats.

    In a group the run is scoped to ``tg_chat_<id>``; adding ``tg_user_<id>`` of
    the initiator lets the scheduled task also see their personal memory. In a
    private chat the tag is already ``tg_user_<id>`` and ``telegram_user_id`` is
    absent, so nothing is added.
    """
    tags = list(_current_memory_tags(runtime))
    metadata = await _thread_metadata(runtime)
    # Format mirrors channels.telegram.runtime.build_memory_tags.
    if metadata.get("channel") == "telegram":
        tg_user_id = metadata.get("telegram_user_id")
        if tg_user_id:
            personal = f"tg_user_{tg_user_id}"
            if personal not in tags:
                tags.append(personal)
    return tags


def _thread_id(runtime: ToolRuntime) -> str | None:
    config = getattr(runtime, "config", None) or {}
    metadata = config.get("metadata") or {}
    tid = metadata.get("thread_id")
    if not tid:
        tid = (config.get("configurable") or {}).get("thread_id")
    return str(tid).strip().strip("/") if tid else None


async def _current_channel_target(session, runtime: ToolRuntime) -> dict | None:
    """Resolve the chat the channel conversation happens in as a delivery target.

    Maps the current langgraph thread back to its ChannelThread (bot + chat), so
    a task scheduled from inside a channel is delivered to that same chat.
    """
    tid = _thread_id(runtime)
    if not tid:
        return None
    row = await ChannelBotRepository(session).get_thread_by_langgraph_id(tid)
    if row is None:
        return None
    return {
        "bot_id": str(row.bot_id),
        "external_chat_id": row.external_chat_id,
        # Deliver at chat level (the whole chat/group). In groups the thread is
        # per-participant, so row.external_user_id is the sender — but the target
        # is a delivery destination (the chat), matching how channel contacts are
        # keyed (chat-level, external_user_id=None).
        "external_user_id": None,
    }


def _target_matches(target: dict, current: dict) -> bool:
    """True if a stored task target points at the current channel chat."""
    return (
        str(target.get("bot_id")) == str(current.get("bot_id"))
        and str(target.get("external_chat_id")) == str(current.get("external_chat_id"))
        and (target.get("external_user_id") or None)
        == (current.get("external_user_id") or None)
    )


def _task_belongs_to_chat(task, current: dict) -> bool:
    return any(_target_matches(t, current) for t in (task.targets or []))


async def _caller_personal_tag(runtime: ToolRuntime) -> str | None:
    """The ``tg_user_<id>`` tag identifying who is calling, or None.

    A task created by a user always carries this tag in its ``memory_tags`` (see
    ``_channel_memory_tags``), so it lets us tell a user's own tasks apart from
    those of other participants in the same group chat.
    """
    metadata = await _thread_metadata(runtime)
    if metadata.get("channel") == "telegram":
        tg_user_id = metadata.get("telegram_user_id")
        if tg_user_id:
            return f"tg_user_{tg_user_id}"
    for tag in _current_memory_tags(runtime):
        if tag.startswith("tg_user_"):
            return tag
    return None


async def _task_belongs_to_caller(task, runtime: ToolRuntime) -> bool:
    """True if the current Telegram user created this task.

    When we can't resolve the caller's identity (e.g. a private chat with no
    per-user tag) we fall back to True: the chat scope already isolates the task.
    """
    personal = await _caller_personal_tag(runtime)
    if personal is None:
        return True
    return personal in (task.memory_tags or [])


def _contact_label(c: ChannelContact) -> str:
    if c.chat_title and c.chat_title.strip():
        return c.chat_title.strip()
    name = " ".join(p for p in [c.first_name, c.last_name] if p)
    if name.strip():
        return name.strip()
    if c.username and c.username.strip():
        return f"@{c.username.strip()}"
    return c.external_chat_id


async def _resolve_targets(
    session, owner_id: uuid.UUID, recipient_ids: list[str]
) -> list[dict]:
    """Map recipient_ids (contact UUIDs) to delivery targets, owner-scoped."""
    chan = ChannelBotRepository(session)
    targets: list[dict] = []
    for rid in recipient_ids:
        try:
            cid = uuid.UUID(str(rid))
        except (ValueError, TypeError):
            continue
        contact = await chan.get_contact_by_id(cid)
        if contact is None:
            continue
        bot = await chan.get_by_id(contact.bot_id)
        if bot is None or bot.user_id != owner_id:
            continue
        targets.append(
            {
                "bot_id": str(bot.id),
                "external_chat_id": contact.external_chat_id,
                "external_user_id": contact.external_user_id,
            }
        )
    return targets


@tool(extras=tool_extras(ToolEffect.READ))
async def list_task_recipients(runtime: ToolRuntime):
    """Получить возможных получателей результата фоновой задачи (одобренные контакты каналов).

    Используй перед schedule_task, чтобы предложить пользователю выбрать, кому
    отправить результат. recipient_id передаётся в schedule_task.
    """
    owner_id = _owner_id(runtime)
    factory = await get_session_factory()
    async with factory() as session:
        chan = ChannelBotRepository(session)
        contacts = await chan.list_approved_contacts_for_owner(owner_id)
        bots = {b.id: b for b in await chan.list_by_user(owner_id)}
    recipients = []
    for c in contacts:
        bot = bots.get(c.bot_id)
        is_group = c.chat_type in ("group", "supergroup")
        recipients.append(
            {
                "recipient_id": str(c.id),
                "channel": bot.channel_type if bot else None,
                "bot": (bot.bot_username if bot and bot.bot_username else None),
                "name": _contact_label(c),
                "chat_type": c.chat_type,
                "is_group": is_group,
                "is_default": c.is_default_task_recipient,
            }
        )
    return recipients


@tool(extras=tool_extras(ToolEffect.WRITE))
async def schedule_task(
    runtime: ToolRuntime,
    prompt: str = Field(
        description="Что выполнить в фоне. Пиши как задачу агенту, например 'Сделай сводку погоды на завтра'."
    ),
    when: str = Field(
        description="Когда выполнить: ISO-дата '2026-06-29T09:00' (разово) или cron '0 9 * * 1' (периодически)."
    ),
    name: str = Field(
        default="", description="Короткое название задачи (необязательно)."
    ),
    recipient_ids: list[str] = Field(
        default=[],
        description="recipient_id из list_task_recipients, кому слать результат. Пусто = получателям по умолчанию.",
    ),
):
    """Запланировать отложенную или периодическую фоновую задачу.

    Если recipient_ids не указаны — результат уйдёт получателям по умолчанию.
    """
    owner_id = _owner_id(runtime)
    try:
        schedule = parse_when(when)
    except ScheduleParseError:
        return {
            "error": "Не понял время.",
            "next": "Передай when как ISO-дату '2026-06-29T09:00' или cron '0 9 * * 1'.",
        }

    factory = await get_session_factory()
    async with factory() as session:
        targets = await _resolve_targets(session, owner_id, recipient_ids or [])
        repo = ScheduledTaskRepository(session)
        task = await repo.create(
            owner_id=owner_id,
            name=name.strip() or None,
            prompt=prompt,
            kind=schedule["kind"],
            cron=schedule["cron"],
            timezone=schedule["timezone"],
            run_at=schedule["run_at"],
            targets=targets,
            memory_tags=_current_memory_tags(runtime),
        )
    return build_widget_tool_message(
        {
            "task_id": str(task.id),
            "kind": task.kind,
            "next_run": task.run_at.isoformat() if task.run_at else None,
            "recipients": len(task.targets) if task.targets else "default",
            "status": "scheduled",
        },
        runtime=runtime,
    )


@tool("schedule_task", extras=tool_extras(ToolEffect.WRITE))
async def schedule_task_in_chat(
    runtime: ToolRuntime,
    prompt: str = Field(
        description="Что выполнить в фоне. Пиши как задачу агенту, например 'Сделай сводку погоды на завтра'."
    ),
    when: str = Field(
        description="Когда выполнить: ISO-дата '2026-06-29T09:00' (разово) или cron '0 9 * * 1' (периодически)."
    ),
    name: str = Field(
        default="", description="Короткое название задачи (необязательно)."
    ),
):
    """Запланировать фоновую задачу. Результат придёт в этот же чат."""
    owner_id = _owner_id(runtime)
    try:
        schedule = parse_when(when)
    except ScheduleParseError:
        return {
            "error": "Не понял время.",
            "next": "Передай when как ISO-дату '2026-06-29T09:00' или cron '0 9 * * 1'.",
        }

    factory = await get_session_factory()
    async with factory() as session:
        target = await _current_channel_target(session, runtime)
        targets = [target] if target else []
        repo = ScheduledTaskRepository(session)
        task = await repo.create(
            owner_id=owner_id,
            name=name.strip() or None,
            prompt=prompt,
            kind=schedule["kind"],
            cron=schedule["cron"],
            timezone=schedule["timezone"],
            run_at=schedule["run_at"],
            targets=targets,
            memory_tags=await _channel_memory_tags(runtime),
        )
    return build_widget_tool_message(
        {
            "task_id": str(task.id),
            "kind": task.kind,
            "next_run": task.run_at.isoformat() if task.run_at else None,
            "status": "scheduled",
        },
        runtime=runtime,
    )


def _task_summary(t) -> dict:
    return {
        "task_id": str(t.id),
        "name": t.name,
        "kind": t.kind,
        "status": t.status,
        "enabled": t.is_enabled,
        "next_run": t.run_at.isoformat() if t.run_at else None,
    }


@tool(extras=tool_extras(ToolEffect.READ))
async def list_scheduled_tasks(runtime: ToolRuntime):
    """Показать запланированные фоновые задачи пользователя."""
    owner_id = _owner_id(runtime)
    factory = await get_session_factory()
    async with factory() as session:
        repo = ScheduledTaskRepository(session)
        tasks = await repo.list_by_owner(owner_id)
    return [_task_summary(t) for t in tasks]


@tool("list_scheduled_tasks", extras=tool_extras(ToolEffect.READ))
async def list_scheduled_tasks_in_chat(runtime: ToolRuntime):
    """Показать запланированные задачи, созданные в этом чате."""
    owner_id = _owner_id(runtime)
    factory = await get_session_factory()
    async with factory() as session:
        current = await _current_channel_target(session, runtime)
        if current is None:
            return []
        repo = ScheduledTaskRepository(session)
        tasks = await repo.list_by_owner(owner_id)
        return [_task_summary(t) for t in tasks if _task_belongs_to_chat(t, current)]


@tool(extras=tool_extras(ToolEffect.WRITE))
async def cancel_scheduled_task(
    runtime: ToolRuntime,
    task_id: str = Field(description="ID задачи из list_scheduled_tasks."),
):
    """Отменить запланированную фоновую задачу."""
    owner_id = _owner_id(runtime)
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return {"error": "Неверный task_id.", "next": "Вызови list_scheduled_tasks."}

    factory = await get_session_factory()
    async with factory() as session:
        repo = ScheduledTaskRepository(session)
        task = await repo.get_for_owner(tid, owner_id)
        if task is None:
            return {
                "error": "Задача не найдена.",
                "next": "Вызови list_scheduled_tasks.",
            }
        await repo.update(task, status=STATUS_CANCELLED, is_enabled=False)
    return {"task_id": task_id, "status": "cancelled"}


@tool("cancel_scheduled_task", extras=tool_extras(ToolEffect.WRITE))
async def cancel_scheduled_task_in_chat(
    runtime: ToolRuntime,
    task_id: str = Field(description="ID задачи из list_scheduled_tasks."),
):
    """Отменить задачу, созданную в этом чате."""
    owner_id = _owner_id(runtime)
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return {"error": "Неверный task_id.", "next": "Вызови list_scheduled_tasks."}

    factory = await get_session_factory()
    async with factory() as session:
        current = await _current_channel_target(session, runtime)
        repo = ScheduledTaskRepository(session)
        task = await repo.get_for_owner(tid, owner_id)
        # Only tasks targeting the current chat are cancellable from here; others
        # are reported as not found so foreign tasks stay invisible.
        if task is None or current is None or not _task_belongs_to_chat(task, current):
            return {
                "error": "Задача не найдена.",
                "next": "Вызови list_scheduled_tasks.",
            }
        await repo.update(task, status=STATUS_CANCELLED, is_enabled=False)
    return {"task_id": task_id, "status": "cancelled"}


def _apply_schedule_edit(fields: dict, when: str) -> dict | None:
    """Fill ``fields`` with rescheduling changes; return an error dict or None.

    Rescheduling also reactivates the task (pending + enabled), so editing the
    time of a finished or cancelled task makes it run again.
    """
    try:
        schedule = parse_when(when)
    except ScheduleParseError:
        return {
            "error": "Не понял время.",
            "next": "Передай when как ISO-дату '2026-06-29T09:00' или cron '0 9 * * 1'.",
        }
    fields["kind"] = schedule["kind"]
    fields["cron"] = schedule["cron"]
    fields["timezone"] = schedule["timezone"]
    fields["run_at"] = schedule["run_at"]
    fields["status"] = STATUS_PENDING
    fields["is_enabled"] = True
    return None


@tool(extras=tool_extras(ToolEffect.WRITE))
async def edit_scheduled_task(
    runtime: ToolRuntime,
    task_id: str = Field(description="ID задачи из list_scheduled_tasks."),
    prompt: str = Field(
        default="", description="Новый текст задачи. Пусто = не менять."
    ),
    when: str = Field(
        default="",
        description="Новое время: ISO-дата '2026-06-29T09:00' или cron '0 9 * * 1'. Пусто = не менять.",
    ),
    name: str = Field(default="", description="Новое название. Пусто = не менять."),
    recipient_ids: list[str] = Field(
        default=[],
        description="Новые получатели (recipient_id из list_task_recipients). Пусто = не менять.",
    ),
):
    """Изменить запланированную задачу: текст, время, название или получателей.

    Меняются только переданные поля. Изменение времени снова активирует задачу.
    """
    owner_id = _owner_id(runtime)
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return {"error": "Неверный task_id.", "next": "Вызови list_scheduled_tasks."}

    factory = await get_session_factory()
    async with factory() as session:
        repo = ScheduledTaskRepository(session)
        task = await repo.get_for_owner(tid, owner_id)
        if task is None:
            return {
                "error": "Задача не найдена.",
                "next": "Вызови list_scheduled_tasks.",
            }

        fields: dict = {}
        if prompt.strip():
            fields["prompt"] = prompt.strip()
        if name.strip():
            fields["name"] = name.strip()
        if recipient_ids:
            fields["targets"] = await _resolve_targets(session, owner_id, recipient_ids)
        if when.strip():
            error = _apply_schedule_edit(fields, when)
            if error is not None:
                return error
        if not fields:
            return {
                "error": "Нечего менять.",
                "next": "Передай новый prompt, when, name или recipient_ids.",
            }

        task = await repo.update(task, **fields)
    return build_widget_tool_message(
        {
            "task_id": str(task.id),
            "kind": task.kind,
            "next_run": task.run_at.isoformat() if task.run_at else None,
            "recipients": len(task.targets) if task.targets else "default",
            "status": "updated",
        },
        runtime=runtime,
    )


@tool("edit_scheduled_task", extras=tool_extras(ToolEffect.WRITE))
async def edit_scheduled_task_in_chat(
    runtime: ToolRuntime,
    task_id: str = Field(description="ID задачи из list_scheduled_tasks."),
    prompt: str = Field(
        default="", description="Новый текст задачи. Пусто = не менять."
    ),
    when: str = Field(
        default="",
        description="Новое время: ISO-дата '2026-06-29T09:00' или cron '0 9 * * 1'. Пусто = не менять.",
    ),
    name: str = Field(default="", description="Новое название. Пусто = не менять."),
):
    """Изменить задачу, созданную в этом чате. Редактировать можно только свои задачи."""
    owner_id = _owner_id(runtime)
    try:
        tid = uuid.UUID(task_id)
    except ValueError:
        return {"error": "Неверный task_id.", "next": "Вызови list_scheduled_tasks."}

    factory = await get_session_factory()
    async with factory() as session:
        current = await _current_channel_target(session, runtime)
        repo = ScheduledTaskRepository(session)
        task = await repo.get_for_owner(tid, owner_id)
        # Foreign tasks (other chats) stay invisible; report as not found.
        if task is None or current is None or not _task_belongs_to_chat(task, current):
            return {
                "error": "Задача не найдена.",
                "next": "Вызови list_scheduled_tasks.",
            }
        # In a group chat a user may edit only the tasks they created themselves.
        if not await _task_belongs_to_caller(task, runtime):
            return {
                "error": "Можно редактировать только свои задачи.",
                "next": "Вызови list_scheduled_tasks.",
            }

        fields: dict = {}
        if prompt.strip():
            fields["prompt"] = prompt.strip()
        if name.strip():
            fields["name"] = name.strip()
        if when.strip():
            error = _apply_schedule_edit(fields, when)
            if error is not None:
                return error
        if not fields:
            return {
                "error": "Нечего менять.",
                "next": "Передай новый prompt, when или name.",
            }

        task = await repo.update(task, **fields)
    return build_widget_tool_message(
        {
            "task_id": str(task.id),
            "kind": task.kind,
            "next_run": task.run_at.isoformat() if task.run_at else None,
            "status": "updated",
        },
        runtime=runtime,
    )
