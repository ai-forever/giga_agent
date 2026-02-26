from typing import Any, Dict, List, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI
from giga_agent.conf import GIGA_PREFIX_API
from pydantic import Field, PrivateAttr, ConfigDict, BaseModel
from uuid import UUID

from giga_agent.core.agent.prompt import BASE_PROMPT
from giga_agent.core.module import BaseModule
from langchain_core.tools import BaseTool

from giga_agent.middlewares.tool_result import ToolResultMiddleware
from giga_agent.models.users import UserShort
from giga_agent.core.agent.graph_factory import create_graph
from langgraph.graph.state import CompiledStateGraph
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.routes import router as api_router

NOTES_PROMPT = """
====

ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ

Ниже описаны инструкции пользователя. Ты ОБЯЗАН выполнять их при выполнении каждой задачи.
```
{0}
```

====
"""  # noqa: E501


class BaseAgent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    modules: tuple[BaseModule, ...] = Field(default_factory=tuple)
    tools: List[BaseTool] = Field(default_factory=list)

    _app: FastAPI = PrivateAttr()
    _graph: CompiledStateGraph[AgentState, Context] = PrivateAttr()
    _module_ids: Set[str] = PrivateAttr(default_factory=set)
    _tools_cache: Dict[tuple[UUID | None, int], List[BaseTool]] = PrivateAttr(
        default_factory=dict
    )

    def get_modules(self) -> list[BaseModule]:
        return []

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "modules":
            return super().__setattr__(name, value)

        old_modules = getattr(self, "modules", None)
        super().__setattr__(name, value)

        module_ids = [m.id for m in self.modules]
        unique_ids = set(module_ids)
        if len(module_ids) != len(unique_ids):
            if old_modules is not None:
                super().__setattr__("modules", old_modules)
            for mid in module_ids:
                if module_ids.count(mid) > 1:
                    raise ValueError(
                        f"Agent cannot have multiple modules with the same id: '{mid}'"
                    )
            raise ValueError("Agent cannot have multiple modules with the same id")

        if hasattr(self, "_module_ids"):
            self._module_ids = unique_ids
        if hasattr(self, "_tools_cache"):
            self._tools_cache.clear()

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)

        # Ensure cache is configured for any entrypoint (CLI, tests, etc.)
        from giga_agent.core.cache import setup_cache

        setup_cache()

        # Ensure cached resources are closed on shutdown (dev server reload included).
        from giga_agent.vectorstores.qdrant import shutdown_qdrant_client

        @asynccontextmanager
        async def _lifespan(_app: FastAPI):
            yield
            await shutdown_qdrant_client()

        self._app = FastAPI(lifespan=_lifespan)
        self._app.state.agent = self
        api_router.prefix = GIGA_PREFIX_API

        # Подключаем core routes
        self._app.include_router(api_router)

        # Re-initialize modules through add_module to ensure validation and route registration
        default_modules = tuple(self.get_modules())
        initial_modules = (*default_modules, *self.modules)

        for module in initial_modules:
            if module.id in self._module_ids:
                raise ValueError(
                    f"Agent cannot have multiple modules with the same id: '{module.id}'"
                )

            if module.get_api_router():
                self._app.include_router(
                    module.get_api_router(), prefix=f"{GIGA_PREFIX_API}/{module.id}"
                )

        # Собираем middleware из модулей
        module_middlewares = self._get_module_middlewares()
        all_middleware = [
            ToolResultMiddleware(),
            *module_middlewares,
        ]

        self._graph = create_graph(self, middleware=all_middleware)
        setattr(self.graph, "giga_agent", self)

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

    def _get_module_middlewares(self):
        middlewares = []
        for module in self.modules:
            mw = module.get_middleware()
            if mw is not None:
                middlewares.append(mw)
        return middlewares

    async def get_prompt(self, user: UserShort) -> str:
        modules_prompts = []
        for module in self.modules:
            instructions = await module.get_instructions(user=user, agent=self)
            if instructions:
                modules_prompts.append(instructions)
        instructions = dict(user.settings or {}).get("contextInstructions")
        instructions_prompt = ""
        if instructions:
            instructions_prompt = NOTES_PROMPT.format(instructions)
        return (
            BASE_PROMPT.format(modules="\n===\n\n".join(modules_prompts))
            + instructions_prompt
        )

    async def get_tools(self, user: UserShort) -> List[BaseTool]:
        user_id = getattr(user, "id", None)
        try:
            user_fingerprint = hash(user)
        except TypeError:
            user_fingerprint = id(user)

        cache_key = (user_id, user_fingerprint)
        cached = self._tools_cache.get(cache_key)
        if cached is not None:
            return cached

        all_tools = list(self.tools)
        for module in self.modules:
            all_tools.extend(await module.get_tools(user=user, agent=self))

        self._tools_cache[cache_key] = all_tools
        return all_tools

    async def extend_task(
        self,
        user: UserShort | None,
        task: str,
        state: AgentState,
    ) -> str:
        extended_parts = []
        for module in self.modules:
            extended_task = await module.extend_task(
                user=user,
                task=task,
                state=state,
                agent=self,
            )
            if extended_task:
                extended_parts.append(extended_task)
        return "\n".join(extended_parts)
