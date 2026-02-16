from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableConfig

from giga_agent.agents.presentation_agent.config import PresentationState, llm
from giga_agent.agents.presentation_agent.prompts.ru import FORMAT, PLAN_PROMPT


async def plan_node(state: PresentationState, config: RunnableConfig):
    ch = PLAN_PROMPT | llm
    resp = await ch.ainvoke(
        {
            "messages": state["messages"]
            + [
                (
                    "user",
                    "Придумай план презентации исходя из переписки выше"
                    + FORMAT
                    + f"\nДополнительная информация: {state['task']}",
                ),
            ],
        },
    )

    if config["configurable"].get("print_messages", False):
        resp.pretty_print()

    json_response = await ch.ainvoke(
        {
            "messages": state["messages"]
            + [("user", "Придумай план презентации исходя из переписки выше"), resp]
            + [
                (
                    "user",
                    """Переведи план выше в формат JSON.
Объекты:
```python
class Slide:
    name: str = Field("Название слайда")
    attachments: Optional[list[str]] = Field("Список вложений из предыдущей переписки (добавляй только если подходит к слайду)")
```
Формат:
{
    "slides": [Объекты типа Slide]
}""",  # noqa: E501
                ),
            ],
        },
    )
    if config["configurable"].get("print_messages", False):
        json_response.pretty_print()
    data = JsonOutputParser().parse(json_response.content)
    return {
        "slides": data.get("slides"),
        "messages": [
            (
                "user",
                "Придумай план презентации исходя из переписки выше"
                + FORMAT
                + f"\nДополнительная информация: {state['task']}",
            ),
            resp,
        ],
    }
