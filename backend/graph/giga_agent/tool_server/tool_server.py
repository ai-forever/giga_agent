import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Body
from langchain_gigachat.utils.function_calling import convert_to_gigachat_tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt.tool_node import _handle_tool_error, ToolNode
from pydantic_core import ValidationError
from fastapi.responses import JSONResponse

from giga_agent.utils.env import load_project_env
from giga_agent.config import MCP_CONFIG, TOOLS, REPL_TOOLS, AGENT_MAP

tool_map = {}
repl_tool_map = {}
config = {}

load_project_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = MultiServerMCPClient(MCP_CONFIG)
    tools = TOOLS + await client.get_tools()
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


@app.post("/{tool_name}")
async def call_tool(tool_name: str, payload: dict = Body(...)):
    if tool_name in tool_map or tool_name in repl_tool_map:
        if tool_name in AGENT_MAP:
            return JSONResponse(
                status_code=500,
                content=f"Ты пытался вызвать '{tool_name}'. "
                f"Нельзя вызывать '{tool_name}' из кода! Вызывай их через function_call",
            )
        try:
            if tool_name in repl_tool_map:
                kwargs = payload.get("kwargs")
                return JSONResponse({"data": await repl_tool_map[tool_name](**kwargs)})
            tool = tool_map[tool_name]
            kwargs = payload.get("kwargs")
            state = payload.get("state")
            injected_args = config["tool_node"].inject_tool_args(
                {"name": tool.name, "args": kwargs, "id": "123"}, state, None
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
                    content=f"Ошибка в заполнении функции!\n{content}\nЗаполни параметры функции по следующей схеме: {tool_schema}",
                )
            data = await tool_map[tool_name].ainvoke(injected_args)
            return {"data": data}
        except Exception as e:
            traceback.print_exc()
            return JSONResponse(
                status_code=500, content=_handle_tool_error(e, flag=True)
            )
    else:
        return JSONResponse(
            status_code=404, content=f"Tool with name {tool_name} not found!"
        )


@app.get("/tools")
async def get_tools():
    tools = []
    for tool in tool_map.values():
        tools.append(convert_to_gigachat_tool(tool)["function"])
    return tools
