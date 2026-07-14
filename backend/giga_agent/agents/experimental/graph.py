"""Экспериментальный режим — граф-обёртка над `giga_agent`.

`giga_agent_experimental` служит презентационной прослойкой между реальным
агентом и пользователем:

- запускает `giga_agent` фоновым ран'ом в отдельном (скрытом) треде и следит за
  его состоянием через LangGraph SDK (`client.threads.get_state`);
- быстрой моделью пишет статус того, что делает агент, ~раз в 10 секунд и
  отправляет его во фронт через `push_ui_message("experimental_status", ...)`
  (эфемерно, без чекпойнта);
- каждое AI-сообщение агента с непустым content (после вырезания
  `<thinking>...`) переписывает моделью-редактором (исправить опечатки/орфографию,
  сделать текст «более русским») и отдаёт как отдельное сообщение внешнего графа;
- пробрасывает во внешний граф тул-результаты с виджетами / MCP-app, чтобы они
  отрендерились.

Внешний граф — стейт-машина `kickoff → pump →(loop)→ END`: каждый pump коммитит
ОДИН всплывший элемент отдельным super-step'ом, поэтому число чекпойнтов ≈ числу
всплывших сообщений (несколько на ход), а не по одному на poll-тик.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Annotated, Any, Required, TypedDict

from cashews import cache
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_gigachat import GigaChat
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.ui import push_ui_message
from langgraph.types import interrupt

from giga_agent.conf import (
    GIGA_AGENT_EXPERIMENTAL_REWRITE_MODEL,
    GIGA_AGENT_EXPERIMENTAL_STATUS_MODEL,
)
from giga_agent.modules.projects.utils import resolve_project_id
from giga_agent.utils.langgraph_sdk import client_session
from giga_agent.utils.messages import strip_thinking
from giga_agent.utils.thread_metadata import update_thread_metadata

INNER_ASSISTANT_ID = "giga_agent"
STATUS_UI_NAME = "experimental_status"
STATUS_UI_ID = "experimental-status"

POLL_INTERVAL_SEC = 2.5
STATUS_INTERVAL_SEC = 10.0
# Сколько прошлых статусов подаём в промпт, чтобы модель показывала продвижение
# и не повторялась дословно.
MAX_RECENT_STATUSES = 5

# Прошлые статусы храним в cashews (Redis в проде, mem:// локально), НЕ в state —
# чтобы не забивать чекпойнты эфемерной презентационной инфой. Распределённый
# бэкенд переживает переезд следующего super-step'а на другой воркер. TTL —
# страховка от утечки, если ран не дошёл до `done` (рестарт воркера и т.п.).
_STATUS_NS = "experimental:status"
_STATUS_TTL = "1h"


def _status_key(run_id: str) -> str:
    return f"{_STATUS_NS}:{run_id}"


async def _get_recent_statuses(run_id: str) -> list[str]:
    return await cache.get(_status_key(run_id)) or []


async def _remember_status(run_id: str, text: str) -> None:
    key = _status_key(run_id)
    statuses = (await cache.get(key) or [])[-MAX_RECENT_STATUSES + 1 :]
    statuses.append(text)
    await cache.set(key, statuses, expire=_STATUS_TTL)


async def _forget_statuses(run_id: str) -> None:
    with contextlib.suppress(Exception):
        await cache.delete(_status_key(run_id))


# --- activity log -----------------------------------------------------------
# «Активность» хода — упорядоченный по времени список вызванных инструментов и
# показанных строк-статусов. Копим в cashews (как статусы), но ключуем по
# ВНЕШНЕМУ thread_id — так HTTP-ручка `/experimental/activity/{thread_id}` может
# отдать живой список активного рана. В отличие от статусов (per-run), активность
# охватывает весь ход (в т.ч. оба inner-рана вокруг ask_questions), поэтому
# сбрасывается в kickoff и дальше только дополняется. Финальный снапшот
# ВСТРАИВАЕТСЯ в маркер-ToolMessage (переживает перезагрузку и TTL кэша).
_ACTIVITY_NS = "experimental:activity"
_ACTIVITY_TTL = "6h"
# Инструменты, не показываемые в активности (внутренняя кухня).
_ACTIVITY_SKIP_TOOLS = {"think", "ask_questions"}


def _now() -> float:
    return time.time()


def _activity_key(thread_id: str) -> str:
    return f"{_ACTIVITY_NS}:{thread_id}"


def _empty_activity(started_at: float | None = None) -> dict:
    return {"started_at": started_at, "finished_at": None, "items": []}


async def _get_activity(thread_id: str) -> dict:
    return await cache.get(_activity_key(thread_id)) or _empty_activity()


async def _set_activity(thread_id: str, activity: dict) -> None:
    await cache.set(_activity_key(thread_id), activity, expire=_ACTIVITY_TTL)


async def _reset_activity(thread_id: str, started_at: float) -> None:
    await _set_activity(thread_id, _empty_activity(started_at))


async def _record_status(thread_id: str, text: str, ts: float) -> None:
    """Добавить строку-статус в активность (после дедупа по последнему тексту)."""
    if not text.strip():
        return
    activity = await _get_activity(thread_id)
    items = activity.setdefault("items", [])
    for prev in reversed(items):
        if prev.get("type") == "status":
            if prev.get("text") == text:
                return  # тот же статус подряд — не дублируем
            break
    items.append({"type": "status", "text": text, "ts": ts})
    await _set_activity(thread_id, activity)


async def _record_tools_from_snapshot(
    thread_id: str, inner_messages: list[dict]
) -> None:
    """Апсертить вызовы инструментов ТЕКУЩЕГО хода из закоммиченного снапшота.

    Учитываем только сообщения ПОСЛЕ границы хода (`_set_activity_baseline` в
    kickoff), а не «после последнего human»: иначе из-за гонки снапшота (в начале
    нового рана нового human ещё нет) затекли бы тулы прошлого хода.
    Тул-итем заводится по `tool_call_id` при первом появлении (ts = сейчас),
    а `status`/`ts_end` проставляются, когда во снапшоте появился парный
    ToolMessage. `think`/`ask_questions` пропускаем.
    """
    baseline = await _get_activity_baseline(thread_id)
    current = inner_messages[baseline:]

    activity = await _get_activity(thread_id)
    items = activity.setdefault("items", [])
    by_id = {it["id"]: it for it in items if it.get("type") == "tool"}
    changed = False
    now = _now()
    for msg in current:
        mtype = msg.get("type")
        if mtype == "ai":
            for tc in msg.get("tool_calls") or []:
                tcid = tc.get("id")
                name = tc.get("name") or ""
                if not tcid or name in _ACTIVITY_SKIP_TOOLS or tcid in by_id:
                    continue
                item = {
                    "type": "tool",
                    "id": tcid,
                    "name": name,
                    "status": "running",
                    "ts": now,
                    "ts_end": None,
                }
                items.append(item)
                by_id[tcid] = item
                changed = True
        elif mtype == "tool":
            tcid = msg.get("tool_call_id")
            item = by_id.get(tcid)
            if item is not None and item.get("ts_end") is None:
                item["status"] = msg.get("status") or "success"
                item["ts_end"] = now
                changed = True
    if changed:
        await _set_activity(thread_id, activity)


async def _finalize_activity(thread_id: str) -> dict:
    """Проставить finished_at (если ещё нет) и вернуть активность."""
    activity = await _get_activity(thread_id)
    if activity.get("finished_at") is None:
        activity["finished_at"] = _now()
        await _set_activity(thread_id, activity)
    return activity


def _activity_baseline_key(thread_id: str) -> str:
    return f"{_ACTIVITY_NS}:baseline:{thread_id}"


async def _set_activity_baseline(thread_id: str, count: int) -> None:
    """Граница текущего хода — число inner-сообщений ДО этого хода.

    Нужна вместо скоупа «после последнего human»: в начале нового рана
    `get_state` может ещё не содержать нового human (гонка снапшота), и тулы
    прошлого хода затекли бы в активность нового. Считаем ровно то, что после
    границы (inner-тред append-only, без веток → индекс стабилен).
    """
    await cache.set(_activity_baseline_key(thread_id), count, expire=_ACTIVITY_TTL)


async def _get_activity_baseline(thread_id: str) -> int:
    return await cache.get(_activity_baseline_key(thread_id)) or 0


async def _forget_activity(thread_id: str) -> None:
    with contextlib.suppress(Exception):
        await cache.delete(_activity_key(thread_id))
    with contextlib.suppress(Exception):
        await cache.delete(_activity_baseline_key(thread_id))


_ACTIVE_RUN_STATUSES = {"pending", "running"}

REWRITE_SYSTEM = (
    "Ты — корректор. Тебе дают текст ответа ассистента — верни ЕГО ЖЕ, "
    "исправив ТОЛЬКО явные ошибки: опечатки, орфографию, пунктуацию, "
    "согласование слов. Правь МИНИМАЛЬНО: не перефразируй нормальные "
    "предложения, не меняй стиль, порядок и структуру. Если ошибок нет — "
    "верни текст без изменений. "
    "Убери случайно вставленные посреди текста иероглифы и другие "
    "нелатинские/некириллические символы-артефакты, не несущие смысла "
    "(частый сбой генерации). Но НЕ трогай осмысленный текст на других "
    "языках, если он к месту. "
    "НИКОГДА не меняй: смысл, факты, числа, даты, имена, названия, термины, "
    "цитаты, язык текста. "
    "ТОЧНО сохрани форматирование: Markdown (заголовки, списки, таблицы, "
    "жирный/курсив), код и код-блоки, формулы ($...$ и $$...$$), ссылки, "
    "эмодзи, а также вставки вида ![...](attachment:...) — их не трогай. "
    "Верни ТОЛЬКО исправленный текст: без вступлений, комментариев, "
    "пояснений и без обрамления кавычками или ```. Не отвечай на текст и "
    "не продолжай его."
)

STATUS_SYSTEM = (
    "Ты пишешь ОДНУ строку-статус о том, ЧЕМ СЕЙЧАС ЗАНЯТ ассистент — она "
    "показывается пользователю вместо «Думаю…». На русском, в настоящем времени, "
    "одной строкой (до ~30 слов, без точки в конце). "
    "Будь КОНКРЕТНЫМ: если из действий видно, ЧТО именно он делает — по какому "
    "запросу ищет, какой файл читает/пишет, какую тему или данные анализирует, "
    "какой инструмент и с чем вызывает — укажи это. Опирайся на аргументы вызовов "
    "инструментов и размышления. НЕ выдумывай деталей, которых нет в действиях, и "
    "НЕ пиши технические имена инструментов/полей — формулируй по-человечески. "
    "Тебе дают запрос пользователя и действия ассистента ИМЕННО по этому запросу. "
    "Если конкретных действий ещё нет — можешь красиво обыграть сам запрос "
    "(например «Разбираюсь с вашим вопросом про налоги»). Как появятся действия — "
    "опирайся на них. "
    "Тебе также дают ПРЕДЫДУЩИЕ статусы, которые ты уже показывал по этому "
    "запросу. НЕ повторяй их дословно: покажи ПРОДВИЖЕНИЕ — что изменилось или "
    "что делаешь дальше. Если ассистент явно перешёл к новому действию — отрази "
    "это; если продолжает то же самое — уточни/детализируй, а не копируй прошлую "
    "формулировку. "
    "Примеры: «Ищу в сети статьи про курс рубля», "
    "«Пишу Python-скрипт для парсинга CSV», "
    "«Анализирую таблицу продаж за квартал», "
    "«Готовлю презентацию по нейросетям». "
    "Если по действиям непонятно — напиши «Думаю»."
)

_rewrite_llm: GigaChat | None = None
_status_llm: GigaChat | None = None


def _get_rewrite_llm() -> GigaChat:
    global _rewrite_llm
    if _rewrite_llm is None:
        _rewrite_llm = GigaChat(
            model=GIGA_AGENT_EXPERIMENTAL_REWRITE_MODEL,
            verify_ssl_certs=False,
            profanity_check=True,
            streaming=True,
            timeout=60
        )
    return _rewrite_llm


def _get_status_llm() -> GigaChat:
    global _status_llm
    if _status_llm is None:
        _status_llm = GigaChat(
            model=GIGA_AGENT_EXPERIMENTAL_STATUS_MODEL,
            verify_ssl_certs=False,
            profanity_check=False,
        )
    return _status_llm.with_config(tags=["nostream"])


class ExperimentalState(TypedDict, total=False):
    messages: Required[Annotated[list[AnyMessage], add_messages]]
    inner_thread_id: str
    inner_run_id: str
    processed_inner_ids: list[str]
    # Значение interrupt'а inner-рана (payload из `interrupt(...)`, напр.
    # ask_questions), ждущее проброса во внешний граф. None — interrupt'а нет.
    # ask_questions кладёт в payload свой tool_call_id — по нему фронт оптимистично
    # рисует карточку ответов, а форвард склеивается с оптимистикой (см. ниже).
    interrupt_value: Any
    done: bool
    # Название внешнего треда скопировано из metadata inner-треда (giga_agent
    # генерит его через ThreadTitleMiddleware; у обёртки такого middleware нет).
    title_synced: bool
    # Приходят во входе submit'а и пробрасываются в inner-ран giga_agent
    # (иначе фронт-обёртка их проглотит — они не в схеме состояния).
    collections: list
    mcp_tools: list
    # Детерминированный id маркера активности текущего хода (задаётся в kickoff).
    # По нему pump обновляет тот же ToolMessage на завершении (add_messages
    # обновляет сообщение на месте). Не выводим из inner_run_id — он меняется
    # после interrupt-resume, а маркер один на весь ход.
    activity_id: str


# Ключи configurable, которые фронт кладёт на submit и которые нужно пробросить
# в inner-ран (режим исследования, выбранные скилы). Остальное (thread_id и пр.)
# НЕ пробрасываем — оно относится к внешнему рану.
_FORWARDED_CONFIGURABLE_KEYS = ("deep_research_forced", "selected_skills")


# --- helpers over SDK-serialized message dicts ------------------------------


def _content_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return ""


def _content_str(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _is_widget_tool(message: dict) -> bool:
    ak = message.get("additional_kwargs") or {}
    if ak.get("response_widget") is True:
        return True
    atts = ak.get("tool_attachments") or []
    return any(
        isinstance(a, dict) and a.get("file_type") == "mcp_ui" and a.get("resource_uri")
        for a in atts
    )


def _eligible_output(message: dict) -> bool:
    """True, если inner-сообщение нужно всплыть во внешний граф.

    ask_questions НЕ всплываем здесь: его ToolMessage строит interrupt_node сразу
    после resume (иначе карточка ответов моргает, пока inner-ран заново прогоняет
    тул). Поэтому его inner-ToolMessage помечается processed и не форвардится.
    """
    mtype = message.get("type")
    if mtype == "ai":
        return bool(strip_thinking(_content_text(message)))
    if mtype == "tool":
        return _is_widget_tool(message)
    return False


async def _rewrite_ai(text: str) -> AIMessage:
    """Переписать текст редактором.

    Через `ainvoke`, а НЕ ручной `astream`: LangGraph сам подхватывает токен-стрим
    LLM-вызова внутри ноды (через колбэки) и пробрасывает его в messages-стрим
    внешнего графа. Ручной astream «съедал» токены локально — во фронт они не шли.
    """
    llm = _get_rewrite_llm()
    try:
        resp = await llm.with_retry(stop_after_attempt=2).ainvoke(
            [SystemMessage(content=REWRITE_SYSTEM), HumanMessage(content=text)]
        )
    except Exception:
        # Редактор упал (напр. profanity_check / сетевой сбой) — не роняем ход,
        # отдаём оригинальный ответ агента как есть.
        return AIMessage(content=text, additional_kwargs={"rendered": True})
    content = resp.content if isinstance(resp.content, str) and resp.content else text
    return AIMessage(
        content=content,
        id=getattr(resp, "id", None),
        additional_kwargs={"rendered": True},
    )


def _stub_message_id(tcid: str) -> str:
    """Детерминированный id AI-заглушки-носителя (по tool_call_id).

    Тот же id фронт ставит оптимистичной заглушке (LiveQuestionsForm), поэтому
    при резюме серверный форвард СКЛЕИВАЕТСЯ с оптимистикой по id (add_messages
    обновляет сообщение на месте), а не создаёт вторую заглушку и второй карточки.
    """
    return f"exp-toolstub-{tcid}"


def _ask_questions_messages(interrupt_value: Any, answer: Any) -> list[AnyMessage]:
    """Собрать AI-заглушку + ToolMessage-ответ ask_questions для внешнего графа.

    Строим сразу после resume (в interrupt_node), а НЕ форвардим inner-ToolMessage
    позже через pump — иначе карточка ответов моргает те секунды, пока inner-ран
    заново прогоняет тул. Контент собираем той же build_questions_result, что и
    сам тул, поэтому он совпадает с inner-результатом. id заглушки детерминирован
    (совпадает с фронт-оптимистикой) → без дублей и морганий.
    """
    if not (isinstance(interrupt_value, dict) and interrupt_value.get("type") == "questions"):
        return []
    tcid = interrupt_value.get("tool_call_id") or ""
    if not tcid:
        return []
    from giga_agent.modules.clarify.tools import build_questions_result

    result = build_questions_result(interrupt_value.get("questions") or [], answer)
    stub = AIMessage(
        id=_stub_message_id(tcid),
        content="",
        tool_calls=[
            {"id": tcid, "name": "ask_questions", "args": {}, "type": "tool_call"}
        ],
        additional_kwargs={"rendered": True},
    )
    tool_msg = ToolMessage(
        id=f"exp-toolmsg-{tcid}",
        content=json.dumps(result, ensure_ascii=False),
        tool_call_id=tcid,
        name="ask_questions",
        status="success",
        additional_kwargs={"tool_name": "ask_questions"},
    )
    return [stub, tool_msg]


def _forward_widget(message: dict) -> list[AnyMessage]:
    """Синтезировать AI-заглушку с tool_call + пробросить ToolMessage.

    Пробрасывает и виджеты, и результат ask_questions. Имя тула берём из
    `additional_kwargs.tool_name` (у ask_questions поле `name` на ToolMessage не
    выставлено) — иначе tool_call стаба назвался бы «widget» и попал в видимый
    список тулов вместо отдельной карточки. Заглушке даём детерминированный id
    (см. _stub_message_id), чтобы фронт-оптимистика склеилась с этим форвардом.
    """
    ak = message.get("additional_kwargs") or {}
    tcid = message.get("tool_call_id") or ""
    name = message.get("name") or ak.get("tool_name") or "widget"
    stub = AIMessage(
        id=_stub_message_id(tcid),
        content="",
        tool_calls=[{"id": tcid, "name": name, "args": {}, "type": "tool_call"}],
        additional_kwargs={"rendered": True},
    )
    tool_msg = ToolMessage(
        content=_content_str(message),
        tool_call_id=tcid,
        name=name,
        status=message.get("status") or "success",
        additional_kwargs=dict(ak),
    )
    return [stub, tool_msg]


ACTIVITY_TOOL_NAME = "experimental_activity"


def _activity_marker_messages(activity_id: str, activity: dict) -> list[AnyMessage]:
    """Собрать пару [AI-заглушка, ToolMessage-маркер] артефакта активности.

    По образцу `_forward_widget`: заглушка несёт tool_call, а ToolMessage —
    результат. `response_widget=True` + маркер `widget` в payload → фронт
    отрендерит его standalone-виджетом (пилюля «Работал N») через готовый пайплайн
    collectResponseWidgets/ResponseWidget. Снапшот активности ВСТРАИВАЕТСЯ в
    content, поэтому панель работает и после перезагрузки/истечения кэша.

    id заглушки и ToolMessage детерминированы (из activity_id) — на завершении
    pump эмитит маркер повторно, и add_messages обновляет обе на месте.
    """
    tcid = f"exp-act-{activity_id}"
    stub = AIMessage(
        id=f"exp-act-stub-{activity_id}",
        content="",
        tool_calls=[
            {"id": tcid, "name": ACTIVITY_TOOL_NAME, "args": {}, "type": "tool_call"}
        ],
        additional_kwargs={"rendered": True},
    )
    tool_msg = ToolMessage(
        id=f"exp-act-msg-{activity_id}",
        # Маркер `widget` кладём ПЛОСКО (без обёртки `data`): фронтовый
        # payloadWidgetKind берёт `raw.data ?? raw` и ищет `.widget` — с вложенным
        # `data` (сама активность без поля widget) виджет не резолвился.
        content=json.dumps(
            {"widget": ACTIVITY_TOOL_NAME, **activity}, ensure_ascii=False
        ),
        tool_call_id=tcid,
        name=ACTIVITY_TOOL_NAME,
        status="success",
        additional_kwargs={
            "response_widget": True,
            "tool_name": ACTIVITY_TOOL_NAME,
            "rendered": True,
        },
    )
    return [stub, tool_msg]


def _summarize_tool_call(tc: dict) -> str:
    name = tc.get("name") or "инструмент"
    args = tc.get("args")
    if isinstance(args, dict) and args:
        arg_str = json.dumps(args, ensure_ascii=False)
        if len(arg_str) > 400:
            arg_str = arg_str[:400] + "…"
        return f"вызывает инструмент {name} с аргументами {arg_str}"
    return f"вызывает инструмент {name}"


def _live_tool_activity(m: dict) -> str:
    """Собрать стримящиеся тул-колы из partial-чанка.

    В accumulated-partial'е аргументы тула приходят по кусочкам: как накопленная
    строка в ``tool_call_chunks[].args`` и/или как (частично) распарсенный dict в
    ``tool_calls``/``invalid_tool_calls``. Берём самое информативное: сначала
    сырые фрагменты чанков (name + накопленный args-string), иначе распарсенные.
    """
    lines: list[str] = []
    chunks = m.get("tool_call_chunks") or []
    if chunks:
        for tcc in chunks:
            if not isinstance(tcc, dict):
                continue
            name = tcc.get("name") or ""
            args = tcc.get("args") or ""  # накопленный фрагмент JSON-строки
            piece = f"{name} {args}".strip()
            if piece:
                lines.append(f"формирует вызов инструмента: {piece}")
        return "\n".join(lines)
    for tc in (m.get("tool_calls") or []) + (m.get("invalid_tool_calls") or []):
        if not isinstance(tc, dict):
            continue
        name = tc.get("name") or ""
        raw_args = tc.get("args")
        if isinstance(raw_args, dict):
            args = json.dumps(raw_args, ensure_ascii=False) if raw_args else ""
        else:
            args = str(raw_args or "")
        piece = f"{name} {args}".strip()
        if piece:
            lines.append(f"формирует вызов инструмента: {piece}")
    return "\n".join(lines)


def _live_text_from_msg(m: dict) -> str:
    """Текст-сигнал из стримового чанка: content, reasoning_content и
    стримящиеся аргументы тул-колов (собираются по кусочкам, пока модель их пишет).
    """
    parts: list[str] = []
    ak = m.get("additional_kwargs") or {}
    rc = ak.get("reasoning_content")
    if isinstance(rc, str) and rc:
        parts.append(rc)
    txt = _content_text(m)
    if txt:
        parts.append(txt)
    tools = _live_tool_activity(m)
    if tools:
        parts.append(tools)
    return "\n".join(parts)


async def _consume_live(config: Any, thread_id: str, run_id: str, live: dict) -> None:
    """Фоновая подписка на messages-стрим inner-рана.

    `join_stream` НЕ буферизован (отдаёт токены «с этого момента»), поэтому даёт
    живой прогресс во время долгого ризонинга/генерации, которого ещё нет в
    закоммиченном стейте (`get_state`). Пишем последний накопленный partial в
    `live["text"]`, откуда его читает `_push_status`. Отмена задачи (при возврате
    из pump) просто закрывает стрим; inner-ран НЕ отменяется
    (`cancel_on_disconnect=False`).
    """
    with contextlib.suppress(Exception):
        async with client_session(config) as client:
            async for part in client.runs.join_stream(
                thread_id,
                run_id,
                stream_mode="messages",
                cancel_on_disconnect=False,
            ):
                event = part.event or ""
                if not event.startswith("messages") or not isinstance(part.data, list):
                    continue
                # messages/partial|complete: data — список message-dict'ов
                # (partial = накопленный контент, поэтому просто заменяем).
                for m in part.data:
                    if not isinstance(m, dict):
                        continue
                    txt = _live_text_from_msg(m)
                    if txt.strip():
                        live["text"] = txt


async def _push_status(
    inner_messages: list[dict],
    live_text: str = "",
    recent_statuses: list[str] | None = None,
) -> str:
    """Сгенерировать и запушить статус (эфемерно, без чекпойнта).

    Возвращает сгенерированный текст (для складывания в кэш прошлых статусов).

    В контекст модели кладём аргументы вызовов инструментов, содержимое/
    размышления закоммиченных сообщений, «живой» partial текущего шага
    (`live_text`) И уже показанные ранее статусы (`recent_statuses`) — так статус
    конкретный, обновляется даже во время долгого ризонинга (когда в `get_state`
    ещё ничего нового не закоммичено) и показывает продвижение, а не повторяется.

    Учитываем ТОЛЬКО текущий ход: всё, что после последнего human-сообщения
    (на доп. сообщении inner-тред содержит и прошлые ходы — их брать нельзя,
    иначе статус будет про старое). Само user-сообщение подаём отдельно, помечая
    как запрос пользователя, чтобы модель могла его обыграть.
    """
    # Граница текущего хода — последнее human-сообщение.
    last_human_idx = -1
    user_message = ""
    for i, msg in enumerate(inner_messages):
        if msg.get("type") == "human":
            last_human_idx = i
            user_message = _content_text(msg)
    current = (
        inner_messages[last_human_idx + 1 :] if last_human_idx >= 0 else inner_messages
    )

    hints: list[str] = []
    for msg in current[-8:]:
        if msg.get("type") == "ai":
            for tc in msg.get("tool_calls") or []:
                hints.append(_summarize_tool_call(tc))
            content = _content_text(msg)
            if content.strip():
                hints.append(f"сообщение/размышления: {content[:500]}")
        elif msg.get("type") == "tool":
            if msg.get("name"):
                hints.append(f"получил результат инструмента {msg['name']}")
    if live_text.strip():
        # Хвост — самое свежее (текущее размышление/генерация прямо сейчас).
        hints.append(f"ПРЯМО СЕЙЧАС пишет/размышляет: {live_text[-600:]}")

    lines: list[str] = []
    if user_message.strip():
        lines.append(f"Запрос пользователя: {user_message[:500]}")
    if hints:
        lines.append("Действия ассистента по этому запросу:")
        lines.extend(hints)
    else:
        lines.append("Ассистент только начал работу над запросом")
    if recent_statuses:
        lines.append(
            "Ранее ты уже показывал такие статусы (не повторяй дословно, "
            "покажи продвижение):"
        )
        lines.extend(f"- {s}" for s in recent_statuses[-MAX_RECENT_STATUSES:])
    context = "\n".join(lines)
    try:
        llm = _get_status_llm()
        resp = await llm.ainvoke(
            [
                SystemMessage(content=STATUS_SYSTEM),
                HumanMessage(content=context),
            ]
        )
        text = strip_thinking(resp.content if isinstance(resp.content, str) else "")
        text = (text or "Думаю").strip().strip('"').split("\n")[0][:300]
    except Exception:
        text = "Думаю"
    push_ui_message(STATUS_UI_NAME, {"text": text}, id=STATUS_UI_ID)
    return text


async def _cancel_inner(config: Any, thread_id: str, run_id: str) -> None:
    with contextlib.suppress(Exception):
        async with client_session(config) as client:
            await client.runs.cancel(thread_id, run_id)


def _outer_thread_id(config: Any) -> str | None:
    """Id ТЕКУЩЕГО (внешнего) треда из config рана."""
    if not isinstance(config, dict):
        return None
    for src in (config.get("metadata"), config.get("configurable")):
        tid = (src or {}).get("thread_id")
        if isinstance(tid, str) and tid.strip():
            return tid.strip().strip("/")
    return None


async def _sync_title_from_inner(config: Any, client, inner_thread_id: str) -> bool:
    """Скопировать thread_title из metadata inner-треда во внешний тред.

    Возвращает True, если название проставлено (тогда больше не пытаемся).
    """
    outer_thread_id = _outer_thread_id(config)
    if not outer_thread_id:
        return False
    with contextlib.suppress(Exception):
        inner = await client.threads.get(inner_thread_id)
        title = ((inner or {}).get("metadata") or {}).get("thread_title")
        if isinstance(title, str) and title.strip():
            await update_thread_metadata(
                config, outer_thread_id, {"thread_title": title.strip()}
            )
            return True
    return False


# --- nodes ------------------------------------------------------------------


async def kickoff(state: ExperimentalState, config) -> dict:
    """Создать/переиспользовать скрытый inner-тред и запустить фоновый ран."""
    messages = state.get("messages") or []
    human = next(
        (m for m in reversed(messages) if getattr(m, "type", None) == "human"),
        None,
    )
    human_content = human.content if human is not None else ""
    # Пробрасываем ВСЕ вложения человека (files, selected, user_input, ...) —
    # тот же shape, что шлёт фронт, поэтому inner-граф прочитает их как обычно.
    human_ak = dict(getattr(human, "additional_kwargs", {}) or {}) if human else {}
    inner_message = {
        "type": "human",
        "content": human_content,
        "additional_kwargs": human_ak,
    }
    # collections (RAG) и mcp_tools приходят во входе submit'а — пробрасываем.
    inner_input = {
        "messages": [inner_message],
        "collections": state.get("collections") or [],
        "mcp_tools": state.get("mcp_tools") or [],
    }
    # Режим исследования / выбранные скилы + автономность.
    outer_conf = (config or {}).get("configurable") or {}
    inner_configurable: dict[str, Any] = {"auto_approve": True}
    for key in _FORWARDED_CONFIGURABLE_KEYS:
        if key in outer_conf:
            inner_configurable[key] = outer_conf[key]

    # Контекст проекта (инструкции + knowledge-коллекция) разворачивается в
    # giga_agent из project_id, а resolve_project_id читает его из metadata
    # ТЕКУЩЕГО треда. Inner-ран крутится в отдельном скрытом треде, поэтому
    # переносим project_id внешнего треда в metadata inner-треда — иначе проект
    # до реального агента не доходит. Метадата треда (в отличие от configurable)
    # переживает interrupt/resume ask_questions, где project_id иначе бы терялся.
    project_id = None
    with contextlib.suppress(Exception):
        project_id = await resolve_project_id(config)
    if project_id is not None:
        # Быстрый путь: resolve_project_id в inner-ране проверит configurable
        # раньше фолбэка на metadata треда (экономит один threads.get). Источник
        # истины — metadata inner-треда (переживает resume), configurable нет.
        inner_configurable["project_id"] = str(project_id)

    inner_thread_id = state.get("inner_thread_id")
    # Граница активности: сколько inner-сообщений уже есть ДО этого хода (реюз
    # треда). Фиксируем ДО runs.create (он добавит нового human) — тогда тулы
    # прошлых ходов не попадут в активность нового.
    inner_baseline = 0
    async with client_session(config) as client:
        if not inner_thread_id:
            inner_metadata: dict[str, Any] = {
                "experimental_inner": True,
                # Фоновый ран без UI одобрения — гоняем giga_agent автономно,
                # чтобы серверные тул-колы выполнялись без interrupt (флаг
                # живёт в metadata треда и переживает resume).
                "auto_approve": True,
            }
            if project_id is not None:
                inner_metadata["project_id"] = str(project_id)
            thread = await client.threads.create(metadata=inner_metadata)
            inner_thread_id = thread["thread_id"]
        else:
            with contextlib.suppress(Exception):
                snap = await client.threads.get_state(inner_thread_id)
                inner_baseline = len(
                    (snap.get("values") or {}).get("messages") or []
                )
        run = await client.runs.create(
            inner_thread_id,
            assistant_id=INNER_ASSISTANT_ID,
            input=inner_input,
            config={"configurable": inner_configurable},
            # Объявляем режимы, чтобы pump мог join_stream'ить messages (живой
            # прогресс) и values (закоммиченный стейт).
            stream_mode=["values", "messages", "updates"],
        )

    push_ui_message(STATUS_UI_NAME, {"text": "Думаю"}, id=STATUS_UI_ID)

    # Артефакт активности: сбрасываем лог хода и эмитим маркер сразу после Human
    # (ordering [Human][Маркер][виджет][AI]). Маркер обновится на завершении.
    outer_thread_id = _outer_thread_id(config)
    activity_id = run["run_id"]
    marker: list[AnyMessage] = []
    if outer_thread_id:
        started_at = _now()
        await _reset_activity(outer_thread_id, started_at)
        await _set_activity_baseline(outer_thread_id, inner_baseline)
        marker = _activity_marker_messages(
            activity_id, _empty_activity(started_at)
        )

    return {
        "messages": marker,
        "inner_thread_id": inner_thread_id,
        "inner_run_id": run["run_id"],
        "activity_id": activity_id,
        # ВАЖНО: сохраняем курсор между ходами. На доп. сообщении inner-тред уже
        # содержит все прошлые сообщения — если сбросить в [], pump всплывёт их
        # заново и старые AI-сообщения задублируются. На новом треде тут [].
        "processed_inner_ids": list(state.get("processed_inner_ids") or []),
        "done": False,
        "title_synced": bool(state.get("title_synced")),
    }


async def pump(state: ExperimentalState, config) -> dict:
    """Довести inner-ран до СЛЕДУЮЩЕГО всплывающего элемента и закоммитить его."""
    thread_id = state["inner_thread_id"]
    run_id = state["inner_run_id"]
    processed: list[str] = list(state.get("processed_inner_ids") or [])
    processed_set = set(processed)
    title_synced = bool(state.get("title_synced"))
    # Артефакт активности хода: копим по внешнему thread_id, обновляем маркер по
    # activity_id (см. kickoff). Оба заданы, только если внешний тред известен.
    outer_thread_id = _outer_thread_id(config)
    activity_id = state.get("activity_id")
    last_status = 0.0
    # Живой буфер текущего partial'а из messages-стрима (обновляется фоновой
    # задачей). Нужен, чтобы статусы обновлялись во время долгого ризонinга.
    live: dict[str, str] = {"text": ""}
    live_task: asyncio.Task | None = None

    try:
        async with client_session(config) as client:
            live_task = asyncio.create_task(
                _consume_live(config, thread_id, run_id, live)
            )
            while True:
                snap = await client.threads.get_state(thread_id)
                inner_messages = (snap.get("values") or {}).get("messages") or []

                # Копим вызовы инструментов текущего хода в лог активности.
                if outer_thread_id:
                    await _record_tools_from_snapshot(outer_thread_id, inner_messages)

                # Пробрасываем название треда из inner в внешний (giga_agent
                # генерит его после первого хода; у обёртки title-middleware нет).
                if not title_synced:
                    title_synced = await _sync_title_from_inner(
                        config, client, thread_id
                    )

                produced: list[AnyMessage] | None = None
                for msg in inner_messages:
                    mid = msg.get("id")
                    if not mid or mid in processed_set:
                        continue
                    if not _eligible_output(msg):
                        processed_set.add(mid)
                        processed.append(mid)
                        continue
                    # Нашли следующий всплывающий элемент.
                    if msg.get("type") == "ai":
                        produced = [await _rewrite_ai(_content_text(msg))]
                    else:
                        produced = _forward_widget(msg)
                    processed_set.add(mid)
                    processed.append(mid)
                    break

                if produced is not None:
                    # Всегда done=False: завершение определяет СЛЕДУЮЩИЙ pump по
                    # свежему снапшоту. Иначе можно завершиться преждевременно —
                    # пока шёл await переписывания, inner-ран мог закоммитить ещё
                    # сообщения, которых нет в этом (устаревшем) снапшоте.
                    return {
                        "messages": produced,
                        "processed_inner_ids": processed,
                        "interrupt_value": None,
                        "done": False,
                        "title_synced": title_synced,
                    }

                # Нет нового всплывающего элемента прямо сейчас.
                run = await client.runs.get(thread_id, run_id)
                if run.get("status") not in _ACTIVE_RUN_STATUSES:
                    # Ран встал: это либо ЗАВЕРШЕНИЕ, либо INTERRUPT (напр.
                    # ask_questions). Различаем по закоммиченным interrupt'ам в
                    # свежем снапшоте — статус «interrupted» ненадёжен (aegra тем
                    # же статусом метит и cancel). Есть pending-interrupt →
                    # уходим в ноду `interrupt` пробрасывать его наружу.
                    snap = await client.threads.get_state(thread_id)
                    interrupts = snap.get("interrupts") or []
                    if interrupts:
                        # value уже несёт tool_call_id (ask_questions кладёт его в
                        # payload) — просто пробрасываем наружу.
                        return {
                            "messages": [],
                            "processed_inner_ids": processed,
                            "interrupt_value": interrupts[0].get("value"),
                            "done": False,
                            "title_synced": title_synced,
                        }
                    # Финальная попытка проставить название (могло появиться уже
                    # после последнего всплывшего элемента).
                    if not title_synced:
                        await _sync_title_from_inner(config, client, thread_id)
                    await _forget_statuses(run_id)

                    # Финализируем активность и обновляем маркер тем же id (add_messages
                    # обновит ToolMessage на месте): дописываем finished_at + полный
                    # список тулов из свежего снапшота, снапшот встраивается в маркер.
                    final_marker: list[AnyMessage] = []
                    if outer_thread_id and activity_id:
                        final_messages = (snap.get("values") or {}).get(
                            "messages"
                        ) or []
                        await _record_tools_from_snapshot(
                            outer_thread_id, final_messages
                        )
                        activity = await _finalize_activity(outer_thread_id)
                        final_marker = _activity_marker_messages(activity_id, activity)
                        # Снапшот уже вшит в маркер (переживает перезагрузку), а
                        # живой кэш больше не нужен — чистим, чтобы активность НЕ
                        # протекала в следующий ход (reset в kickoff — подстраховка).
                        await _forget_activity(outer_thread_id)

                    return {
                        "messages": final_marker,
                        "processed_inner_ids": processed,
                        "interrupt_value": None,
                        "done": True,
                        "title_synced": True,
                    }

                now = time.monotonic()
                if now - last_status >= STATUS_INTERVAL_SEC:
                    status_text = await _push_status(
                        inner_messages,
                        live.get("text", ""),
                        await _get_recent_statuses(run_id),
                    )
                    if status_text and status_text != "Думаю":
                        await _remember_status(run_id, status_text)
                        if outer_thread_id:
                            await _record_status(outer_thread_id, status_text, _now())
                    last_status = now
                await asyncio.sleep(POLL_INTERVAL_SEC)
    except asyncio.CancelledError:
        # Остановка внешнего рана → отменяем фоновый inner-ран (best-effort).
        # Маркер в state остаётся «running» (после raise ноду уже не коммитим),
        # но фиксируем finished_at в кэше, чтобы живая ручка отдавала конечную
        # длительность, а не тикающий таймер после стопа.
        if outer_thread_id:
            await asyncio.shield(_finalize_activity(outer_thread_id))
        await asyncio.shield(_forget_statuses(run_id))
        await asyncio.shield(_cancel_inner(config, thread_id, run_id))
        raise
    finally:
        if live_task is not None:
            live_task.cancel()
            with contextlib.suppress(BaseException):
                await live_task


async def interrupt_node(state: ExperimentalState, config) -> dict:
    """Пробросить interrupt inner-рана наружу и вернуть ответ пользователя внутрь.

    `interrupt(value)` ставит ВНЕШНИЙ ран на паузу прямо здесь — фронт рендерит
    payload (тот же формат, что у giga_agent, напр. ask_questions). На resume
    LangGraph выполняет ноду заново с самого начала, и `interrupt(...)` возвращает
    ответ пользователя — поэтому вызов идёт ПЕРВЫМ, до любых side-эффектов.
    Ответ пробрасываем в inner-тред новым run'ом (`command.resume`), обновляем
    `inner_run_id` и возвращаемся в `pump` дожимать ран.
    """
    interrupt_value = state.get("interrupt_value")
    answer = interrupt(interrupt_value)

    # Сразу коммитим ответ ask_questions во внешний граф (см. helper) — тогда его
    # видит первый же values-снапшот после resume и карточка не моргает.
    messages = _ask_questions_messages(interrupt_value, answer)

    thread_id = state["inner_thread_id"]
    old_run_id = state.get("inner_run_id")
    async with client_session(config) as client:
        run = await client.runs.create(
            thread_id,
            assistant_id=INNER_ASSISTANT_ID,
            command={"resume": answer},
            # auto_approve живёт в metadata треда (переживает resume), но дублируем
            # в configurable для надёжности; input не нужен — резюмим с места.
            config={"configurable": {"auto_approve": True}},
            stream_mode=["values", "messages", "updates"],
        )
    # Кэш статусов ключуется по run_id — старый run завершён, чистим.
    if old_run_id:
        await _forget_statuses(old_run_id)
    return {
        "messages": messages,
        "inner_run_id": run["run_id"],
        "interrupt_value": None,
        "done": False,
    }


def route_after_pump(state: ExperimentalState) -> str:
    if state.get("interrupt_value") is not None:
        return "interrupt"
    return END if state.get("done") else "pump"


workflow = StateGraph(ExperimentalState)
workflow.add_node("kickoff", kickoff)
workflow.add_node("pump", pump)
workflow.add_node("interrupt", interrupt_node)
workflow.add_edge(START, "kickoff")
workflow.add_edge("kickoff", "pump")
workflow.add_conditional_edges(
    "pump", route_after_pump, {"pump": "pump", "interrupt": "interrupt", END: END}
)
workflow.add_edge("interrupt", "pump")

graph = workflow.compile().with_config({"recursion_limit": 200})
