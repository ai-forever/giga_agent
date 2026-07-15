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

from langchain_core.messages import AIMessage, HumanMessage
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
        "off",
        "0",
        "false",
        "no",
    )


def _name(tool) -> str:
    """Имя тула, неважно BaseTool это или dict (MCP-тулы приходят dict'ами).

    MCP-тулзы в graph_factory собираются как dict {"name","description",
    "parameters"} через transform_tool — у них нет атрибута .name, поэтому
    обращение tool.name роняло и сужение под бюджет, и loop-guard.
    """
    if isinstance(tool, dict):
        return tool.get("name") or ""
    return getattr(tool, "name", "") or ""


def _desc(tool) -> str:
    if isinstance(tool, dict):
        return tool.get("description") or ""
    return getattr(tool, "description", "") or ""


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
        size = len(_name(tool)) + len(_desc(tool))
    return int(size / _CHARS_PER_TOKEN) + _PER_TOOL_OVERHEAD


def _estimate(tools) -> int:
    return sum(_tool_tokens(t) for t in tools)


def _extract_user_query(content: str) -> str:
    """Вытащить блок <user_query>…</user_query>, если он есть.

    Промпт-шаблон оборачивает запрос пользователя в <user_query>, но в то же
    сообщение бывают вшиты few-shot примеры и инструкции со словами вроде
    «задач»/«файл», которые ложно матчат доменные правила. Берём только сам
    запрос; если тега нет — возвращаем контент как есть.
    """
    marker = "<user_query>"
    if marker not in content:
        return content
    # Контент после ПЕРВОГО открывающего тега. Важно split (не rsplit): шаблон
    # закрывает блок тем же кривым тегом <user_query> (а не </user_query>), и
    # rsplit по последнему вхождению отдавал бы пустоту после закрытия.
    tail = content.split(marker, 1)[1]
    # Обрезаем по первому закрывающему варианту (нормальному или кривому).
    for close in ("</user_query>", marker):
        tail = tail.split(close, 1)[0]
    return tail.strip()


def _gather_text(messages) -> str:
    parts: list[str] = []
    for m in messages:
        # Контент для матчинга правил берём ТОЛЬКО из сообщений пользователя
        # (и только сам <user_query>). Остальное — шум, ложно матчащий домены:
        #   • SystemMessage — статичные инструкции/few-shot ("задач", "файл"…);
        #   • AIMessage — многословный think агента;
        #   • ToolMessage — большие JSON-результаты тулов (события, файлы…).
        # request_tools-стикинесс держим отдельно — через args/имена tool_calls.
        if isinstance(m, HumanMessage):
            content = getattr(m, "content", "")
            if isinstance(content, str):
                parts.append(_extract_user_query(content))
            elif isinstance(content, list):
                parts.extend(_extract_user_query(str(p)) for p in content)
        # Стикинесс: имя вызванного тула (держим домен активным между ходами) +
        # args ТОЛЬКО у request_tools (это и есть intent «дайте мне тул X»).
        # args прочих тулов (особенно think) — многословный шум, не матчим.
        for call in getattr(m, "tool_calls", None) or []:
            name = call.get("name", "")
            parts.append(str(name))
            if name == "request_tools":
                parts.append(str(call.get("args", "")))
    return "\n".join(parts).lower()


def _pending_tool_names(messages) -> set[str]:
    """Имена тулов из tool_calls в последнем AIMessage — их нельзя выкидывать."""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            return {c.get("name") for c in (m.tool_calls or []) if c.get("name")}
        break
    return set()


def _resolve(token: str, by_name: dict) -> list:
    # Префикс-токен: "tracker_" (Яндекс-модули) или "bitrix-" (дефисные имена
    # MCP-серверов). Точный токен — иначе.
    if token.endswith(("_", "-")):
        return [t for n, t in by_name.items() if n.startswith(token)]
    t = by_name.get(token)
    return [t] if t is not None else []


# Сопоставление тулов с человекочитаемыми названиями модулей — чтобы в сообщении
# об ошибке подсказать пользователю, что именно отключить в меню инструментов.
_TOOL_GROUPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("disk_",), "Яндекс.Диск"),
    (("tracker_",), "Яндекс.Трекер"),
    (
        (
            "python",
            "shell",
            "await_shell",
            "read_file",
            "write_file",
            "edit_file",
            "delete_file",
        ),
        "Песочница (REPL)",
    ),
    (("get_urls",), "Веб"),
    (("get_documents",), "Документы (RAG)"),
    (("search_memories",), "Память"),
    (("analyze_image",), "Изображения"),
    (("read_skill_manifest",), "Скиллы"),
    (("bitrix-",), "Битрикс24 (MCP)"),
)


