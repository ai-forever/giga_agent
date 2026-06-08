"""ToolRouterMiddleware — динамический подбор тулов под лимит GigaChat.

GigaChat в режиме function-calling ограничивает блок определений функций
(~4096 токенов, ≈6-7 тулов). Этот middleware перед каждым вызовом модели
оставляет только релевантный поднабор тулов.

Принципы безопасности (не ломать остальной giga_agent):
- Прозрачный pass-through, если: роутер выключен флагом / модель не GigaChat /
  тулов нет / набор уже влезает в бюджет.
- Никогда не выкидывает core-тулы (think, multi_tool_use, request_tools).
- Никогда не выкидывает тулы, на которые ссылаются незавершённые tool_calls.
- Любая неожиданность при rebind → pass-through исходного запроса.
"""

from __future__ import annotations

import json
import logging
import os

from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from giga_agent.core.agent.middleware import AgentMiddleware
from giga_agent.modules.tool_router.rules import (
    CORE_TOOL_NAMES,
    DEFAULT_PRIORITY,
    RULES,
    TOOL_KEYWORDS,
    matches,
)

logger = logging.getLogger(__name__)

# Эвристика стоимости блока функций GigaChat, откалибрована по замерам:
# 6 тулов проходят, 7 — нет; "index 0: 4451" при 7 тулах.
_CHARS_PER_TOKEN = 2.6
_PER_TOOL_OVERHEAD = 370
_BUDGET_TOKENS = int(os.environ.get("GIGA_AGENT_TOOL_ROUTER_BUDGET", "3800"))


def _enabled() -> bool:
    return os.environ.get("GIGA_AGENT_TOOL_ROUTER", "on").lower() not in (
        "off", "0", "false", "no"
    )


def _unwrap(model):
    m = model
    for _ in range(6):
        if hasattr(m, "bound"):
            m = m.bound
        else:
            break
    return m


def _is_gigachat(model) -> bool:
    base = _unwrap(model)
    return "gigachat" in (type(base).__module__ or "").lower() or (
        type(base).__name__ == "GigaChat"
    )


def _tool_tokens(tool) -> int:
    try:
        schema = json.dumps(convert_to_openai_tool(tool), ensure_ascii=False)
        size = len(schema)
    except Exception:
        size = len(getattr(tool, "name", "")) + len(getattr(tool, "description", ""))
    return int(size / _CHARS_PER_TOKEN) + _PER_TOOL_OVERHEAD


def _estimate(tools) -> int:
    return sum(_tool_tokens(t) for t in tools)


def _gather_text(messages) -> str:
    parts: list[str] = []
    for m in messages:
        content = getattr(m, "content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(p) for p in content)
        # аргументы вызовов тулов (в т.ч. request_tools intent) — для стикинесса
        for call in getattr(m, "tool_calls", None) or []:
            parts.append(str(call.get("args", "")))
            parts.append(str(call.get("name", "")))
    return "\n".join(parts).lower()


def _pending_tool_names(messages) -> set[str]:
    """Имена тулов из tool_calls в последнем AIMessage — их нельзя выкидывать."""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            return {c.get("name") for c in (m.tool_calls or []) if c.get("name")}
        break
    return set()


def _resolve(token: str, by_name: dict) -> list:
    if token.endswith("_"):
        return [t for n, t in by_name.items() if n.startswith(token)]
    t = by_name.get(token)
    return [t] if t is not None else []


# Сопоставление тулов с человекочитаемыми названиями модулей — чтобы в сообщении
# об ошибке подсказать пользователю, что именно отключить в меню инструментов.
_TOOL_GROUPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("disk_",), "Яндекс.Диск"),
    (("tracker_",), "Яндекс.Трекер"),
    (
        ("python", "shell", "await_shell", "read_file", "write_file",
         "edit_file", "delete_file"),
        "Песочница (REPL)",
    ),
    (("get_urls",), "Веб"),
    (("get_documents",), "Документы (RAG)"),
    (("search_memories",), "Память"),
    (("analyze_image",), "Изображения"),
    (("read_skill_manifest",), "Скиллы"),
)


