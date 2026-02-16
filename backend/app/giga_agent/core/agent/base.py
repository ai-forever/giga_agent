import asyncio
import threading
from typing import Any, List, Set, Optional, TypeVar, Coroutine, cast

from giga_agent.core.agent.core_middleware import (
    CoreFirstMiddleware,
    CoreLastMiddleware,
)
from typing_extensions import override

from fastapi import FastAPI
from pydantic import Field, PrivateAttr, ConfigDict
from langchain_core.load.serializable import Serializable

from giga_agent.core.agent.prompt import BASE_PROMPT
from giga_agent.core.module import BaseModule
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from giga_agent.models.users import UserShort
from giga_agent.sandbox.base import BaseSandbox
from giga_agent.core.agent.graph_factory import create_graph
from langgraph.graph.state import CompiledStateGraph
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.routes import llms_router, sandboxes_router, files_router, generators_router

NOTES_PROMPT = """
====

ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ

Ниже описаны инструкции пользователя. Ты ОБЯЗАН выполнять их при выполнении каждой задачи.
----
{0}
----

====
"""  # noqa: E501

_T = TypeVar("_T")


def _run_coroutine_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _runner():
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - defensive
            result["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in result:
        raise cast(Exception, result["error"])
    return cast(_T, result["value"])


class BaseAgent(Serializable):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    modules: List[BaseModule] = Field(default_factory=list)
    llm: Optional[BaseChatModel] = None
    sandbox: Optional[BaseSandbox] = None
    tools: Optional[List[BaseTool]] = None

    _app: FastAPI = PrivateAttr()
    _graph: CompiledStateGraph[AgentState, Context] = PrivateAttr()
    _module_ids: Set[str] = PrivateAttr(default_factory=set)

    @classmethod
    @override
    def is_lc_serializable(cls) -> bool:
        return True

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)

        # Ensure cache is configured for any entrypoint (CLI, tests, etc.)
        from giga_agent.core.cache import setup_cache

        setup_cache()

        self._app = FastAPI()
        self._app.state.agent = self

        # Подключаем core routes
        self._app.include_router(llms_router)
        self._app.include_router(sandboxes_router)
        self._app.include_router(files_router)
        self._app.include_router(generators_router)

        # Re-initialize modules through add_module to ensure validation and route registration
        initial_modules = self.modules
        self.modules = []

        for module in initial_modules:
            self.add_module(module)

        # Собираем middleware из модулей
        module_middlewares = _run_coroutine_sync(self._get_module_middlewares())
        all_middleware = [CoreFirstMiddleware(), *module_middlewares, CoreLastMiddleware()]

        self._graph = create_graph(self, middleware=all_middleware)
        setattr(self.graph, "giga_agent", self)

    def add_module(self, module: BaseModule):
        if module.id in self._module_ids:
            raise ValueError(
                f"Agent cannot have multiple modules with the same id: '{module.id}'"
            )

        self.modules.append(module)
        self._module_ids.add(module.id)

        # Re-setup routes or just add the new one if possible
        if hasattr(self, "_app") and module.get_api_router():
            self._app.include_router(module.get_api_router(), prefix=f"/{module.id}")

    def _setup_routes(self):
        for module in self.modules:
            router = module.get_api_router()
            if router:
                self._app.include_router(router)

    @property
    def app(self) -> FastAPI:
        return self._app

    @property
    def graph(self):
        return self._graph

    async def _get_module_middlewares(self):
        middlewares = []
        for module in self.modules:
            mw = await module.get_middleware()
            if mw is not None:
                middlewares.append(mw)
        return middlewares

    async def get_prompt(self, user: UserShort) -> str:
        modules_prompts = []
        for module in self.modules:
            instructions = await module.get_instructions(user=user, agent=self)
            if instructions:
                modules_prompts.append(instructions)
        instructions = user.settings.get("contextInstructions")
        instructions_prompt = ""
        if instructions:
            instructions_prompt = NOTES_PROMPT.format(instructions)
        return (
            BASE_PROMPT.format(modules="\n===\n\n".join(modules_prompts))
            + instructions_prompt
        )

    async def get_tools(self, user: UserShort) -> List[BaseTool]:
        all_tools = list(self.tools or [])
        for module in self.modules:
            all_tools.extend(await module.get_tools(user=user, agent=self))
        return all_tools
