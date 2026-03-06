from typing import Annotated, Literal, TypeAlias

from langchain.tools import ToolRuntime
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from giga_agent.core.db import get_session_factory
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    get_current_user_from_runtime,
    normalize_search_result,
    resolve_user_llm,
    resolve_user_search_engine,
)
from giga_agent.modules.subagents_legacy.uploads import (
    build_tool_message,
    resolve_upload_prefix,
    upload_files_for_runtime_user,
)
from giga_agent.utils.langgraph_sdk import get_client


class LeanGraphState(TypedDict):
    main_task: Annotated[str, "Основная задача от пользователя"]
    competitors_analysis: Annotated[str, "Анализ конкурентов"]
    feedback: Annotated[
        str,
        "Фидбек от пользователя. Обязательно учитывай его в своих ответах!",
    ]

    # Lean Canvas
    problem: Annotated[str, "Проблема, которую пытается решить продукт или услуга."]
    solution: Annotated[str, "Краткое описание предлагаемого решения."]
    key_metrics: Annotated[
        str,
        "Ключевые показатели, которые необходимо измерять для отслеживания прогресса.",
    ]
    unique_value_proposition: Annotated[
        str,
        (
            "Единое, ясное и убедительное сообщение, объясняющее, "
            "почему вы отличаетесь от других и почему стоит покупать именно у вас."
        ),
    ]
    unfair_advantage: Annotated[
        str,
        "То, что конкуренты не могут легко скопировать или купить.",
    ]
    channels: Annotated[str, "Пути охвата ваших клиентских сегментов."]
    customer_segments: Annotated[
        str,
        "Целевая аудитория или группы людей, которых вы пытаетесь охватить.",
    ]
    cost_structure: Annotated[str, "Основные затраты, связанные с ведением бизнеса."]
    revenue_streams: Annotated[str, "Как бизнес будет зарабатывать деньги."]


async def _resolve_llm(config: RunnableConfig):
    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_config(config, session=session)
        llm = await resolve_user_llm(user, session=session)
    return llm.with_config(tags=["nostream"])


def state_to_string(state: LeanGraphState) -> str:
    """Преобразует состояние в строку для отображения."""
    result = []
    for field, annotation in LeanGraphState.__annotations__.items():
        value = state.get(field, "")
        if value:
            # annotation is typing.Annotated[type, description]
            if hasattr(annotation, "__metadata__") and annotation.__metadata__:
                desc = annotation.__metadata__[0]
            else:
                desc = ""
            result.append(f"{desc} ({field}): {value}")
    return "\n".join(result)


async def ask_llm(state: LeanGraphState, question: str, config: RunnableConfig) -> str:
    TEMPLATE = """
    Ты - эксперт в области стартапов и Lean Canvas. Твоя задача - помочь пользователю создать Lean Canvas для его задачи.
    Учитывай уже заполненные части таблицы Lean Canvas и главную задачу пользователя (main_task).

    Обязательно учитывай фидбек от пользователя (feedback), если он задан.
    <STATE>
    {state}
    </STATE>
    
    ЯЗЫК ОБЩЕНИЯ

    Ты должен общаться с пользователем на выбранном им языке.
    Язык пользователя: {language}.

    Ответь на вопрос: {question}
    Отвечай коротко, не более 1-2 коротких предложений и обязательно учти фидбек от пользователя (feedback), если он задан. Оформи ответ в виде буллетов.
    """  # noqa: E501

    prompt = ChatPromptTemplate.from_messages([("system", TEMPLATE)]).partial(
        language="ru",
    )

    llm = await _resolve_llm(config)
    chain = prompt | llm | StrOutputParser()
    return await chain.ainvoke({"state": state_to_string(state), "question": question})


async def customer_segments(state: LeanGraphState, config: RunnableConfig):
    return {
        "customer_segments": await ask_llm(state, "Кто ваши целевые клиенты?", config),
    }


async def problem(state: LeanGraphState, config: RunnableConfig):
    return {"problem": await ask_llm(state, "Какую проблему вы решаете?", config)}


async def unique_value_proposition(state: LeanGraphState, config: RunnableConfig):
    return {
        "unique_value_proposition": await ask_llm(
            state,
            "Какое уникальное предложение вы предлагаете?",
            config,
        ),
    }


async def solution(state: LeanGraphState, config: RunnableConfig):
    return {
        "solution": await ask_llm(
            state,
            "Какое решение вы предлагаете для этой проблемы?",
            config,
        ),
    }


async def channels(state: LeanGraphState, config: RunnableConfig):
    return {
        "channels": await ask_llm(
            state,
            "Какие каналы привлечения клиентов вы используете?",
            config,
        ),
    }


