"""LangChain-инструменты для Agent Skills."""

from __future__ import annotations

import difflib

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command, interrupt

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.modules.skills.parser import SkillParseError, parse_skill_md
from giga_agent.modules.skills.service import (
    SkillInstallError,
    SkillNotFoundError,
    SkillsService,
)
from giga_agent.sandbox.manager.runtime_factory import SandboxRuntimeFactory

logger = get_logger(__name__)

TOOL_NAME = "read_skill_manifest"
BUILD_SKILL_TOOL_NAME = "build_skill"


async def _build_fuzzy_skill_suggestions(
    svc: SkillsService,
    owner_id,
    sandbox,
    requested_name: str,
) -> str:
    try:
        skills = await svc.list_skills(owner_id, sandbox)
    except Exception as e:
        logger.warning("fuzzy suggestions: failed to list skills: %s", e)
        return ""

    if not skills:
        return ""

    names = [s.name for s in skills]
    matches = difflib.get_close_matches(requested_name, names, n=3, cutoff=0.5)
    if not matches:
        lower_req = requested_name.lower()
        matches = [n for n in names if lower_req in n.lower()][:3]
    if not matches:
        return ""

    lines = [
        "\n\nМанифест НЕ загружен. Возможно, ты опечатался в имени. "
        f"Повторно вызови инструмент {TOOL_NAME}, передав одно из "
        "следующих имён в поле name:",
    ]
    for name in matches:
        lines.append(f"- {name}")
    return "\n".join(lines)


def _build_tool_result(
    *,
    runtime: ToolRuntime,
    content: str,
    is_error: bool = False,
) -> Command:
    tool_message_kwargs: dict = {
        "tool_call_id": runtime.tool_call_id,
        "content": content,
        "name": TOOL_NAME,
        "additional_kwargs": {"tool_name": TOOL_NAME},
    }
    if is_error:
        tool_message_kwargs["status"] = "error"
    return Command(update={"messages": [ToolMessage(**tool_message_kwargs)]})


async def _resolve_owner_and_runtime(runtime: ToolRuntime):
    resolver = RuntimeResolver.from_config(runtime.config)
    resolved = await resolver.get_sandbox()
    sandbox = SandboxRuntimeFactory.build(resolved.provider, resolved.sandbox)
    return resolver.user.id, sandbox


@tool(parse_docstring=False, extras={"repl_save": False})
async def read_skill_manifest(
    name: str,
    runtime: ToolRuntime,
):
    """
    Читает манифест навыка (SKILL.md) и возвращает список вспомогательных
    файлов. Это НЕ полная документация — большинство навыков состоят из
    десятков файлов в `references/`, которые нужно читать отдельно через
    `read_file`. Используй манифест, чтобы выбрать релевантные файлы перед
    началом работы.
    """
    if runtime is None:
        return "Error: ToolRuntime is required"

    try:
        owner_id, sandbox = await _resolve_owner_and_runtime(runtime)
    except Exception as e:
        logger.warning("%s: failed to resolve runtime: %s", TOOL_NAME, e)
        return _build_tool_result(
            runtime=runtime,
            content=f"Error resolving sandbox: {e}",
            is_error=True,
        )

    factory = await get_session_factory()
    async with factory() as session:
        svc = SkillsService(session)
        try:
            activation = await svc.get_skill_body(owner_id, name, sandbox)
        except SkillNotFoundError as e:
            suggestions = await _build_fuzzy_skill_suggestions(
                svc, owner_id, sandbox, name
            )
            return _build_tool_result(
                runtime=runtime,
                content=f"{e}{suggestions}",
                is_error=True,
            )
        except Exception as e:
            logger.error("%s failed: %s", TOOL_NAME, e, exc_info=True)
            return _build_tool_result(
                runtime=runtime,
                content=f"Error reading skill manifest: {e}",
                is_error=True,
            )

    parts: list[str] = [
        f"# Манифест навыка: {activation.name}\n\n"
        f"Путь навыка: `{activation.sandbox_path}`\n\n"
        "Обязательно используй этот путь как базовую директорию перед "
        "использованием файлов навыка.\n",
        activation.body,
    ]

    if activation.files:
        parts.append(
            "\n\n## ВАЖНО: это только манифест (SKILL.md)\n\n"
            "Выше — точка входа в навык, а не полная документация. "
            "Полные инструкции по конкретным фичам лежат в файлах ниже. "
            "Перед использованием фичи (например, magic-move, mermaid, "
            "export и т.п.) обязательно прочитай соответствующий файл "
            "через `read_file` по sandbox-пути. Не полагайся только на "
            "манифест — в нём намеренно опущены детали.\n\n"
            "## Файлы навыка (читай через read_file):\n"
        )
        for f in activation.files:
            parts.append(f"- {f.sandbox_path}")

    return _build_tool_result(runtime=runtime, content="\n".join(parts))