def _groups_for(tool_names: list[str]) -> list[str]:
    """Группы модулей, к которым относятся переданные тулы (для подсказки)."""
    found: list[str] = []
    for toks, label in _TOOL_GROUPS:
        if label in found:
            continue
        for name in tool_names:
            if any(
                name == tok or (tok.endswith(("_", "-")) and name.startswith(tok))
                for tok in toks
            ):
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


def _notice(content: str) -> AIMessage:
    """Служебное сообщение от инфраструктуры (не ответ модели).

    Помечается kind="system_notice" — фронт рисует его отдельным серым
    info-баблом, чтобы не выглядело как реплика ассистента.
    """
    return AIMessage(content=content, additional_kwargs={"kind": "system_notice"})


def _overflow_message(all_tools: list, selected: list) -> AIMessage:
    """Сообщение, когда даже минимальный набор не влезает в бюджет GigaChat."""
    sel_ids = {id(t) for t in selected}
    dropped = [_name(t) for t in all_tools if id(t) not in sel_ids]
    groups = _groups_for(dropped) or _groups_for([_name(t) for t in all_tools])
    hint = ", ".join(groups) if groups else "часть модулей"
    return _notice(
        "⚠️ Слишком много активных инструментов для GigaChat — они не "
        "помещаются в лимит блока функций (~4096 токенов).\n\n"
        f"Отключите лишние модули в меню инструментов (например: {hint}) "
        "и повторите запрос."
    )


def _limit_error_message(tools: list) -> AIMessage:
    """Сообщение при пойманном 413/лимите токенов от модели."""
    groups = _groups_for([_name(t) for t in (tools or [])])
    hint = f" (например: {', '.join(groups)})" if groups else ""
    return _notice(
        "⚠️ Запрос превысил лимит токенов GigaChat. Частые причины — "
        "слишком много активных инструментов или разросшийся диалог.\n\n"
        f"Отключите лишние модули в меню инструментов{hint} или начните "
        "новый чат, затем повторите."
    )


# Подсказки: какой модуль/секрет включить, если домен запрошен, но тулов нет.
_MODULE_HINTS: dict[str, str] = {
    "yandex_tracker": (
        "нужен Яндекс.Трекер — подключите его в меню коннекторов и укажите "
        "секрет YANDEX_TRACKER_ORG_ID (ID организации)"
    ),
    "yandex_disk": "нужен Яндекс.Диск — подключите его в меню коннекторов",
    "yandex_mail": "нужна Яндекс.Почта — подключите её в меню коннекторов",
    "code": "включите модуль «Песочница (REPL)» в меню Инструменты",
    "web": "включите модуль «Веб-скрапер» в меню Инструменты",
    "docs": "включите модуль «Документы (RAG)» в меню Инструменты",
    "memory": "включите модуль «Память» в меню Инструменты",
    "images": "включите модуль «Анализ изображений» в меню Инструменты",
    "skills": "включите модуль «Скиллы» в меню Инструменты",
    "bitrix": (
        "нужен MCP Битрикс24 — подключите сервер mcp-dev.bitrix24.tech/mcp "
        "в меню Инструменты → MCP"
    ),
}


def _consecutive_request_tools(messages) -> int:
    """Сколько раз модель звала request_tools с последнего хода пользователя.

    Не «строго подряд»: модель часто чередует request_tools с другим (не тем)
    тулом — request_tools, mail_search, request_tools… — и при строгой
    последовательности guard не срабатывал. Считаем все request_tools-ходы до
    ближайшего human-сообщения.
    """
    count = 0
    for m in reversed(messages):
        if getattr(m, "type", None) == "human":
            break  # новый ход пользователя обнуляет счётчик
        if isinstance(m, AIMessage):
            calls = m.tool_calls or []
            if any(c.get("name") == "request_tools" for c in calls):
                count += 1
    return count


