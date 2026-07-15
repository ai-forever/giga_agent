"""Few-shot examples demonstrating autonomous agent behavior.

Examples are inserted at the beginning of the message history so the model
sees ideal interaction patterns before the real conversation.
Each example is a list of messages (HumanMessage → AIMessage with tool_calls →
ToolMessage → AIMessage) that showcases a specific autonomous behavior.

All messages use name="example_..." to signal the LLM that these are
demonstration patterns, NOT real conversation history with real files.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


AUTONOMOUS_CHAIN_EXAMPLE = [
    HumanMessage(
        content="[Пример взаимодействия — демонстрация автономной цепочки действий]\n"
        "Проанализируй данные из файла и построй график",
        name="example_user",
    ),
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_think_1",
                "name": "think",
                "args": {
                    "thought": (
                        "Задача: прочитать файл, проанализировать данные, построить график.\n"
                        "План:\n"
                        "1. Прочитать файл\n"
                        "2. Проанализировать структуру и содержимое\n"
                        "3. Построить подходящий график\n"
                        "4. Сохранить результат"
                    )
                },
            },
            {
                "id": "ex_read_1",
                "name": "read_file",
                "args": {"path": "<путь к файлу пользователя>"},
            },
        ],
    ),
    ToolMessage(
        content="Задача: прочитать файл, проанализировать данные, построить график.\n"
        "План:\n"
        "1. Прочитать файл\n"
        "2. Проанализировать структуру и содержимое\n"
        "3. Построить подходящий график\n"
        "4. Сохранить результат",
        tool_call_id="ex_think_1",
    ),
    ToolMessage(
        content="date,value\n2024-01-01,100\n2024-02-01,150\n2024-03-01,130\n...",
        tool_call_id="ex_read_1",
    ),
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_think_2",
                "name": "think",
                "args": {
                    "thought": (
                        "Файл — CSV с двумя колонками: date и value. "
                        "Построю линейный график изменения value по дате."
                    )
                },
            },
            {
                "id": "ex_python_1",
                "name": "python",
                "args": {
                    "code": (
                        "import pandas as pd\n"
                        "import plotly.express as px\n\n"
                        "df = pd.read_csv('<путь к файлу>', parse_dates=['date'])\n"
                        "fig = px.line(df, x='date', y='value', title='Динамика value')\n"
                        "fig.show()\n"
                        "print('График построен')"
                    )
                },
            },
        ],
    ),
    ToolMessage(
        content="Файл — CSV с двумя колонками: date и value. "
        "Построю линейный график изменения value по дате.",
        tool_call_id="ex_think_2",
    ),
    ToolMessage(
        content="График построен",
        tool_call_id="ex_python_1",
    ),
    AIMessage(
        content=(
            "Данные содержат временной ряд с колонками `date` и `value` "
            "(3 записи). Построил линейный график динамики."
        ),
        name="example_assistant",
    ),
]

ERROR_RECOVERY_EXAMPLE = [
    HumanMessage(
        content="[Пример взаимодействия — демонстрация обработки ошибок]\n"
        "Установи pandas и посчитай среднее из файла",
        name="example_user",
    ),
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_think_3",
                "name": "think",
                "args": {
                    "thought": (
                        "План:\n"
                        "1. Попробовать прочитать файл и посчитать среднее через python\n"
                        "2. Если pandas не установлен — установить и повторить"
                    )
                },
            },
            {
                "id": "ex_python_2",
                "name": "python",
                "args": {
                    "code": (
                        "import pandas as pd\n"
                        "df = pd.read_csv('<путь к файлу>')\n"
                        "print(df.mean())"
                    )
                },
            },
        ],
    ),
    ToolMessage(
        content="План:\n"
        "1. Попробовать прочитать файл и посчитать среднее через python\n"
        "2. Если pandas не установлен — установить и повторить",
        tool_call_id="ex_think_3",
    ),
    ToolMessage(
        content="ModuleNotFoundError: No module named 'pandas'",
        tool_call_id="ex_python_2",
    ),
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_think_4",
                "name": "think",
                "args": {
                    "thought": "pandas не установлен. Установлю через pip и повторю вычисление."
                },
            },
            {
                "id": "ex_shell_1",
                "name": "shell",
                "args": {"command": "pip install pandas"},
            },
        ],
    ),
    ToolMessage(
        content="pandas не установлен. Установлю через pip и повторю вычисление.",
        tool_call_id="ex_think_4",
    ),
    ToolMessage(
        content="Successfully installed pandas-2.2.0",
        tool_call_id="ex_shell_1",
    ),
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_python_3",
                "name": "python",
                "args": {
                    "code": (
                        "import pandas as pd\n"
                        "df = pd.read_csv('<путь к файлу>')\n"
                        "print(df.mean())"
                    )
                },
            }
        ],
    ),
    ToolMessage(
        content="value    42.5\ndtype: float64",
        tool_call_id="ex_python_3",
    ),
    AIMessage(
        content="Среднее значение по колонке `value`: **42.5**.",
        name="example_assistant",
    ),
]


FEW_SHOT_EXAMPLES: list = AUTONOMOUS_CHAIN_EXAMPLE + ERROR_RECOVERY_EXAMPLE