def _build_build_skill_result(
    *,
    runtime: ToolRuntime,
    content: str,
    is_error: bool = False,
) -> Command:
    tool_message_kwargs: dict = {
        "tool_call_id": runtime.tool_call_id,
        "content": content,
        "name": BUILD_SKILL_TOOL_NAME,
        "additional_kwargs": {"tool_name": BUILD_SKILL_TOOL_NAME},
    }
    if is_error:
        tool_message_kwargs["status"] = "error"
    return Command(update={"messages": [ToolMessage(**tool_message_kwargs)]})


@tool(parse_docstring=False, extras={"repl_save": False})
async def build_skill(
    skill_md: str,
    runtime: ToolRuntime,
):
    """
    Создаёт новый переиспользуемый навык (Skill) из наработанного в диалоге
    контекста. Передай ПОЛНОЕ содержимое файла SKILL.md с YAML-фронтматтером:

        ---
        name: my-skill
        description: Краткое описание, когда применять навык
        ---

        # Инструкции
        ...подробные пошаговые инструкции...

    Требования к `name`: строчные латинские буквы, цифры и дефисы
    (`^[a-z][a-z0-9-]*[a-z0-9]$`). Тело — это инструкция для будущих запусков,
    поэтому пиши его самодостаточно и по делу.

    ВАЖНО: навык будет сохранён ТОЛЬКО после явного подтверждения пользователем
    (accept/deny). Вызывай инструмент только когда пользователь попросил
    сохранить навык или согласился на предложение его создать.
    """
    if runtime is None:
        return "Error: ToolRuntime is required"

    try:
        parsed = parse_skill_md(skill_md)
    except SkillParseError as e:
        return _build_build_skill_result(
            runtime=runtime,
            content=(
                f"Не удалось разобрать SKILL.md: {e}. Исправь фронтматтер/имя и "
                "вызови build_skill снова."
            ),
            is_error=True,
        )

    decision = interrupt(
        {
            "type": "confirm_build_skill",
            "skill": {
                "name": parsed.name,
                "description": parsed.description,
                "body": parsed.body,
            },
        }
    )

    if not isinstance(decision, dict) or decision.get("type") != "approve":
        comment = ""
        if isinstance(decision, dict):
            comment = decision.get("message") or ""
        suffix = f' Комментарий пользователя: "{comment}"' if comment else ""
        return _build_build_skill_result(
            runtime=runtime,
            content=(
                f"Пользователь отклонил создание навыка '{parsed.name}'. "
                f"Не сохраняй навык и уточни, что нужно изменить.{suffix}"
            ),
        )

    try:
        owner_id, sandbox = await _resolve_owner_and_runtime(runtime)
    except Exception as e:
        logger.warning("%s: failed to resolve runtime: %s", BUILD_SKILL_TOOL_NAME, e)
        return _build_build_skill_result(
            runtime=runtime,
            content=f"Error resolving sandbox: {e}",
            is_error=True,
        )

    factory = await get_session_factory()
    async with factory() as session:
        svc = SkillsService(session)
        try:
            skill = await svc.create_from_content(owner_id, skill_md, sandbox)
        except SkillInstallError as e:
            return _build_build_skill_result(
                runtime=runtime,
                content=f"Не удалось сохранить навык: {e}",
                is_error=True,
            )
        except Exception as e:
            logger.error("%s failed: %s", BUILD_SKILL_TOOL_NAME, e, exc_info=True)
            return _build_build_skill_result(
                runtime=runtime,
                content=f"Ошибка при сохранении навыка: {e}",
                is_error=True,
            )

    return _build_build_skill_result(
        runtime=runtime,
        content=(
            f"Навык '{skill.name}' успешно создан и включён. "
            "Он доступен в списке навыков и может быть вызван через "
            "read_skill_manifest."
        ),
    )
