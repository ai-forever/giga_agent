from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import (
    RunnableConfig,
    RunnableParallel,
    RunnablePassthrough,
)

from giga_agent.modules.subagents_legacy.agents.meme_agent.config import MemeState
from giga_agent.modules.subagents_legacy.agents.meme_agent.prompts.ru import (
    MEME_TEXT_PROMPT,
)
from giga_agent.modules.subagents_legacy.runtime import (
    get_current_user_from_config,
    resolve_user_llm,
)


async def text_node(state: MemeState, config: RunnableConfig):
    user = await get_current_user_from_config(config)
    llm = await resolve_user_llm(user)
    ch = (
        MEME_TEXT_PROMPT
        | llm.with_config(tags=["nostream"])
        | RunnableParallel(
            {"message": RunnablePassthrough(), "json": JsonOutputParser()}
        )
    ).with_retry()
    resp = await ch.ainvoke({"messages": state["messages"]})
    if config["configurable"].get("print_messages", False):
        resp["message"].pretty_print()
    return {"meme_idea": resp["json"], "messages": resp["message"]}