def _unavailable_domain_hint(request) -> str:
    text = _gather_text(request.messages)
    available = {_name(t) for t in (request.tools or [])}
    for rule in RULES:
        if not matches(text, rule):
            continue
        has = any(
            (tok.endswith(("_", "-")) and any(n.startswith(tok) for n in available))
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
        n
        for n in (_name(t) for t in (request.tools or []))
        if n and n not in CORE_TOOL_NAMES
    )
    parts = ["Не получилось подобрать подходящий инструмент под запрос."]
    if hint:
        parts.append(f"Похоже, {hint}.")
    if avail:
        parts.append("Доступные сейчас инструменты: " + ", ".join(avail) + ".")
    else:
        parts.append("Сейчас не подключено ни одного профильного инструмента.")
    return _notice("\n".join(parts))


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
                        "short-circuiting",
                        _estimate(selected),
                    )
                    return _overflow_message(tools, selected)
                base = _unwrap(request.model)
                new_model = base.bind_tools(selected, tool_choice=request.tool_choice)
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
        by_name = {_name(t): t for t in tools if _name(t)}
        text = _gather_text(request.messages)
        pending = _pending_tool_names(request.messages)

        # 1) обязательный костяк
        keep: dict[str, object] = {
            n: by_name[n] for n in CORE_TOOL_NAMES if n in by_name
        }
        keep.update({n: by_name[n] for n in pending if n in by_name})

        # 1.4) тул, ЯВНО названный в тексте, — максимальный приоритет. Модель в
        # request_tools-intent часто пишет имя нужного тула ("вызвать mail_send");
        # без этого он выпадал из бюджета и начинался request_tools-цикл.
        named: list = [by_name[n] for n in by_name if len(n) > 4 and n in text]

        # Токены тулсетов из ПРАВИЛ, совпавших с текстом. operation-precision
        # (TOOL_KEYWORDS) имеет смысл только внутри активного домена.
        matched_tokens: tuple[str, ...] = tuple(
            tok for rule in RULES if matches(text, rule) for tok in rule.tools
        )

        def _in_matched_domain(name: str) -> bool:
            for tok in matched_tokens:
                if tok.endswith(("_", "-")):
                    if name.startswith(tok):
                        return True
                elif name == tok:
                    return True
            return False

        # 1.5) operation-aware: тул с точечным совпадением ключевых слов.
        # Делим на «в активном домене» (его правило совпало) и «вне». Первые
        # идут вперёд — точность операции ("удали файл" → disk_delete). Вторые
        # уходят ПОСЛЕ тулсетов совпавших правил: иначе общие слова в
        # рассуждении модели или в request_tools-intent ("прочитать", "найти")
        # тянут чужие тулы и крадут слоты у нужного домена (напр. bitrix).
        kw_hit_in: list = []
        kw_hit_out: list = []
        for name, kws in TOOL_KEYWORDS.items():
            if name in by_name and any(kw in text for kw in kws):
                bucket = kw_hit_in if _in_matched_domain(name) else kw_hit_out
                bucket.append(by_name[name])

        ordered: list = named + [t for t in kw_hit_in if t not in named]

        # 2) тулсеты, совпавшие по ключевым словам (в порядке RULES)
        for rule in RULES:
            if matches(text, rule):
                for tok in rule.tools:
                    ordered.extend(_resolve(tok, by_name))

        # 2.5) точечные хиты вне активного домена — доп. приоритет ПОСЛЕ
        # совпавших доменов (доступны как филлер, но не крадут слоты).
        ordered.extend(t for t in kw_hit_out if t not in ordered)

        # 3) общий приоритет для дозаполнения бюджета
        for tok in DEFAULT_PRIORITY:
            ordered.extend(_resolve(tok, by_name))
        ordered.extend(tools)  # всё остальное в конце

        # 4) жадно добавляем под бюджет (костяк уже внутри)
        for t in ordered:
            tn = _name(t)
            if not tn or tn in keep:
                continue
            if _estimate(list(keep.values()) + [t]) <= _BUDGET_TOKENS:
                keep[tn] = t

        selected = list(keep.values())
        dropped = [_name(t) for t in tools if _name(t) not in keep]
        if dropped:
            logger.info(
                "ToolRouter: kept %d/%d tools (~%d tok). kept=%s dropped=%s",
                len(selected),
                len(tools),
                _estimate(selected),
                [_name(t) for t in selected],
                dropped,
            )
        return selected
