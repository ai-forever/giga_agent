from typing import TypedDict, Annotated
from operator import add
from langgraph.graph import StateGraph, START, END
from langchain_core.tools import tool
from giga_agent.utils.langgraph_sdk import client_session
from langchain.tools import ToolRuntime


class GraphState(TypedDict):
    """Состояние графа с историей сообщений и счетчиком"""
    messages: Annotated[list[str], add]
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
    """Третий узел: генерация результата"""
    messages = state.get("messages", [])
    counter = state.get("counter", 0)
    
    result = f"Финальный результат: {counter} итераций, сообщений: {len(messages)}"
    
    return {
        "messages": [f"Результат готов"],
        "counter": counter,
        "result": result
    }


def should_continue(state: GraphState) -> str:
    """Условие продолжения: если counter < 3, повторяем обработку"""
    counter = state.get("counter", 0)
    if counter < 3:
        return "process"
    return "analyze"


# Создание графа
workflow = StateGraph(GraphState)

# Добавление узлов
workflow.add_node("process_input", node_process_input)
workflow.add_node("analyze", node_analyze)
workflow.add_node("generate_result", node_generate_result)

# Добавление ребер
workflow.add_edge(START, "process_input")
workflow.add_conditional_edges(
    "process_input",
    should_continue,
    {
        "process": "process_input",
        "analyze": "analyze"
    }
)
workflow.add_edge("analyze", "generate_result")
workflow.add_edge("generate_result", END)

# Компиляция графа
graph = workflow.compile()


@tool
async def run_example_graph(user_input: str, runtime: ToolRuntime) -> str:
    """
    Запускает пример LangGraph графа с обработкой входных данных через LangGraph SDK со стримингом.
    
    Args:
        user_input: Входное сообщение для обработки
        
    Returns:
        Финальный результат выполнения графа
    """
    initial_state = {
        "messages": [f"Входное сообщение: {user_input}"],
        "counter": 0,
        "result": ""
    }

    try:
        # Создаем клиент LangGraph SDK
        async with client_session(runtime.config) as client:
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
                # Выводим информацию о текущем состоянии
                if chunk.event != "values":
                    continue
                chunk = chunk.data
                if isinstance(chunk, dict):
                    counter = chunk.get("counter", 0)
                    messages_count = len(chunk.get("messages", []))
                    result = chunk.get("result", "")

                    print(f"📊 Состояние: counter={counter}, messages={messages_count}")
                    if result:
                        print(f"✅ Результат: {result}")

                    final_result = chunk.get("result", "")

        print(f"\n✨ Выполнение завершено\n")

        return final_result if final_result else "Результат не получен"

    except Exception as e:
        # Fallback на прямой вызов при ошибке SDK
        print(f"⚠️ SDK вызов не удался: {e}")
        print(f"🔄 Используется прямой локальный вызов графа\n")
        
        final_state = graph.invoke(initial_state)
        return final_state.get("result", "Результат не получен")

