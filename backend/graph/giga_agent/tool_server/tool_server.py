import traceback
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse
from langchain_gigachat.utils.function_calling import convert_to_gigachat_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt.tool_node import ToolNode, _handle_tool_error
from langgraph_sdk.client import get_client
from pydantic_core import ValidationError

from giga_agent.config import AGENT_MAP, MCP_CONFIG, REPL_TOOLS, TOOLS
from giga_agent.settings import settings
from giga_agent.tool_server.utils import transform_schema

tool_map = {}
repl_tool_map = {}
config = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = MultiServerMCPClient(MCP_CONFIG)
    # mcp_tools = [transform_tool(tool) for tool in await client.get_tools()] dsfdsfdsfdsfsdf
    mcp_tools = await client.get_tools()
    for mcp_tool in mcp_tools:
        mcp_tool.name = mcp_tool.name.replace("-", "_")
        if isinstance(mcp_tool.args_schema, dict):
            mcp_tool.args_schema = transform_schema(mcp_tool.args_schema)
    tools = TOOLS + mcp_tools
    config["tool_node"] = ToolNode(tools=tools)
    for tool in tools:
        tool_map[tool.name] = tool
    for tool in REPL_TOOLS:
        repl_tool_map[tool.__name__] = tool
    yield
    repl_tool_map.clear()
    tool_map.clear()
    config.clear()


app = FastAPI(lifespan=lifespan)
langgraph_client = get_client(url=settings.internal.langgraph_api_url)


@app.post("/{tool_name}")
async def call_tool(tool_name: str, payload: dict = Body(...)):
    if tool_name in tool_map or tool_name in repl_tool_map:
        if tool_name in AGENT_MAP:
            return JSONResponse(
                status_code=500,
                content=f"Ты пытался вызвать '{tool_name}'. "
                f"Нельзя вызывать '{tool_name}' из кода! Вызывай их через function_call",  # noqa: E501
            )
        try:
            if tool_name in repl_tool_map:
                kwargs = payload.get("kwargs")
                return JSONResponse({"data": await repl_tool_map[tool_name](**kwargs)})
            tool = tool_map[tool_name]
            kwargs = payload.get("kwargs")
            thread_id = payload.get("thread_id")
            checkpoint_id = payload.get("checkpoint_id")
            state = (
                await langgraph_client.threads.get_state(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                )
            )["values"]
            injected_args = config["tool_node"].inject_tool_args(
                {"name": tool.name, "args": kwargs, "id": "123"},
                state,
                None,
            )["args"]
            if tool.name == "python":
                injected_args["code"] = kwargs.get("code")
            try:
                tool._to_args_and_kwargs(injected_args, None)
            except ValidationError as e:
                content = _handle_tool_error(e, flag=True)
                tool_schema = convert_to_gigachat_tool(tool)["function"]
                return JSONResponse(
                    status_code=500,
                    content=f"Ошибка в заполнении функции!\n{content}\n"
                    f"Заполни параметры функции по следующей схеме: {tool_schema}",
                )
            graph_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                },
            }
            data = await tool_map[tool_name].ainvoke(injected_args, config=graph_config)
            return {"data": data}
        except Exception as e:
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content=_handle_tool_error(e, flag=True),
            )
    else:
        return JSONResponse(
            status_code=404,
            content=f"Tool with name {tool_name} not found!",
        )


@app.get("/tools")
async def get_tools():
    tools = []
    for tool in tool_map.values():
        tools.append(convert_to_gigachat_tool(tool)["function"])
    return tools
