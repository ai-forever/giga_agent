# Подагенты
## [Агент презентаций](backend/graph/giga_agent/agents/presentation_agent)
Создает презентации с помощью [Reveal.js](https://revealjs.com/). Генерирует слайды / изображения к ним.

Так же, имеет возможность подгружать в презентации изображения/графики из основного агента GigaAgent.

Пример работы: [переписка](/docs/examples/mortgage/landing_presentation_chat.pdf), [презентация](/docs/examples/mortgage/presentation.pdf)
## [Агент генерации подкастов](backend/graph/giga_agent/agents/podcast)
Создает подкаст на основе переписки / контента по ссылке. Использует синтез [SaluteSpeech](https://developers.sber.ru/portal/products/smartspeech).

Пример работы: [переписка](/docs/examples/mortgage_podcast/podcast_chat.pdf), [подкаст](/docs/examples/mortgage_podcast/podcast.mp3)
## [Агент Мемов](backend/graph/giga_agent/agents/meme_agent)
Создает мемы. Достаточно простой агент, можно использовать в качестве примера для создания своего.

Мемы со сберкотом, может генерить только на GigaChat API Kandinsky

Пример работы: [чат](/docs/examples/memes/chat.pdf)

![мем_1](/docs/examples/memes/meme1.jpeg)
## [Агент по созданию Lean Canvas](backend/graph/giga_agent/agents/lean_canvas)
Создает LeanCanvas — популярный инструмента для описания бизнес-модели стартапов.

Пример работы: [переписка](docs/examples/lean_canvas/lean_canvas.pdf)
## [Агент по созданию лендингов](backend/graph/giga_agent/agents/landing_agent)
Создает лендинг

Пример работы: [переписка](/docs/examples/mortgage/landing_presentation_chat.pdf)
## [Агент исследователь города](backend/graph/giga_agent/agents/gis_agent)
Интересные места + карта с помощью 2GIS

Пример работы: [переписка](/docs/examples/city_explorer/city_explorer.pdf)

---

# Как создать своего субагента

## Что такое субграф (subgraph)?

**Субграф** — это отдельный LangGraph граф, который может быть вызван из основного агента как инструмент. Это позволяет:

- **Изолировать сложную логику** — вынести многошаговый процесс в отдельный граф
- **Переиспользовать компоненты** — один субграф можно использовать в разных агентах
- **Управлять состоянием** — каждый субграф имеет свое изолированное состояние
- **Стримить результаты** — получать промежуточные результаты выполнения в реальном времени

## Когда использовать субграфы?

✅ **Используйте субграф, если:**
- Задача требует нескольких этапов обработки с промежуточными состояниями
- Нужна циклическая логика (например, итеративная обработка до достижения условия)
- Требуется отслеживать прогресс выполнения
- Логика может быть переиспользована в разных контекстах

❌ **Не используйте субграф, если:**
- Задача решается простой функцией
- Нет необходимости в управлении состоянием
- Нужен просто вызов внешнего API

## Пошаговая инструкция создания субграфа

### 1. Создайте файл с графом

Создайте файл `subgraph.py` в вашем модуле, например `agent/my_module/subgraph.py`:

```python
from typing import TypedDict, Annotated
from operator import add
from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool
from giga_agent.utils.langgraph_sdk import get_client
from langchain.tools import ToolRuntime


class GraphState(TypedDict):
    """Определите состояние вашего графа"""
    messages: Annotated[list[str], add]  # add объединяет списки из разных узлов
    counter: int
    result: str


def node_process_input(state: GraphState) -> GraphState:
    """Первый узел: обработка входных данных"""
    messages = state.get("messages", [])
    counter = state.get("counter", 0)
    
    new_message = f"Обработан ввод (итерация {counter + 1})"
    
    return {
        "messages": [new_message],
        "counter": counter + 1,
        "result": ""
    }


def node_analyze(state: GraphState) -> GraphState:
    """Второй узел: анализ данных"""
    counter = state.get("counter", 0)
    messages = state.get("messages", [])
    
    analysis = f"Анализ выполнен: обработано {len(messages)} сообщений"
    
    return {
        "messages": [analysis],
        "counter": counter,
        "result": ""
    }


def node_generate_result(state: GraphState) -> GraphState:
    """Третий узел: генерация финального результата"""
    messages = state.get("messages", [])
    counter = state.get("counter", 0)
    
    result = f"Финальный результат: {counter} итераций, сообщений: {len(messages)}"
    
    return {
        "messages": [f"Результат готов"],
        "counter": counter,
        "result": result
    }


def should_continue(state: GraphState) -> str:
    """Условная логика: определяет следующий узел"""
    counter = state.get("counter", 0)
    if counter < 3:
        return "process"  # Повторяем обработку
    return "analyze"  # Переходим к анализу


# Создание графа
workflow = StateGraph(GraphState)

# Добавление узлов
workflow.add_node("process_input", node_process_input)
workflow.add_node("analyze", node_analyze)
workflow.add_node("generate_result", node_generate_result)

# Добавление рёбер (связей между узлами)
workflow.add_edge(START, "process_input")
workflow.add_conditional_edges(
    "process_input",
    should_continue,
    {
        "process": "process_input",  # Цикл
        "analyze": "analyze"          # Выход из цикла
    }
)
workflow.add_edge("analyze", "generate_result")
workflow.add_edge("generate_result", END)

# Компиляция графа — ОБЯЗАТЕЛЬНО экспортируйте как 'graph'
graph = workflow.compile()
```

**Ключевые моменты:**

1. **Состояние** (`GraphState`) — определяет данные, передаваемые между узлами
2. **Узлы** (`node_*`) — функции, принимающие и возвращающие состояние
3. **Рёбра** — связи между узлами (обычные и условные)
4. **Аннотация с `add`** — автоматически объединяет списки из разных узлов
5. **Экспорт `graph`** — переменная должна называться именно `graph`

### 2. Создайте инструмент для вызова субграфа

В том же файле `subgraph.py` добавьте tool-функцию:

```python
@tool
async def run_example_graph(user_input: str, runtime: ToolRuntime) -> str:
    """
    Запускает пример LangGraph графа с обработкой входных данных.
    
    Args:
        user_input: Входное сообщение для обработки
        runtime: Контекст выполнения инструмента (автоматически предоставляется)
        
    Returns:
        Финальный результат выполнения графа
    """
    # Создаем клиент LangGraph SDK для вызова субграфа
    client = get_client(runtime.config)
    
    initial_state = {
        "messages": [f"Входное сообщение: {user_input}"],
        "counter": 0,
        "result": ""
    }
    
    try:
        # Создаем поток (thread) для выполнения графа
        thread = await client.threads.create()

        print(f"\n🔄 Запуск графа через стриминг...")
        print(f"Thread ID: {thread['thread_id']}\n")
        
        final_result = None
        
        # Используем стриминг для получения результатов в реальном времени
        async for chunk in client.runs.stream(
            thread_id=thread["thread_id"],
            assistant_id="example_graph",  # ID графа из get_subgraphs
            input=initial_state,
            stream_mode="values"  # Стримим значения состояния
        ):
            if chunk.event != "values":
                continue
            
            chunk_data = chunk.data
            if isinstance(chunk_data, dict):
                counter = chunk_data.get("counter", 0)
                messages_count = len(chunk_data.get("messages", []))
                result = chunk_data.get("result", "")

                print(f"📊 Состояние: counter={counter}, messages={messages_count}")
                if result:
                    print(f"✅ Результат: {result}")
            
                final_result = chunk_data.get("result", "")

        print(f"\n✨ Выполнение завершено\n")
        
        return final_result if final_result else "Результат не получен"
        
    except Exception as e:
        # Fallback на прямой вызов при ошибке SDK
        print(f"⚠️ SDK вызов не удался: {e}")
        print(f"🔄 Используется прямой локальный вызов графа\n")
        
        final_state = graph.invoke(initial_state)
        return final_state.get("result", "Результат не получен")
```

**Важные детали:**

- `runtime: ToolRuntime` — автоматически передается библиотекой, содержит конфигурацию
- `get_client(runtime.config)` — создает клиент для вызова субграфов
- `assistant_id` — должен совпадать с ключом в `get_subgraphs()`
- `stream_mode="values"` — стримит полные состояния после каждого узла
- Fallback на `graph.invoke()` — для локального тестирования без SDK

### 3. Создайте модуль с регистрацией субграфа

Создайте файл `module.py`:

```python
from __future__ import annotations

from typing import List

from giga_agent.core.module import BaseModule
from giga_agent.models import UserShort
from langchain_core.tools import BaseTool

from .subgraph import graph, run_example_graph


class MySubgraphModule(BaseModule):
    id: str = 'my_subgraph'

    def get_subgraphs(self) -> dict[str, str]:
        """
        Регистрация подграфов модуля.
        
        Returns:
            Словарь {ID_графа: "путь.к.модулю:переменная"}
        """
        return {
            "example_graph": "agent.my_module.subgraph:graph"
        }
    
    async def get_tools(
        self,
        user: UserShort | None,
        agent: "BaseAgent",
    ) -> List[BaseTool]:
        """Предоставление инструмента для вызова субграфа"""
        return [run_example_graph]
```

**Ключевые моменты:**

- `get_subgraphs()` — регистрирует субграфы модуля
- Формат значения: `"путь.к.модулю:переменная_графа"`
- ID графа (`example_graph`) должен совпадать с `assistant_id` в tool-функции
- `get_tools()` возвращает инструмент для вызова субграфа

### 4. Зарегистрируйте модуль в агенте

В файле `agent.py`:

```python
from giga_agent.agents.giga_agent import GigaAgent

from .my_module.module import MySubgraphModule

agent = GigaAgent(modules=[MySubgraphModule()])

graph, app = agent.graph, agent.app
```

### 5. Добавьте зависимости

В `pyproject.toml` убедитесь, что добавлены необходимые зависимости:

```toml
[project]
name = "my_agent"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "giga-agent",
    "langgraph-sdk>=0.3.11"  # Для работы с субграфами
]
```

## Структура проекта

```
my_agent/
├── agent/
│   ├── __init__.py
│   ├── agent.py                    # Определение агента
│   └── my_module/
│       ├── __init__.py
│       ├── module.py               # Модуль с get_subgraphs()
│       └── subgraph.py             # Граф + tool для вызова
├── pyproject.toml
└── README.md
```

## Запуск и тестирование

```bash
# Установите зависимости
uv sync

# Запустите агента в режиме разработки
uv run giga_agent dev agent.agent:graph:app

# Агент будет доступен на http://localhost:8123
```

Теперь основной агент может вызвать ваш субграф через инструмент `run_example_graph`.

## Полный пример

Смотрите рабочий пример в [`examples/agent_with_subgraph/`](examples/agent_with_subgraph/):

```
examples/agent_with_subgraph/
├── agent/
│   ├── agent.py
│   └── with_subgraph/
│       ├── module.py               # Регистрация субграфа
│       └── subgraph.py             # Граф с циклической логикой
└── pyproject.toml
```
