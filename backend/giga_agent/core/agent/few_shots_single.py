"""Few-shot examples with strictly single-tool turns.

Demonstrates iterative thinking and error recovery without file operations.
Each AI message contains exactly one tool call.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# user -> think -> think -> ответ (чистое рассуждение без инструментов)
PURE_THINKING_EXAMPLE_SINGLE = [
    HumanMessage(
        content="[Пример взаимодействия — демонстрация итеративного размышления]\n"
        "В комнате 3 выключателя, каждый управляет одной из 3 лампочек в соседней комнате. "
        "Зайти в соседнюю комнату можно только один раз. Как определить, какой выключатель к какой лампочке относится?",
        name="example_user",
    ),
    # 1. think — первичный анализ
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_pt_think_1",
                "name": "think",
                "args": {
                    "thought": (
                        "Классическая логическая задача. Ключевое ограничение: зайти в комнату можно только один раз, "
                        "значит визуально я могу проверить состояние лампочек лишь однажды.\n"
                        "Если бы я мог только включать/выключать — я бы различил максимум 2 состояния (вкл/выкл), "
                        "а лампочек 3. Значит нужен ещё один канал информации.\n"
                        "Какие свойства лампочки, кроме «горит/не горит», можно наблюдать? "
                        "Лампа накаливания нагревается, если была включена. "
                        "Это даёт третье состояние: «не горит, но тёплая».\n"
                        "Нужно продумать точную последовательность действий."
                    )
                },
            }
        ],
    ),
    ToolMessage(content="", tool_call_id="ex_pt_think_1"),
    # 2. think — углублённое рассуждение, построение решения
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_pt_think_2",
                "name": "think",
                "args": {
                    "thought": (
                        "Итого три различимых состояния лампочки:\n"
                        "- Горит → была включена в момент проверки\n"
                        "- Не горит, тёплая → была включена, потом выключена\n"
                        "- Не горит, холодная → никогда не включалась\n\n"
                        "Алгоритм:\n"
                        "1. Включить выключатель №1, подождать несколько минут\n"
                        "2. Выключить №1, включить №2\n"
                        "3. Зайти в комнату и проверить:\n"
                        "   - Лампочка горит → выключатель №2\n"
                        "   - Лампочка не горит, но тёплая → выключатель №1\n"
                        "   - Лампочка не горит и холодная → выключатель №3\n\n"
                        "Решение полное, корректно покрывает все 3 лампочки. Можно отвечать."
                    )
                },
            }
        ],
    ),
    ToolMessage(content="", tool_call_id="ex_pt_think_2"),
    # 3. Финальный ответ
    AIMessage(
        content=(
            "Используем то, что лампочка нагревается при работе:\n\n"
            "1. Включите выключатель **№1** и подождите 3–5 минут\n"
            "2. Выключите **№1**, включите **№2**\n"
            "3. Зайдите в комнату:\n"
            "   - Лампочка **горит** → выключатель **№2**\n"
            "   - Лампочка **не горит, но тёплая** на ощупь → выключатель **№1**\n"
            "   - Лампочка **не горит и холодная** → выключатель **№3**"
        ),
        name="example_assistant",
    ),
]


# user -> think -> python (ошибка) -> think -> исправленный python -> ответ
ITERATIVE_THINKING_EXAMPLE_SINGLE = [
    HumanMessage(
        content="[Пример взаимодействия — демонстрация итеративного размышления и исправления ошибок]\n"
        "Сколько существует способов рассадить 8 гостей за круглый стол, "
        "если двое конкретных гостей не должны сидеть рядом?",
        name="example_user",
    ),
    # 1. think — первичный анализ и план
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_s_think_1",
                "name": "think",
                "args": {
                    "thought": (
                        "Задача: круговые перестановки 8 человек с ограничением — "
                        "двое (A и B) не сидят рядом.\n"
                        "План:\n"
                        "1. Вспомнить формулу круговых перестановок: (n-1)!\n"
                        "2. Посчитать общее число — (8-1)! = 7!\n"
                        "3. Вычесть случаи, когда A и B рядом: склеиваем их в один элемент, "
                        "получаем (7-1)! = 6! круговых перестановок, × 2 (A-B и B-A)\n"
                        "4. Итого: 7! - 2·6!\n"
                        "Напишу код для вычисления."
                    )
                },
            }
        ],
    ),
    ToolMessage(content="", tool_call_id="ex_s_think_1"),
    # 2. python — код с ошибкой (неправильная формула)
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_s_py_1",
                "name": "python",
                "args": {
                    "code": (
                        "from math import factorial\n\n"
                        "total = factorial(8)\n"
                        "adjacent = factorial(7) * 2\n"
                        "result = total - adjacent\n"
                        "print(f'Ответ: {result}')"
                    )
                },
            }
        ],
    ),
    ToolMessage(
        content="Ответ: 30240",
        tool_call_id="ex_s_py_1",
    ),
    # 3. think — анализ результата, обнаружение ошибки
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_s_think_2",
                "name": "think",
                "args": {
                    "thought": (
                        "Стоп, результат 30240 выглядит неправильно.\n"
                        "Проверяю: я использовал factorial(8) = 8! = 40320 — это обычные перестановки, "
                        "а для круглого стола нужно (n-1)! = 7! = 5040.\n"
                        "Аналогично для случая «рядом»: склейка даёт 7 объектов по кругу = 6! = 720, × 2 = 1440.\n"
                        "Правильный ответ: 5040 - 1440 = 3600.\n"
                        "Ошибка: использовал обычные перестановки вместо круговых. Исправлю код."
                    )
                },
            }
        ],
    ),
    ToolMessage(content="", tool_call_id="ex_s_think_2"),
    # 4. python — исправленный код
    AIMessage(
        content="",
        name="example_assistant",
        tool_calls=[
            {
                "id": "ex_s_py_2",
                "name": "python",
                "args": {
                    "code": (
                        "from math import factorial\n\n"
                        "n = 8\n"
                        "total_circular = factorial(n - 1)\n"
                        "adjacent_circular = factorial(n - 2) * 2\n"
                        "result = total_circular - adjacent_circular\n"
                        "print(f'Ответ: {result}')"
                    )
                },
            }
        ],
    ),
    ToolMessage(
        content="Ответ: 3600",
        tool_call_id="ex_s_py_2",
    ),
    # 5. Финальный ответ
    AIMessage(
        content=(
            "Существует **3600** способов рассадить 8 гостей за круглый стол так, "
            "чтобы двое конкретных гостей не сидели рядом.\n\n"
            "Решение: всего круговых перестановок (8−1)! = 5040, минус случаи, "
            "когда A и B рядом: 2·(8−2)! = 1440. Итого 5040 − 1440 = 3600."
        ),
        name="example_assistant",
    ),
]


FEW_SHOT_EXAMPLES_SINGLE: list = (
    PURE_THINKING_EXAMPLE_SINGLE + ITERATIVE_THINKING_EXAMPLE_SINGLE
)