def _groups_for(tool_names: list[str]) -> list[str]:
    """Группы модулей, к которым относятся переданные тулы (для подсказки)."""
    found: list[str] = []
    for toks, label in _TOOL_GROUPS:
        if label in found:
            continue
        for name in tool_names:
            if any(name == tok or (tok.endswith("_") and name.startswith(tok))
                   for tok in toks):
                found.append(label)
                break
    return found


def _is_token_limit_error(exc: BaseException) -> bool:
    """Ошибка превышения лимита токенов/размера запроса (любой провайдер)."""
    name = type(exc).__name__
    msg = str(exc).lower()
    return (
        name == "RequestEntityTooLargeError"
        or "tokens limit exceeded" in msg
        or "request entity too large" in msg
        or ("413" in msg and "token" in msg)
    )


def _overflow_message(all_tools: list, selected: list) -> AIMessage:
    """Сообщение, когда даже минимальный набор не влезает в бюджет GigaChat."""
    sel_ids = {id(t) for t in selected}
    dropped = [t.name for t in all_tools if id(t) not in sel_ids]
    groups = _groups_for(dropped) or _groups_for([t.name for t in all_tools])
    hint = ", ".join(groups) if groups else "часть модулей"
    return AIMessage(
        content=(
            "⚠️ Слишком много активных инструментов для GigaChat — они не "
            "помещаются в лимит блока функций (~4096 токенов).\n\n"
            f"Отключите лишние модули в меню инструментов (например: {hint}) "
            "и повторите запрос."
        )
    )


def _limit_error_message(tools: list) -> AIMessage:
    """Сообщение при пойманном 413/лимите токенов от модели."""
    groups = _groups_for([t.name for t in (tools or [])])
    hint = f" (например: {', '.join(groups)})" if groups else ""
    return AIMessage(
        content=(
            "⚠️ Запрос превысил лимит токенов GigaChat. Частые причины — "
            "слишком много активных инструментов или разросшийся диалог.\n\n"
            f"Отключите лишние модули в меню инструментов{hint} или начните "
            "новый чат, затем повторите."
        )
    )


# Подсказки: какой модуль/секрет включить, если домен запрошен, но тулов нет.
_MODULE_HINTS: dict[str, str] = {
    "yandex_tracker": (
        "нужен Яндекс.Трекер — добавьте секреты YANDEX_TRACKER_OAUTH_TOKEN и "
        "YANDEX_TRACKER_ORG_ID (Настройки → API-ключи модулей)"
    ),
    "yandex_disk": "нужен Яндекс.Диск — добавьте секрет YANDEX_DISK_ACCESS_TOKEN",
    "code": "включите модуль «Песочница (REPL)» в меню Инструменты",
    "web": "включите модуль «Веб-скрапер» в меню Инструменты",
    "docs": "включите модуль «Документы (RAG)» в меню Инструменты",
    "memory": "включите модуль «Память» в меню Инструменты",
    "images": "включите модуль «Анализ изображений» в меню Инструменты",
    "skills": "включите модуль «Скиллы» в меню Инструменты",
}


def _consecutive_request_tools(messages) -> int:
    """Сколько подряд последних ходов модель вызывала ТОЛЬКО request_tools."""
    count = 0
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            calls = m.tool_calls or []
            if calls and all(c.get("name") == "request_tools" for c in calls):
                count += 1
                continue
            break
        if getattr(m, "type", None) == "human":
            break  # новый ход пользователя обнуляет счётчик
    return count


def _unavailable_domain_hint(request) -> str:
    text = _gather_text(request.messages)
    available = {t.name for t in (request.tools or [])}
    for rule in RULES:
        if not matches(text, rule):
            continue
        has = any(
            (tok.endswith("_") and any(n.startswith(tok) for n in available))
            or tok in available
            for tok in rule.tools
        )
        if not has:
            return _MODULE_HINTS.get(rule.name, f"модуль «{rule.name}» не подключён")
    return ""


