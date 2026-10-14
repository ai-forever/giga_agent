from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from giga_agent.core.agent.tool_policy import (
    ToolEffect,
    ToolPlanMode,
    tool_extras,
)


class QuestionInput(BaseModel):
    """Отдельный вопрос с вариантами ответа."""

    text: str = Field(description="Текст вопроса")
    options: list[str] = Field(
        description=(
            "Список вариантов ответа. "
            "Вариант 'Другое' со свободным вводом автоматически добавляется в UI — "
            "НЕ включай собственные варианты 'Другое'/'Свой вариант'."
        ),
    )
    type: Literal["single", "multi"] = Field(
        default="single",
        description="'single' for single choice (radio buttons), 'multi' for multiple choice (checkboxes)",
    )


class AskQuestionsInput(BaseModel):
    """Input schema for the ask_questions tool."""

    questions: list[QuestionInput] = Field(
        description="Список вопросов пользователю",
    )
    # Инъектится рантаймом (не виден модели). При явном args_schema LangChain ищет
    # injected-поля именно в схеме, поэтому объявляем его здесь, а не только в
    # сигнатуре функции.
    tool_call_id: Annotated[str, InjectedToolCallId] = Field(default="")


@tool(
    "ask_questions",
    args_schema=AskQuestionsInput,
    extras=tool_extras(ToolEffect.WRITE, plan_mode=ToolPlanMode.ALLOW, not_process=True),
)
async def ask_questions(
    questions: list,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> str:
    """Задай пользователю один или несколько уточняющих вопросов с заготовленными вариантами ответа

    Используй этот tool когда запрос пользователя неясный или когда требуется
    конкретная информация перед тем как продолжить. Каждый вопрос может быть
    single-choice или multi-choice. Вариант "Другое" со свободным вводом
    автоматически показывается в UI - НЕ добавляй его в свои варианты ответа.
    Если в вопросе имеет место рекомендованный вариант - пометь его (Рекомендовано) в конце
    """
    if not questions:
        return "Вопросы не предоставлены."

    formatted_questions: list[dict] = []
    for i, q_raw in enumerate(questions):
        q = q_raw.model_dump() if hasattr(q_raw, "model_dump") else dict(q_raw)
        formatted_questions.append(
            {
                "id": f"q_{i}",
                "text": q.get("text", ""),
                "type": q.get("type", "single"),
                "options": [
                    {"id": f"q_{i}_opt_{j}", "text": str(opt)}
                    for j, opt in enumerate(q.get("options", []))
                ],
            }
        )

    # tool_call_id кладём в payload interrupt'а: фронт по нему оптимистично
    # привязывает карточку ответов (в обёртке giga_agent_experimental AI-сообщения
    # с этим tool_call на момент interrupt'а ещё нет), а возвращаемый ниже
    # ToolMessage всё равно получает именно этот id — они совпадают.
    value = interrupt(
        {
            "type": "questions",
            "questions": formatted_questions,
            "tool_call_id": tool_call_id,
        }
    )
    # Структурированный результат отдаём и модели (через `summary`), и фронту
    # (он рендерит карточку «как ответил пользователь» по этим же полям).
    return build_questions_result(formatted_questions, value)


def build_questions_result(formatted_questions: list[dict], value) -> dict:
    """Собрать результат ask_questions из заданных вопросов и ответа-resume.

    Вынесено, чтобы обёртка giga_agent_experimental (interrupt_node) строила ровно
    тот же ToolMessage сразу после resume — иначе карточка ответов «моргает», пока
    inner-ран заново прогоняет ask_questions.
    """
    if isinstance(value, dict) and value.get("type") == "comment":
        user_msg = value.get("message", "")
        summary = (
            f'Пользователь пропустил вопросы и ответил: "{user_msg}"'
            if user_msg
            else "Пользователь пропустил вопросы и не оставил ответа."
        )
        return {
            "ask_questions": True,
            "skipped": True,
            "comment": user_msg,
            "summary": summary,
            "items": [],
        }

    answers = value.get("answers", []) if isinstance(value, dict) else []
    answers_by_q = {a.get("question_id", ""): a for a in answers}
    items: list[dict] = []
    parts: list[str] = []
    for q in formatted_questions:
        answer = answers_by_q.get(q["id"], {})
        selected_ids = answer.get("selected", [])
        other_text = answer.get("other_text", "")
        opt_map = {opt["id"]: opt["text"] for opt in q["options"]}
        selected_texts = [opt_map.get(s, s) for s in selected_ids]
        all_selected = list(selected_texts)
        if other_text:
            all_selected.append(other_text)
        items.append(
            {
                "question": q["text"],
                "type": q["type"],
                "options": [opt["text"] for opt in q["options"]],
                "selected": selected_texts,
                "other_text": other_text,
            }
        )
        if all_selected:
            parts.append(f"Q: {q['text']}\nA: {', '.join(all_selected)}")

    return {
        "ask_questions": True,
        "skipped": False,
        "summary": "\n\n".join(parts)
        if parts
        else "Пользователь не предоставил ответ.",
        "items": items,
    }
