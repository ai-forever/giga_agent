"""LangChain-инструменты для Agent Skills."""

from __future__ import annotations

import uuid

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.modules.skills.service import SkillNotFoundError, SkillsService
from giga_agent.sandbox.manager import SandboxManager
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory

logger = get_logger(__name__)


def _build_activate_skill_result(
    *,
    runtime: ToolRuntime,
    content: str,
) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    tool_call_id=runtime.tool_call_id,
                    content=content,
                    additional_kwargs={"tool_name": "activate_skill"},
                )
            ]
        }
    )


async def _resolve_owner_and_runtime(runtime: ToolRuntime):
    user_id_raw = runtime.config["configurable"]["langgraph_auth_user"]["identity"]
    owner_id = uuid.UUID(user_id_raw) if isinstance(user_id_raw, str) else user_id_raw

    factory = await get_session_factory()
    async with factory() as session:
        resolved = await SandboxManager.get_cached_or_db(
            user_id=owner_id,
            session=session,
        )
    sandbox = SandboxRuntimeFactory.build(resolved.provider, resolved.sandbox)
    return owner_id, sandbox


@tool(parse_docstring=False, extras={"repl_save": False})
async def activate_skill(
    name: str,
    runtime: ToolRuntime,
):
    """
    Активирует навык по имени и возвращает полные инструкции, а также список
    файлов навыка с их sandbox-путями. Используй этот инструмент, когда системный
    промпт упоминает доступный навык, который нужен для выполнения задачи.
    """
    if runtime is None:
        return "Error: ToolRuntime is required"

    try:
        owner_id, sandbox = await _resolve_owner_and_runtime(runtime)
    except Exception as e:
        logger.warning("activate_skill: failed to resolve runtime: %s", e)
        return _build_activate_skill_result(
            runtime=runtime,
            content=f"Error resolving sandbox: {e}",
        )

    factory = await get_session_factory()
    async with factory() as session:
        svc = SkillsService(session)
        try:
            activation = await svc.get_skill_body(owner_id, name, sandbox)
        except SkillNotFoundError as e:
            return _build_activate_skill_result(runtime=runtime, content=str(e))
        except Exception as e:
            logger.error("activate_skill failed: %s", e, exc_info=True)
            return _build_activate_skill_result(
                runtime=runtime,
                content=f"Error activating skill: {e}",
            )

    parts: list[str] = [
        f"# Навык: {activation.name}\n\n"
        f"Путь навыка: `{activation.sandbox_path}`\n\n"
        "Обязательно используй этот путь как базовую директорию перед "
        "использованием файлов навыка.\n",
        activation.body,
    ]

    if activation.files:
        parts.append("\n\n## Файлы навыка (читай через read_file):\n")
        for f in activation.files:
            parts.append(f"- {f.sandbox_path}")

    return _build_activate_skill_result(runtime=runtime, content="\n".join(parts))