async def revenue_streams(state: LeanGraphState, config: RunnableConfig):
    return {
        "revenue_streams": await ask_llm(
            state,
            "Как вы планируете зарабатывать деньги?",
            config,
        ),
    }


async def cost_structure(state: LeanGraphState, config: RunnableConfig):
    return {
        "cost_structure": await ask_llm(
            state, "Какова структура ваших затрат?", config
        ),
    }


async def key_metrics(state: LeanGraphState, config: RunnableConfig):
    return {
        "key_metrics": await ask_llm(
            state,
            "Какие ключевые показатели вы будете отслеживать?",
            config,
        ),
    }


async def unfair_advantage(state: LeanGraphState, config: RunnableConfig):
    return {
        "unfair_advantage": await ask_llm(
            state,
            "Какое ваше конкурентное преимущество?",
            config,
        ),
    }


class CompetitorsAnalysisResult(BaseModel):
    """Анализ конкурентов"""

    thoughts: str = Field(description="Мысли по поводу ответа")
    solution: str = Field(
        description=(
            "Какие конкуренты существуют и чем они отличаются от вашего продукта"
        ),
    )
    is_unique: bool = Field(description="Уникально ли ваше предложение?")


COMPETITION_ANALYSIS_TEMPLATE = """Ты работаешь над таблицей Lean Canvas и тебе нужно проанализировать конкурентов.

Учитывай уже заполненные части таблицы Lean Canvas и главную задачу пользователя (main_task).
<STATE>
{state}
</STATE>

Результаты поиска по запросу "{unique_value_proposition}". Учитывай их, чтобы понять, уникальную ли идею ты придумал.
Если в поиске нет ничего похожего, значит идея вероятно уникальная.
<SEARCH_RESULTS>
{search_results}
</SEARCH_RESULTS>

ЯЗЫК ОБЩЕНИЯ

Ты должен общаться с пользователем на выбранном им языке.
Язык пользователя: {language}.

Выведи только следующую информацию в формате JSON:
{format_instructions}"""  # noqa: E501


async def check_unique(
    state: LeanGraphState,
    config: RunnableConfig,
) -> Command[Literal["4_solution", "3_unique_value_proposition"]]:
    if config["configurable"].get("skip_search", False):
        # Если пропускаем поиск, то просто переходим к следующему шагу
        return Command(goto="4_solution")

    parser = PydanticOutputParser(pydantic_object=CompetitorsAnalysisResult)
    prompt = ChatPromptTemplate.from_messages(
        [("system", COMPETITION_ANALYSIS_TEMPLATE)],
    ).partial(format_instructions=parser.get_format_instructions(), language="ru")

    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_config(config, session=session)
        search_engine = await resolve_user_search_engine(user, session=session)
    search_results = await search_engine.search([state["unique_value_proposition"]])
    search_results_text = "\n\n".join(
        normalize_search_result(item) for item in search_results
    )

    llm = await _resolve_llm(config)
    llm = await _resolve_llm(config)
    chain = prompt | llm | parser
    res = await chain.ainvoke(
        {
            "state": state_to_string(state),
            "unique_value_proposition": state["unique_value_proposition"],
            "search_results": search_results_text,
        },
    )

    competitors_analysis = (
        state.get("competitors_analysis", "")
        + "\n"
        + state["unique_value_proposition"]
        + " - "
        + res.solution
    )

    if res.is_unique:
        # Если предложение уникально, переходим к следующему шагу
        return Command(
            update={"competitors_analysis": competitors_analysis.strip()},
            goto="4_solution",
        )
    # Если предложение не уникально, возвращаемся к шагу "3_unique_value_proposition"
    return Command(
        update={"competitors_analysis": competitors_analysis.strip()},
        goto="3_unique_value_proposition",
    )


RedirectStep: TypeAlias = Literal[
    "1_customer_segments",
    "2_problem",
    "3_unique_value_proposition",
    "4_solution",
    "5_channels",
    "6_revenue_streams",
    "7_cost_structure",
    "8_key_metrics",
    "9_unfair_advantage",
    "__end__",
]


class UserFeedback(BaseModel):
    """Анализ конкурентов"""

    feedback: str = Field(description="Фидебек пользователя, что надо исправить")
    next_step: RedirectStep = Field(description="Следующий шаг в Lean Canvas")
    is_done: bool = Field(description="Можно ли завершать создание Lean Canvas?")


