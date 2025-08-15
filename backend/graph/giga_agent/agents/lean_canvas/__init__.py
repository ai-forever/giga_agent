import os

from langchain_core.tools import tool
from langchain_core.output_parsers import StrOutputParser
from langchain.prompts import ChatPromptTemplate
from langgraph.types import interrupt
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.ui import push_ui_message
from langgraph_sdk import get_client
from typing_extensions import TypedDict, Annotated

from giga_agent.utils.lang import LANG
from giga_agent.utils.llm import load_llm

llm = load_llm().with_config(tags=["nostream"])


class LeanGraphState(TypedDict):
    main_task: Annotated[str, "Основная задача от пользователя"]
    competitors_analysis: Annotated[str, "Анализ конкурентов"]
    feedback: Annotated[
        str, "Фидбек от пользователя. Обязательно учитывай его в своих ответах!"
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
        "Единое, ясное и убедительное сообщение, объясняющее, почему вы отличаетесь от других и почему стоит покупать именно у вас.",
    ]
    unfair_advantage: Annotated[
        str, "То, что конкуренты не могут легко скопировать или купить."
    ]
    channels: Annotated[str, "Пути охвата ваших клиентских сегментов."]
    customer_segments: Annotated[
        str, "Целевая аудитория или группы людей, которых вы пытаетесь охватить."
    ]
    cost_structure: Annotated[str, "Основные затраты, связанные с ведением бизнеса."]
    revenue_streams: Annotated[str, "Как бизнес будет зарабатывать деньги."]


def state_to_string(state: LeanGraphState) -> str:
    """
    Преобразует состояние в строку для отображения.
    """
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
    """

    prompt = ChatPromptTemplate.from_messages([("system", TEMPLATE)]).partial(
        language=LANG
    )

    chain = prompt | llm | StrOutputParser()
    return await chain.ainvoke({"state": state_to_string(state), "question": question})


async def customer_segments(state: LeanGraphState, config: RunnableConfig):
    return {
        "customer_segments": await ask_llm(state, "Кто ваши целевые клиенты?", config)
    }


async def problem(state: LeanGraphState, config: RunnableConfig):
    return {"problem": await ask_llm(state, "Какую проблему вы решаете?", config)}


async def unique_value_proposition(state: LeanGraphState, config: RunnableConfig):
    return {
        "unique_value_proposition": await ask_llm(
            state, "Какое уникальное предложение вы предлагаете?", config
        )
    }


async def solution(state: LeanGraphState, config: RunnableConfig):
    return {
        "solution": await ask_llm(
            state, "Какое решение вы предлагаете для этой проблемы?", config
        )
    }


async def channels(state: LeanGraphState, config: RunnableConfig):
    return {
        "channels": await ask_llm(
            state, "Какие каналы привлечения клиентов вы используете?", config
        )
    }


async def revenue_streams(state: LeanGraphState, config: RunnableConfig):
    return {
        "revenue_streams": await ask_llm(
            state, "Как вы планируете зарабатывать деньги?", config
        )
    }


async def cost_structure(state: LeanGraphState, config: RunnableConfig):
    return {
        "cost_structure": await ask_llm(state, "Какова структура ваших затрат?", config)
    }


async def key_metrics(state: LeanGraphState, config: RunnableConfig):
    return {
        "key_metrics": await ask_llm(
            state, "Какие ключевые показатели вы будете отслеживать?", config
        )
    }


async def unfair_advantage(state: LeanGraphState, config: RunnableConfig):
    return {
        "unfair_advantage": await ask_llm(
            state, "Какое ваше конкурентное преимущество?", config
        )
    }


from typing_extensions import Literal
from langgraph.types import Command
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser
from langchain_tavily import TavilySearch


class CompetitorsAnalysisResult(BaseModel):
    """Анализ конкурентов"""

    thoughts: str = Field(description="Мысли по поводу ответа")
    solution: str = Field(
        description="Какие конкуренты существуют и чем они отличаются от вашего продукта"
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
{format_instructions}"""


