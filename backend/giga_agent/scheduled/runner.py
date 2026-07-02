"""Headless execution and channel delivery for scheduled tasks."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from langgraph_sdk import get_client

from giga_agent.channels.registry import ChannelRegistry
from giga_agent.channels.render import render_run_result
from giga_agent.channels.telegram.utils import _langgraph_url, _make_token
from giga_agent.conf import GIGA_AGENT_SCHEDULER_RUN_TIMEOUT_SEC
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBotRepository
from giga_agent.models.scheduled_task import (
    KIND_CRON,
    STATUS_DONE,
    STATUS_DONE_NO_DELIVERY,
    STATUS_FAILED,
    STATUS_PARTIALLY_FAILED,
    ScheduledTask,
    ScheduledTaskRepository,
)
from giga_agent.models.users import UserRepository
from giga_agent.scheduled.cron import compute_next_run

logger = get_logger(__name__)


async def _make_owner_token(owner_id: uuid.UUID) -> str:
    factory = await get_session_factory()
    async with factory() as session:
        user = await UserRepository(session).get_by_id(owner_id, use_cache=False)
    if user is None:
        raise RuntimeError(f"Owner {owner_id} not found")
    return _make_token(owner_id, user.email)


async def _run_graph(
    *,
    owner_id: uuid.UUID,
    prompt: str,
    task_id: uuid.UUID,
    token: str,
    run_timeout: int,
    memory_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Run the agent graph headless on a fresh thread under the owner's identity."""
    # Inherit the memory scope of the context the task was scheduled in (e.g. the
    # Telegram chat); fall back to a task-scoped tag when none was captured.
    tags = memory_tags or [f"task_{task_id}"]
    memory_show_global = not bool(memory_tags)
    client = get_client(
        url=_langgraph_url(),
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        # Background runs must not pause for human approval — mark the thread
        # autonomous so server-side tool calls execute without an interrupt.
        thread = await client.threads.create(
            metadata={
                "type": "scheduled_task",
                "task_id": str(task_id),
                "auto_approve": True,
                # Mark as a scheduled thread and pin the graph so it surfaces in
                # the main sidebar list (where threads are filtered by graph_id).
                "is_scheduled": True,
                "graph_id": "giga_agent",
            },
        )
        thread_id = thread["thread_id"]
        run_input = {
            "messages": [
                {
                    "role": "human",
                    "content": prompt,
                    "additional_kwargs": {"user_input": prompt},
                }
            ],
            "mcp_tools": [],
        }
        result = await asyncio.wait_for(
            client.runs.wait(
                thread_id=thread_id,
                assistant_id="giga_agent",
                input=run_input,
                config={
                    "configurable": {
                        "memory_disabled": False,
                        "memory_tags": tags,
                        "memory_show_global": memory_show_global,
                        "auto_approve": True,
                    },
                },
            ),
            timeout=run_timeout,
        )
        return result
    finally:
        await client.aclose()


def _targets_from_defaults(contacts: list) -> list[dict[str, Any]]:
    return [
        {
            "bot_id": str(c.bot_id),
            "external_chat_id": c.external_chat_id,
            "external_user_id": c.external_user_id,
        }
        for c in contacts
    ]


async def _deliver_to_targets(
    chan_repo: ChannelBotRepository,
    *,
    owner_id: uuid.UUID,
    targets: list[dict[str, Any]],
    parts: list[dict[str, Any]],
    token: str,
) -> tuple[int, int]:
    """Deliver parts to each target. Returns (delivered, failed)."""
    delivered = 0
    failed = 0
    for target in targets:
        try:
            bot_id = uuid.UUID(str(target["bot_id"]))
            external_chat_id = str(target["external_chat_id"])
        except (KeyError, ValueError):
            failed += 1
            continue
        try:
            bot = await chan_repo.get_by_id(bot_id)
            if bot is None or bot.user_id != owner_id:
                logger.warning("Target bot %s not found or not owned", bot_id)
                failed += 1
                continue
            runtime = await ChannelRegistry.get_runtime(
                bot.channel_type, bot.settings or {}
            )
            ok = await runtime.deliver(
                bot,
                external_chat_id,
                parts,
                token=token,
                external_user_id=target.get("external_user_id"),
            )
            if ok:
                delivered += 1
            else:
                failed += 1
        except Exception:
            logger.exception(
                "Delivery failed for bot %s chat %s", bot_id, external_chat_id
            )
            failed += 1
    return delivered, failed


async def _finalize(
    repo: ScheduledTaskRepository,
    task: ScheduledTask,
    status: str,
    *,
    last_error: str | None = None,
) -> None:
    """Apply terminal status, or reschedule the next run for cron tasks."""
    if task.kind == KIND_CRON and task.cron:
        try:
            next_run = compute_next_run(
                task.cron,
                tz_name=task.timezone,
                after=datetime.now(timezone.utc),
            )
            await repo.reschedule_cron(task, next_run, last_error=last_error)
            return
        except Exception:
            logger.exception("Failed to compute next cron run for task %s", task.id)
    await repo.mark_status(task, status, last_error=last_error, clear_result=True)


async def execute_due_task(
    task_id: uuid.UUID,
    *,
    run_timeout: int = GIGA_AGENT_SCHEDULER_RUN_TIMEOUT_SEC,
) -> None:
    """Run one claimed (status=running) task and deliver its result.

    Opens its own DB session so multiple tasks can run concurrently. If the task
    already has a persisted ``last_result`` (e.g. a restart happened mid-delivery),
    the graph is not re-run — delivery resumes from the saved result.
    """
    factory = await get_session_factory()
    async with factory() as session:
        repo = ScheduledTaskRepository(session)
        task = await repo.get_by_id(task_id)
        if task is None:
            return

        owner_id = task.owner_id

        # Identity for both the graph run and attachment downloads during delivery.
        try:
            token = await _make_owner_token(owner_id)
        except Exception as exc:
            await _finalize(repo, task, STATUS_FAILED, last_error=str(exc)[:2000])
            return

        # Run the graph unless we already have a result to deliver (idempotency).
        parts = task.last_result
        if parts is None:
            try:
                result = await _run_graph(
                    owner_id=owner_id,
                    prompt=task.prompt,
                    task_id=task.id,
                    token=token,
                    run_timeout=run_timeout,
                    memory_tags=task.memory_tags,
                )
                parts = render_run_result(result)
                await repo.save_result(task, parts)
            except Exception as exc:
                logger.exception("Scheduled task %s run failed", task.id)
                await _finalize(repo, task, STATUS_FAILED, last_error=str(exc)[:2000])
                return

        # Resolve delivery targets: explicit targets, else default recipients.
        chan_repo = ChannelBotRepository(session)
        targets = list(task.targets or [])
        if not targets:
            defaults = await chan_repo.list_default_recipients_for_owner(owner_id)
            targets = _targets_from_defaults(defaults)

        if not targets:
            await _finalize(
                repo, task, STATUS_DONE_NO_DELIVERY, last_error="no recipients"
            )
            return

        delivered, failed = await _deliver_to_targets(
            chan_repo,
            owner_id=owner_id,
            targets=targets,
            parts=parts,
            token=token,
        )
        if failed == 0:
            await _finalize(repo, task, STATUS_DONE)
        else:
            await _finalize(
                repo,
                task,
                STATUS_PARTIALLY_FAILED,
                last_error=f"{failed}/{delivered + failed} targets failed",
            )


async def run_task_now(
    task_id: uuid.UUID,
    *,
    run_timeout: int = GIGA_AGENT_SCHEDULER_RUN_TIMEOUT_SEC,
) -> None:
    """Manually run a task once for testing, without touching its schedule.

    Runs the graph and delivers the result regardless of enabled/status, but does
    NOT change ``status``/``run_at``/``last_result`` — only records ``last_run_at``
    and a ``last_error`` describing the manual run's outcome. The next scheduled
    run is unaffected.
    """
    factory = await get_session_factory()
    async with factory() as session:
        repo = ScheduledTaskRepository(session)
        task = await repo.get_by_id(task_id)
        if task is None:
            return

        owner_id = task.owner_id
        now = datetime.now(timezone.utc)

        try:
            token = await _make_owner_token(owner_id)
            result = await _run_graph(
                owner_id=owner_id,
                prompt=task.prompt,
                task_id=task.id,
                token=token,
                run_timeout=run_timeout,
                memory_tags=task.memory_tags,
            )
            parts = render_run_result(result)
        except Exception as exc:
            logger.exception("Manual run of scheduled task %s failed", task.id)
            await repo.update(
                task,
                last_run_at=now,
                last_error=f"manual run failed: {exc}"[:2000],
            )
            return

        chan_repo = ChannelBotRepository(session)
        targets = list(task.targets or [])
        if not targets:
            defaults = await chan_repo.list_default_recipients_for_owner(owner_id)
            targets = _targets_from_defaults(defaults)

        if not targets:
            await repo.update(
                task, last_run_at=now, last_error="manual run: no recipients"
            )
            return

        delivered, failed = await _deliver_to_targets(
            chan_repo,
            owner_id=owner_id,
            targets=targets,
            parts=parts,
            token=token,
        )
        last_error = (
            None
            if failed == 0
            else f"manual run: {failed}/{delivered + failed} targets failed"
        )
        await repo.update(task, last_run_at=now, last_error=last_error)