FEEDBACK_TEMPLATE = """Ты работаешь над таблицей Lean Canvas. Ты уже сгенерировал версию Lean Canvas и получил фидбек от пользователя.
Тебе нужно разобраться фидбек и понять, как действовать дальше, заполнив таблицу с ответом.

ЯЗЫК ОБЩЕНИЯ

Ты должен общаться с пользователем на выбранном им языке.
Язык пользователя: {language}.

Учитывай уже заполненные части таблицы Lean Canvas и главную задачу пользователя (main_task).
<STATE>
{state}
</STATE>

Вот фидбек пользователя на твою работу:
{feedback}

Извлеки из него данные для дальнейшей работы. Если пользователь всем доволен или не говорит ничего конкретного, 
то прими решение закончить генерацию (is_done = True).
Выведи только следующую информацию в формате JSON:
{format_instructions}"""  # noqa: E501


async def get_feedback(
    state: LeanGraphState,
    config: RunnableConfig,
) -> Command[RedirectStep]:
    if config["configurable"].get("need_interrupt"):
        feedback = interrupt(
            "Пожалуйста, дайте обратную связь по Lean Canvas. "
            "Если все хорошо, напишите 'Хорошо'. "
            "Если нужно что-то изменить, напишите, "
            "что именно и с какого шага начать.",
        )
    else:
        feedback = "Все хорошо!"
    llm = await _resolve_llm(config)

    parser = PydanticOutputParser(pydantic_object=UserFeedback)
    prompt = ChatPromptTemplate.from_messages([("system", FEEDBACK_TEMPLATE)]).partial(
        format_instructions=parser.get_format_instructions(),
        language="ru",
    )

    chain = prompt | llm | parser
    res = await chain.ainvoke(
        {
            "state": state_to_string(state),
            "feedback": feedback,
        },
    )

    if res.is_done:
        return Command(update={}, goto=END)
    # Если предложение не уникально, возвращаемся к шагу "3_unique_value_proposition"
    return Command(
        update={"feedback": res.feedback},
        goto=res.next_step,
    )


graph = StateGraph(LeanGraphState)

graph.add_node("1_customer_segments", customer_segments)
graph.add_node("2_problem", problem)
graph.add_node("3_unique_value_proposition", unique_value_proposition)
graph.add_node("3.1_check_unique", check_unique)
graph.add_node("4_solution", solution)
graph.add_node("5_channels", channels)
graph.add_node("6_revenue_streams", revenue_streams)
graph.add_node("7_cost_structure", cost_structure)
graph.add_node("8_key_metrics", key_metrics)
graph.add_node("9_unfair_advantage", unfair_advantage)
graph.add_node("get_feedback", get_feedback)

graph.add_edge(START, "1_customer_segments")
graph.add_edge("1_customer_segments", "2_problem")
graph.add_edge("2_problem", "3_unique_value_proposition")
graph.add_edge("3_unique_value_proposition", "3.1_check_unique")
graph.add_edge("4_solution", "5_channels")
graph.add_edge("5_channels", "6_revenue_streams")
graph.add_edge("6_revenue_streams", "7_cost_structure")
graph.add_edge("7_cost_structure", "8_key_metrics")
graph.add_edge("8_key_metrics", "9_unfair_advantage")
graph.add_edge("9_unfair_advantage", "get_feedback")

app = graph.compile()

NEW_LINE = "\n"


def lean_canvas_to_text(state) -> str:
    return f"""1. Customer Segments
{state["customer_segments"]}

2. Problem
{state["problem"]}

3. Unique Value Proposition
{state["unique_value_proposition"]}

4. Solution
{state["solution"]}

5. Channels
{state["channels"]}

6. Revenue Streams
{state["revenue_streams"]}

7. Cost Structure
{state["cost_structure"]}

8. Key Metrics
{state["key_metrics"]}

9. Unfair Advantage
{state["unfair_advantage"]}"""