def _stuck_message(request) -> AIMessage:
    """Сообщение, когда модель зациклилась, прося недоступный инструмент."""
    hint = _unavailable_domain_hint(request)
    avail = sorted(
        t.name for t in (request.tools or []) if t.name not in CORE_TOOL_NAMES
    )
    parts = ["Не получилось подобрать подходящий инструмент под запрос."]
    if hint:
        parts.append(f"Похоже, {hint}.")
    if avail:
        parts.append("Доступные сейчас инструменты: " + ", ".join(avail) + ".")
    else:
        parts.append("Сейчас не подключено ни одного профильного инструмента.")
    return AIMessage(content="\n".join(parts))


class ToolRouterMiddleware(AgentMiddleware):
    """Сужает набор тулов под бюджет GigaChat по ключевым словам разговора."""

    async def wrap_model_call(self, request, handler):
        # --- Loop-guard: модель застряла на request_tools (нужного тула нет) ---
        try:
            if _consecutive_request_tools(request.messages) >= 2:
                logger.warning(
                    "ToolRouter: request_tools loop detected, short-circuiting"
                )
                return _stuck_message(request)
        except Exception:
            logger.exception("ToolRouter: loop-guard failed")

        req = request
        # --- Проактивно: сузить набор тулов под бюджет GigaChat ---
        try:
            tools = list(request.tools or [])
            if (
                _enabled()
                and tools
                and _is_gigachat(request.model)
                and _estimate(tools) > _BUDGET_TOKENS
            ):
                selected = self._select(request, tools)
                if _estimate(selected) > _BUDGET_TOKENS:
                    # Даже обязательный костяк не влезает → понятное сообщение
                    # в чат вместо неизбежного 413.
                    logger.warning(
                        "ToolRouter: mandatory toolset over budget (~%d tok), "
                        "short-circuiting", _estimate(selected),
                    )
                    return _overflow_message(tools, selected)
                base = _unwrap(request.model)
                new_model = base.bind_tools(
                    selected, tool_choice=request.tool_choice
                )
                req = request.override(model=new_model, tools=selected)
        except Exception:
            logger.exception("ToolRouter: rebind failed, passing through")
            req = request

        # --- Реактивно: поймать лимит токенов и показать его внятно в чате ---
        try:
            return await handler(req)
        except Exception as exc:
            if _is_token_limit_error(exc):
                logger.warning("ToolRouter: token-limit surfaced to chat: %s", exc)
                return _limit_error_message(list(getattr(req, "tools", None) or []))
            raise

    def _select(self, request, tools: list) -> list:
        by_name = {t.name: t for t in tools}
        text = _gather_text(request.messages)
        pending = _pending_tool_names(request.messages)

        # 1) обязательный костяк
        keep: dict[str, object] = {
            n: by_name[n] for n in CORE_TOOL_NAMES if n in by_name
        }
        keep.update({n: by_name[n] for n in pending if n in by_name})

        # 1.5) operation-aware: тул с точечным совпадением ключевых слов идёт
        # первым в очереди (например "удали" → disk_delete), иначе при ~3
        # слотах нужная операция выпадала.
        ordered: list = [
            by_name[name]
            for name, kws in TOOL_KEYWORDS.items()
            if name in by_name and any(kw in text for kw in kws)
        ]

        # 2) тулсеты, совпавшие по ключевым словам (в порядке RULES)
        for rule in RULES:
            if matches(text, rule):
                for tok in rule.tools:
                    ordered.extend(_resolve(tok, by_name))

        # 3) общий приоритет для дозаполнения бюджета
        for tok in DEFAULT_PRIORITY:
            ordered.extend(_resolve(tok, by_name))
        ordered.extend(tools)  # всё остальное в конце

        # 4) жадно добавляем под бюджет (костяк уже внутри)
        for t in ordered:
            if t.name in keep:
                continue
            if _estimate(list(keep.values()) + [t]) <= _BUDGET_TOKENS:
                keep[t.name] = t

        selected = list(keep.values())
        dropped = [t.name for t in tools if t.name not in keep]
        if dropped:
            logger.info(
                "ToolRouter: kept %d/%d tools (~%d tok). kept=%s dropped=%s",
                len(selected), len(tools), _estimate(selected),
                [t.name for t in selected], dropped,
            )
        return selected
