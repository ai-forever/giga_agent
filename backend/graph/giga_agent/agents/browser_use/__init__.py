import json
from urllib.parse import quote

import websockets
from langchain_core.tools import tool
from langgraph.graph.ui import push_ui_message


@tool(parse_docstring=False)
async def browser_task(task: str):
    """Открывает браузер и выполняет задачу, которую ты поставишь ему.
    Может быть полезно, если нужно сделать какие-то действия на сайте.

    Args:
        task: Полный текст задачи

    """
    url = f"ws://localhost:7070/ws?task={quote(task)}"
    push_ui_message(
        "agent_execution",
        {"agent": "browser_task", "node_text": "Запускаю браузер"},
    )
    async with websockets.connect(url) as ws:
        async for message in ws:
            data = json.loads(message)

            msg_type = data.get("type")
            if msg_type == "error":
                return {"error": data.get("message")}
            if msg_type == "done":
                return {"success": data.get("success"), "message": data.get("message")}

            # Промежуточные данные шага
            push_ui_message(
                "agent_execution",
                {
                    "agent": "browser_task",
                    "node_text": data.get("action"),
                    "image": data.get("screenshot_base64"),
                },
            )
