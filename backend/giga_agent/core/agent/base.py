import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Set
from uuid import UUID

from cashews import cache
from fastapi import FastAPI
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from giga_agent.conf import (
    GIGA_AGENT_PREFIX_API,
    GIGA_AGENT_SANDBOX_IDLE_SWEEPER_ENABLED,
    GIGA_AGENT_SANDBOX_IDLE_SWEEPER_INTERVAL_SEC,
    GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_KEY,
    GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_TTL_SEC,
    GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_CONCURRENCY,
    GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_ENABLED,
    GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_INTERVAL_SEC,
    GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_KEY,
    GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_TTL_SEC,
    GIGA_AGENT_SCHEDULER_ENABLED,
    GIGA_AGENT_SCHEDULER_INTERVAL_SEC,
    GIGA_AGENT_SCHEDULER_LOCK_KEY,
    GIGA_AGENT_SCHEDULER_LOCK_TTL_SEC,
    GIGA_AGENT_SCHEDULER_MAX_CONCURRENT_RUNS,
    GIGA_AGENT_SCHEDULER_RUN_TIMEOUT_SEC,
    GIGA_AGENT_UI,
    GIGA_AGENT_UI_PREFIX,
    get_settings,
)
from giga_agent.core.agent.graph_factory import create_graph
from giga_agent.core.agent.prompt import build_base_prompt
from giga_agent.core.agent.types import AgentState, Context
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger, setup_cli_logging
from giga_agent.core.migrations import apply_migrations
from giga_agent.core.module import BaseModule
from giga_agent.core.observability.http_logging import (
    RequestLoggingContextMiddleware,
)
from giga_agent.middlewares.logging_context import LoggingContextMiddleware
from giga_agent.middlewares.repair_messages import RepairMessagesMiddleware
from giga_agent.middlewares.thread_title import ThreadTitleMiddleware
from giga_agent.middlewares.tool_result import ToolResultMiddleware
from giga_agent.models.users import UserShort
from giga_agent.routes import router as api_router
from giga_agent.runtime_config import mount_runtime_config_route
from giga_agent.sandbox.idle_sweeper import IdleSandboxSweeper
from giga_agent.sandbox.orphan_sweeper import OrphanSandboxSweeper
from giga_agent.scheduled.scheduler import ScheduledTaskScheduler

NOTES_PROMPT = """
====

{0}

====
"""  # noqa: E501

logger = get_logger(__name__)