async def check_unique(
    state: LeanGraphState, config: RunnableConfig
) -> Command[Literal["4_solution", "3_unique_value_proposition"]]:
    if config["configurable"].get("skip_search", False):
        # Если пропускаем поиск, то просто переходим к следующему шагу
        return Command(goto="4_solution")

    parser = PydanticOutputParser(pydantic_object=CompetitorsAnalysisResult)
    prompt = ChatPromptTemplate.from_messages(
        [("system", COMPETITION_ANALYSIS_TEMPLATE)]
    ).partial(format_instructions=parser.get_format_instructions(), language=LANG)

    search_results_text = await TavilySearch().arun(state["unique_value_proposition"])

    chain = prompt | llm | parser
    res = await chain.ainvoke(
        {
            "state": state_to_string(state),
            "unique_value_proposition": state["unique_value_proposition"],
            "search_results": search_results_text,
        }
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
    else:
        # Если предложение не уникально, возвращаемся к шагу "3_unique_value_proposition"
        return Command(
            update={"competitors_analysis": competitors_analysis.strip()},
            goto="3_unique_value_proposition",
        )


from typing import Literal, TypeAlias

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
{format_instructions}"""


async def get_feedback(
    state: LeanGraphState, config: RunnableConfig
) -> Command[RedirectStep]:
    if config["configurable"].get("need_interrupt"):
        feedback = interrupt(
            """Пожалуйста, дайте обратную связь по Lean Canvas. Если все хорошо, напишите 'Хорошо'. 
    Если нужно что-то изменить, напишите, что именно и с какого шага начать."""
        )
    else:
        feedback = "Все хорошо!"

    parser = PydanticOutputParser(pydantic_object=UserFeedback)
    prompt = ChatPromptTemplate.from_messages([("system", FEEDBACK_TEMPLATE)]).partial(
        format_instructions=parser.get_format_instructions(), language=LANG
    )

    chain = prompt | llm | parser
    res = await chain.ainvoke(
        {
            "state": state_to_string(state),
            "feedback": feedback,
        }
    )

    if res.is_done:
        return Command(update={}, goto=END)
    else:
        # Если предложение не уникально, возвращаемся к шагу "3_unique_value_proposition"
        return Command(
            update={"feedback": res.feedback},
            goto=res.next_step,
        )


from langgraph.checkpoint.memory import MemorySaver

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


import uuid

NEW_LINE = "\n"


def lean_canvas_to_text(state) -> str:
    return f"""1. Customer Segments
{state['customer_segments']}

2. Problem
{state['problem']}

3. Unique Value Proposition
{state['unique_value_proposition']}

4. Solution
{state['solution']}

5. Channels
{state['channels']}

6. Revenue Streams
{state['revenue_streams']}

7. Cost Structure
{state['cost_structure']}

8. Key Metrics
{state['key_metrics']}

9. Unfair Advantage
{state['unfair_advantage']}"""


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
    {css}
    <div class="canvas">
        <div class="canvas-title-cell">{state['main_task'].replace(NEW_LINE, "<br>")}</div>

        <div class="box problem">
            <div class="title">2. Problem</div>
            {state['problem'].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box solution">
            <div class="title">4. Solution</div>
            {state['solution'].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box key_metrics">
            <div class="title">8. Key Metrics</div>
            {state['key_metrics'].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box uvp">
            <div class="title">3. Unique Value Proposition</div>
            {state['unique_value_proposition'].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box unfair">
            <div class="title">9. Unfair Advantage</div>
            {state['unfair_advantage'].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box channels">
            <div class="title">5. Channels</div>
            {state['channels'].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box customer_segments">
            <div class="title">1. Customer Segments</div>
            {state['customer_segments'].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box cost_structure">
            <div class="title">7. Cost Structure</div>
            {state['cost_structure'].replace(NEW_LINE, "<br>")}
        </div>

        <div class="box revenue_streams">
            <div class="title">6. Revenue Streams</div>
            {state['revenue_streams'].replace(NEW_LINE, "<br>")}
        </div>

    </div>
    """
    return html


@tool
async def lean_canvas(
    theme: str = Field(description="На какую тему создаем Lean Canvas"),
):
    """Создает Lean Canvas под задачу пользователя. Полезно для проработки стартапов."""
    client = get_client(url=os.getenv("LANGGRAPH_API_URL", "http://0.0.0.0:2024"))
    thread = await client.threads.create()
    thread_id = thread["thread_id"]
    push_ui_message(
        "agent_execution",
        {
            "agent": "lean_canvas",
            "node": "__start__",
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
                "skip_search": False if os.getenv("TAVILY_API_KEY") else True,
            }
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
                },
            )
    file_id = str(uuid.uuid4())
    html = lean_canvas_to_html(state)
    text = lean_canvas_to_text(state)
    return {
        "text": text,
        "message": f'В результате выполнения была сгенерирована HTML страница {file_id}. Покажи её пользователю через "![HTML-страница](html:{file_id})" и напиши ответ с использованием текста lean canvas и куда двигаться пользователю дальше',
        "giga_attachments": [{"type": "text/html", "file_id": file_id, "data": html}],
    }