def lean_canvas_to_html(state) -> str:
    """Lean Canvas -> HTML"""
    # --- CSS для сетки 5×2 + нижний ряд -----------------------------------
    css = """
    <style>
    .canvas {
        display: grid;
        grid-template-columns: 13% 30% 13% 30% 13%;   /* ширины колонок */
        grid-template-rows: auto auto auto auto;           /* Title + 2 ряда + низ   */
        gap: 8px;
        background: transparent;
        font-family: Arial, sans-serif;
    }
    .box {
        background:#e59a12;
        color:#fff;
        border:1px solid #fff;
        padding:12px 14px;
        line-height:1.3;
    }
    .title { font-weight:700; margin-bottom:6px; }
    .canvas-title-cell { /* New class for the title cell */
        grid-column: 1 / -1; /* Span all columns */
        grid-row: 1 / span 1;    /* First row */
        text-align: center;
        color: #08c; /* Copied from original h2 */
        font-family: Arial, sans-serif; /* Copied from original h2 */
        padding: 8px 0; /* Vertical padding */
        font-size: 1.3em;
        font-weight: bold;
    }
    /* раскладка по «ячейкам» */
    .problem           { grid-area: 2 / 1 / span 2 / span 1; } /* Shifted down */
    .solution          { grid-area: 2 / 2 / span 1 / span 1; } /* Shifted down */
    .key_metrics       { grid-area: 3 / 2 / span 1 / span 1; } /* Shifted down */
    .uvp               { grid-area: 2 / 3 / span 2 / span 1; } /* Shifted down */
    .unfair            { grid-area: 2 / 4 / span 1 / span 1; } /* Shifted down */
    .channels          { grid-area: 3 / 4 / span 1 / span 1; } /* Shifted down */
    .customer_segments { grid-area: 2 / 5 / span 2 / span 1; } /* Shifted down */
    .cost_structure    { grid-area: 4 / 1 / span 1 / span 3; } /* Shifted down */
    .revenue_streams   { grid-area: 4 / 4 / span 1 / span 2; } /* Shifted down */
    </style>
    """

    # --- HTML-разметка ------------------------------------------------------
    html = f"""
    <meta charset="utf-8">
    {css}
    <div class="canvas">
        <div class="canvas-title-cell">{state["main_task"].replace(NEW_LINE, "<br>")}</div>

        <div class="box problem">
            <div class="title">2. Problem</div>
            {state["problem"].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box solution">
            <div class="title">4. Solution</div>
            {state["solution"].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box key_metrics">
            <div class="title">8. Key Metrics</div>
            {state["key_metrics"].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box uvp">
            <div class="title">3. Unique Value Proposition</div>
            {state["unique_value_proposition"].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box unfair">
            <div class="title">9. Unfair Advantage</div>
            {state["unfair_advantage"].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box channels">
            <div class="title">5. Channels</div>
            {state["channels"].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box customer_segments">
            <div class="title">1. Customer Segments</div>
            {state["customer_segments"].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box cost_structure">
            <div class="title">7. Cost Structure</div>
            {state["cost_structure"].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box revenue_streams">
            <div class="title">6. Revenue Streams</div>
            {state["revenue_streams"].replace(NEW_LINE, "<br>")}
        </div>

    </div>
    """  # noqa: E501
    return html


@tool
async def lean_canvas(
    theme: str = Field(description="На какую тему создаем Lean Canvas"),
    runtime: ToolRuntime = None,
):
    """Создает Lean Canvas под задачу пользователя. Полезно для проработки стартапов."""
    factory = await get_session_factory()
    async with factory() as session:
        user = await get_current_user_from_runtime(runtime, session=session)
    client = get_client(runtime.config)
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    push_ui_message(
        "agent_execution",
        {
            "agent": "lean_canvas",
            "node": "__start__",
            "tool_call_id": runtime.tool_call_id,
        },
    )
    state = {}
    async for chunk in client.runs.stream(
        thread_id=thread_id,
        assistant_id="lean_canvas",
        input={"main_task": theme},
        stream_mode=["values", "updates"],
        on_disconnect="cancel",
        config={
            "configurable": {
                "thread_id": thread_id,
                "need_interrupt": False,
                "skip_search": user.search_engine_id is None,
            },
        },
    ):
        if chunk.event == "values":
            state = chunk.data
        elif chunk.event == "updates":
            push_ui_message(
                "agent_execution",
                {
                    "agent": "lean_canvas",
                    "node": list(chunk.data.keys())[0],
                    "tool_call_id": runtime.tool_call_id,
                },
            )
    html = lean_canvas_to_html(state)
    text = lean_canvas_to_text(state)
    prefix = resolve_upload_prefix(runtime)
    uploaded = await upload_files_for_runtime_user(
        runtime,
        files=[
            {
                "file_name": f"{prefix}/lean_canvas.html",
                "file_type": "html",
                "content": html.encode("utf-8"),
            }
        ],
    )
    file = uploaded[0]
    return build_tool_message(
        runtime,
        tool_name="lean_canvas",
        payload={
            "text": text,
            "message": (
                f"В результате выполнения была сгенерирована HTML страница "
                f"{file.sandbox_path}. Покажи её пользователю через "
                f'"![alt-описание](attachment:{file.sandbox_path})" и '
                f"напиши ответ с использованием текста lean canvas и "
                f"куда двигаться пользователю дальше"
            ),
        },
        attachments=uploaded,
    )