def _disabled_module_ids(
    config: RunnableConfig | None,
    user: UserShort | None = None,
) -> set[str]:
    """Возвращает id модулей, выключенных пользователем.

    Приоритеты:
    1. Явный override из `config.configurable.disabled_modules` (CLI / API /
       ad-hoc вызов). Пустой список = намеренный override «включить всё».
    2. Персистентная настройка `user.settings.disabledModules`.
    """
    if isinstance(config, dict):
        configurable = config.get("configurable") or {}
        raw = configurable.get("disabled_modules")
        if raw is not None:
            return {str(x) for x in raw if x}
    if user is not None:
        settings = user.settings or {}
        raw = settings.get("disabledModules") or []
        return {str(x) for x in raw if x}
    return set()


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
    _agent_modules: tuple[BaseModule, ...] = PrivateAttr(default_factory=tuple)
    _idle_sandbox_sweeper: IdleSandboxSweeper | None = PrivateAttr(default=None)
    _orphan_sandbox_sweeper: OrphanSandboxSweeper | None = PrivateAttr(default=None)
    _scheduled_task_scheduler: ScheduledTaskScheduler | None = PrivateAttr(default=None)

    def get_modules(self) -> list[BaseModule]:
        return []

    def __check_for_unique_ids(self):
        module_ids = [m.id for m in self.all_modules]
        unique_ids = set(module_ids)
        if len(module_ids) != len(unique_ids):
            for mid in module_ids:
                if module_ids.count(mid) > 1:
                    raise ValueError(
                        f"Agent cannot have multiple modules with the same id: '{mid}'"
                    )
            raise ValueError("Agent cannot have multiple modules with the same id")
        return unique_ids

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "modules":
            return super().__setattr__(name, value)

        old_modules = getattr(self, "modules", None)
        super().__setattr__(name, value)

        try:
            unique_ids = self.__check_for_unique_ids()
        except ValueError as e:
            if old_modules is not None:
                super().__setattr__("modules", old_modules)
            raise e

        if hasattr(self, "_module_ids"):
            self._module_ids = unique_ids
        if hasattr(self, "_tools_cache"):
            self._tools_cache.clear()

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)

        # Ensure cache is configured for any entrypoint (CLI, tests, etc.)
        from giga_agent.core.cache import setup_cache

        setup_cache()

        @asynccontextmanager
        async def _lifespan(_app: FastAPI):
            from giga_agent.sandbox.local_jupyter.manager import (
                get_local_jupyter_server_manager,
            )

            if not (os.getenv("GIGA_AGENT_SECRET_KEY") or "").strip():
                raise Exception(
                    "GIGA_AGENT_SECRET_KEY is not set. Please set env secret key."
                )
            settings = get_settings()
            setup_cli_logging(settings.giga_agent_log_level)
            await self.run_startup_migrations()
            from giga_agent.channels.manager import get_channel_manager

            await get_channel_manager().start_all()
            await self.run_startup_hooks()
            if self._idle_sandbox_sweeper is not None:
                self._idle_sandbox_sweeper.start()
            if self._orphan_sandbox_sweeper is not None:
                self._orphan_sandbox_sweeper.start()
            if self._scheduled_task_scheduler is not None:
                await self._scheduled_task_scheduler.reset_stale()
                self._scheduled_task_scheduler.start()
            try:
                yield
            finally:
                if self._idle_sandbox_sweeper is not None:
                    await self._idle_sandbox_sweeper.stop()
                if self._orphan_sandbox_sweeper is not None:
                    await self._orphan_sandbox_sweeper.stop()
                if self._scheduled_task_scheduler is not None:
                    await self._scheduled_task_scheduler.stop()
                await get_local_jupyter_server_manager().stop()
                stack = getattr(_app.state, "_ui_resources_stack", None)
                if stack is not None:
                    stack.close()
                from giga_agent.channels.manager import get_channel_manager

                await get_channel_manager().stop_all()
                # Ensure cached resources are closed on shutdown (dev server reload included).
                from giga_agent.vectorstores.qdrant import shutdown_qdrant_client

                await shutdown_qdrant_client()
                # Close any warm MCP sessions held by the embedded pool.
                from giga_agent.modules.mcp.pool import shutdown_pool

                await shutdown_pool()

        self._app = FastAPI(lifespan=_lifespan)
        # Per-request logging context (request_id/method/path) for custom routes.
        self._app.add_middleware(RequestLoggingContextMiddleware)
        self._app.state.agent = self
        from giga_agent.sandbox.local_jupyter.manager import (
            get_local_jupyter_server_manager,
        )

        self._app.state.local_jupyter_server_manager = (
            get_local_jupyter_server_manager()
        )
        api_router.prefix = GIGA_AGENT_PREFIX_API
        mount_runtime_config_route(self._app)

        # Подключаем core routes
        self._app.include_router(api_router)

        # If UI is enabled and a UI prefix is specified, mount UI endpoints into this app.
        if GIGA_AGENT_UI and GIGA_AGENT_UI_PREFIX:
            from giga_agent.ui import mount_ui

            mount_ui(self._app)

        # Re-initialize modules through add_module to ensure validation and route registration
        default_modules = tuple(self.get_modules())
        self._agent_modules = (*default_modules, *self.modules)

        # Register the loaded agent so the integrations registry can resolve
        # providers by walking modules from request-free contexts.
        from giga_agent.core.integrations.registry import set_current_agent

        set_current_agent(self)

        for module in self._agent_modules:
            if module.id in self._module_ids:
                raise ValueError(
                    f"Agent cannot have multiple modules with the same id: '{module.id}'"
                )

            if module.get_api_router():
                self._app.include_router(
                    module.get_api_router(),
                    prefix=f"{GIGA_AGENT_PREFIX_API}/{module.id}",
                )

        # Собираем middleware из модулей
        from giga_agent.middlewares.usage_tracking import UsageTrackingMiddleware

        module_middlewares = self._get_module_middlewares()
        all_middleware = [
            # First: bind run ids into structlog contextvars so every log line
            # produced by the middlewares/nodes below is tagged with them.
            LoggingContextMiddleware(),
            RepairMessagesMiddleware(),
            ThreadTitleMiddleware(),
            ToolResultMiddleware(),
            UsageTrackingMiddleware(),
            *module_middlewares,
        ]
        if get_settings().giga_agent_metrics_enabled:
            from giga_agent.middlewares.metrics import MetricsMiddleware

            # Insert right after logging so token/tool/run metrics wrap the loop.
            all_middleware.insert(1, MetricsMiddleware())

        self._graph = create_graph(self, middleware=all_middleware)

        setattr(self.graph, "giga_agent", self)
        self.__check_for_unique_ids()
        self._idle_sandbox_sweeper = IdleSandboxSweeper(
            interval_sec=GIGA_AGENT_SANDBOX_IDLE_SWEEPER_INTERVAL_SEC,
            lock_key=GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_KEY,
            lock_ttl_sec=GIGA_AGENT_SANDBOX_IDLE_SWEEPER_LOCK_TTL_SEC,
            enabled=GIGA_AGENT_SANDBOX_IDLE_SWEEPER_ENABLED,
        )
        self._orphan_sandbox_sweeper = OrphanSandboxSweeper(
            interval_sec=GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_INTERVAL_SEC,
            lock_key=GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_KEY,
            lock_ttl_sec=GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_LOCK_TTL_SEC,
            concurrency=GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_CONCURRENCY,
            enabled=GIGA_AGENT_SANDBOX_ORPHAN_SWEEPER_ENABLED,
        )
        self._scheduled_task_scheduler = ScheduledTaskScheduler(
            interval_sec=GIGA_AGENT_SCHEDULER_INTERVAL_SEC,
            lock_key=GIGA_AGENT_SCHEDULER_LOCK_KEY,
            lock_ttl_sec=GIGA_AGENT_SCHEDULER_LOCK_TTL_SEC,
            run_timeout_sec=GIGA_AGENT_SCHEDULER_RUN_TIMEOUT_SEC,
            max_concurrent_runs=GIGA_AGENT_SCHEDULER_MAX_CONCURRENT_RUNS,
            enabled=GIGA_AGENT_SCHEDULER_ENABLED,
        )

    @property
    def app(self) -> FastAPI:
        return self._app

    @property
    def graph(self):
        return self._graph

    @property
    def all_modules(self):
        return self._agent_modules

    def _get_module_middlewares(self):
        middlewares = []
        for module in self._agent_modules:
            mw = module.get_middleware()
            if mw is not None:
                middlewares.append(mw)
        return middlewares

    async def get_prompt(
        self,
        user: UserShort,
        state: AgentState | None = None,
        config: RunnableConfig | None = None,
        channel_prompt: str = "",
        scheduled_prompt: str = "",
        *,
        enable_think: bool = True,
        enable_multi_tool_use: bool = False,
        connector_sources: "list | None" = None,
    ) -> str:
        disabled = _disabled_module_ids(config, user)
        modules_prompts = []
        for module in self._agent_modules:
            if module.label and module.id in disabled:
                continue
            instructions = await module.get_instructions(
                user=user, agent=self, state=state, config=config
            )
            if instructions:
                modules_prompts.append(instructions)
        # Несъёмный connector-дисптач: единый листинг доступных коннекторов
        # (MCP-серверы + ленивые модули). Источники вычисляются один раз в
        # amodel_node и передаются сюда, чтобы не дублировать запросы.
        if connector_sources:
            from giga_agent.core.agent.connectors.prompt import (
                build_connectors_prompt,
            )

            connectors_prompt = await build_connectors_prompt(
                connector_sources, user_id=user.id
            )
            if connectors_prompt:
                modules_prompts.append(connectors_prompt)
        if channel_prompt:
            modules_prompts.append(channel_prompt.strip())
        if scheduled_prompt:
            modules_prompts.append(scheduled_prompt.strip())
        instructions = dict(user.settings or {}).get("contextInstructions")
        instructions_prompt = ""
        if instructions:
            instructions_prompt = NOTES_PROMPT.format(instructions)
        base_prompt = await build_base_prompt(
            enable_think=enable_think,
            enable_multi_tool_use=enable_multi_tool_use,
        )
        pr = (
            base_prompt.format(modules="\n===\n\n".join(modules_prompts))
            + instructions_prompt
        )
        return (
            base_prompt.format(modules="\n===\n\n".join(modules_prompts))
            + instructions_prompt
        )

    async def get_tools(
        self, user: UserShort, *, config: RunnableConfig | None = None
    ) -> List[BaseTool]:
        user_id = getattr(user, "id", None)
        try:
            user_fingerprint = hash(user)
        except TypeError:
            user_fingerprint = id(user)

        is_channel = False
        if isinstance(config, dict):
            metadata = config.get("metadata") or {}
            is_channel = bool(metadata.get("is_channel"))
        cache_key = (user_id, user_fingerprint, is_channel)
        cached = self._tools_cache.get(cache_key)
        if cached is not None:
            return cached

        all_tools: list[BaseTool] = list(self.tools)
        for module in self._agent_modules:
            all_tools.extend(
                await module.get_tools(user=user, agent=self, config=config)
            )

        self._tools_cache[cache_key] = all_tools
        return all_tools

    async def run_startup_hooks(self):
        logger.info("Running startup hooks...")
        session_factory = await get_session_factory()
        async with session_factory() as session:
            for module in self._agent_modules:
                try:
                    await module.on_startup(session)
                except Exception as e:
                    logger.error(
                        f"Error in startup hook for {module.__class__.__name__}: {e}"
                    )
                    pass

    async def run_startup_migrations(self) -> None:
        settings = get_settings()
        if settings.giga_agent_skip_startup_migrations:
            logger.info(
                "Skipping startup migrations (GIGA_AGENT_SKIP_STARTUP_MIGRATIONS=1)."
            )
            return

        lock_key = settings.giga_agent_startup_migrations_lock_key
        lock_ttl_sec = settings.giga_agent_startup_migrations_lock_ttl_sec
        if settings.giga_agent_runtime in ("local", "cli"):
            logger.warning(
                "Startup migration lock uses in-memory cache in local runtime; "
                "it does not coordinate across multiple processes."
            )
        logger.info(
            "Running startup migrations with lock key '%s' (ttl=%ss).",
            lock_key,
            lock_ttl_sec,
        )
        async with cache.lock(
            lock_key,
            expire=lock_ttl_sec,
            wait=True,
        ):
            await asyncio.to_thread(apply_migrations, self)

    async def extend_task(
        self,
        user: UserShort | None,
        task: str,
        state: AgentState,
        config: RunnableConfig | None = None,
    ) -> str:
        disabled = _disabled_module_ids(config, user)
        extended_parts = []
        for module in self._agent_modules:
            if module.label and module.id in disabled:
                continue
            extended_task = await module.extend_task(
                user=user,
                task=task,
                state=state,
                agent=self,
                config=config,
            )
            if extended_task:
                extended_parts.append(extended_task)
        return "\n".join(extended_parts)
