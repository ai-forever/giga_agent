from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)

from giga_agent.agents.meme_agent.config import MemeState, llm
from giga_agent.agents.meme_agent.prompts.ru import MEME_TEXT_PROMPT

ch = (
    MEME_TEXT_PROMPT
    | llm
    | RunnableParallel({"message": RunnablePassthrough(), "json": JsonOutputParser()})
).with_retry()


async def text_node(state: MemeState, config: RunnableConfig):
    resp = await ch.ainvoke({"messages": state["messages"]})
    if config["configurable"].get("print_messages", False):
        resp["message"].pretty_print()
    return {"meme_idea": resp["json"], "messages": resp["message"]}
