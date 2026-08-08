"""Lazy runtime resolver with per-request caching.

Each graph node creates its own ``RuntimeResolver`` via ``create(config)``
and stores it in ``config["configurable"]["runtime_resolver"]``.
Down-stream consumers (tools, middlewares, module hooks) retrieve it with
``from_config(config)``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from langchain_core.runnables.config import RunnableConfig

from giga_agent.conf import get_settings
from giga_agent.core.db import get_session_factory
from giga_agent.models.users import UserRepository, UserShort
from giga_agent.utils.langgraph_sdk import get_user_id_from_config

CONFIG_KEY = "runtime_resolver"

_CLI_USER_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


class RuntimeResolver:
    """Lazily resolves and caches runtime dependencies for the current user."""

    __slots__ = ("_user", "_cache")

    def __init__(self, user: UserShort) -> None:
        self._user = user
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, config: RunnableConfig) -> RuntimeResolver:
        """Create a new resolver, loading the user from auth data in *config*."""
        from giga_agent.conf import get_settings

        if get_settings().giga_agent_runtime == "cli":
            return await CliRuntimeResolver.create(config)

        identity = get_user_id_from_config(config)
        if identity is None:
            raise ValueError("langgraph_auth_user.identity is missing from config")
        user_uuid = uuid.UUID(identity) if isinstance(identity, str) else identity
        factory = await get_session_factory()
        async with factory() as session:
            user = await UserRepository.get_cached_or_db(user_uuid, session=session)
        if user is None:
            raise ValueError(f"User {user_uuid} not found")
        return cls(user)

    @classmethod
    def from_config(cls, config: RunnableConfig) -> RuntimeResolver:
        """Extract an already-created resolver from *config*.

        Raises ``ValueError`` if the resolver has not been injected.
        """
        configurable = config.get("configurable") or {}
        existing = configurable.get(CONFIG_KEY)
        if existing is not None:
            return existing
        raise ValueError(
            "RuntimeResolver not found in config. "
            "Ensure the resolver was created in the owning node."
        )

    def inject(self, config: RunnableConfig) -> None:
        """Store this resolver into *config* so child configs inherit it."""
        configurable = config.get("configurable")
        if configurable is None:
            config["configurable"] = {CONFIG_KEY: self}  # type: ignore[typeddict-unknown-key]
        else:
            configurable[CONFIG_KEY] = self  # type: ignore[literal-required]

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _attach_rate_limiter(
        self,
        runtime: Any,
        resource_type: str,
        resource_id: uuid.UUID,
        session,
    ) -> None:
        """Build and attach a per-(resource, user) rate limiter, if one is configured."""
        from giga_agent.core.rate_limit import build_runtime_rate_limiter

        limiter = await build_runtime_rate_limiter(
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=self._user.id,
            session=session,
        )
        if limiter is not None:
            runtime.attach_rate_limiter(limiter)

    # ------------------------------------------------------------------
    # User
    # ------------------------------------------------------------------

    @property
    def user(self) -> UserShort:
        return self._user

    # ------------------------------------------------------------------
    # Availability checks (has_*)
    # ------------------------------------------------------------------

    @property
    def has_llm(self) -> bool:
        return self._user.llm_id is not None

    @property
    def has_fast_llm(self) -> bool:
        return (self._user.fast_llm_id or self._user.llm_id) is not None

    @property
    def has_embedding(self) -> bool:
        return self._user.embedding_id is not None

    @property
    def has_sandbox(self) -> bool:
        return self._user.sandbox_provider_id is not None

    @property
    def has_search_engine(self) -> bool:
        return self._user.search_engine_id is not None

    @property
    def has_image_generator(self) -> bool:
        return self._user.image_generator_id is not None

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    async def get_llm_runtime(self):
        """Resolve the user's primary LLM runtime (``user.llm_id``), cached."""
        from giga_agent.llm.base import BaseLLMRuntime
        from giga_agent.llm.manager import LLMManager

        cached: BaseLLMRuntime | None = self._cache.get("llm")
        if cached is not None:
            return cached
        llm_id = self._user.llm_id
        if llm_id is None:
            raise ValueError("User has no llm_id configured")
        factory = await get_session_factory()
        async with factory() as session:
            runtime = await LLMManager.resolve_by_id(llm_id, session=session)
            await self._attach_rate_limiter(runtime, "llm", llm_id, session)
        self._cache["llm"] = runtime
        return runtime

    async def get_fast_llm_runtime(self):
        """Resolve fast LLM (``fast_llm_id`` falling back to ``llm_id``), cached."""
        from giga_agent.llm.base import BaseLLMRuntime
        from giga_agent.llm.manager import LLMManager

        cached: BaseLLMRuntime | None = self._cache.get("fast_llm")
        if cached is not None:
            return cached
        llm_id = self._user.fast_llm_id or self._user.llm_id
        if llm_id is None:
            raise ValueError("User has no fast_llm_id or llm_id configured")
        factory = await get_session_factory()
        async with factory() as session:
            runtime = await LLMManager.resolve_by_id(llm_id, session=session)
            await self._attach_rate_limiter(runtime, "llm", llm_id, session)
        self._cache["fast_llm"] = runtime
        return runtime

    async def get_fast_llm_parallel_calls(self) -> int:
        """Resolve fast LLM parallelism (``fast_llm_id`` falling back to ``llm_id``)."""
        from giga_agent.models.llm import LLMRepository

        cached: int | None = self._cache.get("fast_llm_parallel_calls")
        if cached is not None:
            return cached
        llm_id = self._user.fast_llm_id or self._user.llm_id
        if llm_id is None:
            raise ValueError("User has no fast_llm_id or llm_id configured")
        factory = await get_session_factory()
        async with factory() as session:
            llm = await LLMRepository.get_cached_or_db(llm_id, session=session)
        parallel_calls = max(1, int(llm.parallel_calls)) if llm is not None else 1
        self._cache["fast_llm_parallel_calls"] = parallel_calls
        return parallel_calls

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def get_embedding_runtime(self):
        """Resolve the user's embedding runtime (``user.embedding_id``), cached."""
        from giga_agent.embeddings.base import BaseEmbeddingRuntime
        from giga_agent.embeddings.manager import EmbeddingManager

        cached: BaseEmbeddingRuntime | None = self._cache.get("embedding")
        if cached is not None:
            return cached
        embedding_id = self._user.embedding_id
        if embedding_id is None:
            raise ValueError("User has no embedding_id configured")
        factory = await get_session_factory()
        async with factory() as session:
            runtime = await EmbeddingManager.resolve_by_id(
                embedding_id, session=session
            )
            await self._attach_rate_limiter(runtime, "embedding", embedding_id, session)
        self._cache["embedding"] = runtime
        return runtime

    # ------------------------------------------------------------------
    # Image generator
    # ------------------------------------------------------------------

    async def get_image_generator(self):
        """Resolve the user's image generator (``user.image_generator_id``), cached."""
        from giga_agent.generators.image.base import BaseImageGenerator
        from giga_agent.generators.image.manager import ImageGeneratorManager

        cached: BaseImageGenerator | None = self._cache.get("image_generator")
        if cached is not None:
            return cached
        gen_id = self._user.image_generator_id
        if gen_id is None:
            raise ValueError("User has no image_generator_id configured")
        factory = await get_session_factory()
        async with factory() as session:
            runtime = await ImageGeneratorManager.resolve_by_id(gen_id, session=session)
            await self._attach_rate_limiter(runtime, "image_generator", gen_id, session)
        self._cache["image_generator"] = runtime
        return runtime

    # ------------------------------------------------------------------
    # Search engine
    # ------------------------------------------------------------------

    async def get_search_engine(self):
        """Resolve the user's search engine (``user.search_engine_id``), cached."""
        from giga_agent.search_engines.base import BaseSearchEngine
        from giga_agent.search_engines.manager import SearchEngineManager

        cached: BaseSearchEngine | None = self._cache.get("search_engine")
        if cached is not None:
            return cached
        engine_id = self._user.search_engine_id
        if engine_id is None:
            raise ValueError("User has no search_engine_id configured")
        factory = await get_session_factory()
        async with factory() as session:
            runtime = await SearchEngineManager.resolve_by_id(
                engine_id, session=session
            )
            await self._attach_rate_limiter(
                runtime, "search_engine", engine_id, session
            )
        self._cache["search_engine"] = runtime
        return runtime

    # ------------------------------------------------------------------
    # Sandbox
    # ------------------------------------------------------------------

    async def get_sandbox(self):
        """Resolve the user's sandbox (``SandboxManager.get_cached_or_db``), cached."""
        from giga_agent.sandbox.manager.facade import SandboxManager
        from giga_agent.sandbox.manager.types import SandboxResolved

        cached: SandboxResolved | None = self._cache.get("sandbox")
        if cached is not None:
            return cached
        factory = await get_session_factory()
        async with factory() as session:
            resolved = await SandboxManager.get_cached_or_db(
                user_id=self._user.id,
                session=session,
            )
        self._cache["sandbox"] = resolved
        return resolved


class CliRuntimeResolver(RuntimeResolver):
    """Runtime resolver for CLI mode — loads runtimes from giga_agent.conf.json."""

    __slots__ = ("_user", "_cache", "_conf")

    def __init__(self, user: UserShort, conf) -> None:
        super().__init__(user)
        self._conf = conf

    @classmethod
    async def create(cls, config: RunnableConfig) -> CliRuntimeResolver:
        from giga_agent.core.agent.cli_conf import CliRuntimeConf, load_cli_conf

        conf: CliRuntimeConf = load_cli_conf()
        user = UserShort(
            id=_CLI_USER_UUID,
            email="cli@giga-agent.local.dev",
            is_active=True,
            is_superuser=True,
            is_synthetic=True,
            settings=conf.user_settings or None,
        )
        return cls(user, conf)

    # ------------------------------------------------------------------
    # Availability checks (override — check conf.json)
    # ------------------------------------------------------------------

    @property
    def has_llm(self) -> bool:
        return self._conf.llm is not None

    @property
    def has_fast_llm(self) -> bool:
        return (self._conf.fast_llm or self._conf.llm) is not None

    @property
    def has_embedding(self) -> bool:
        return self._conf.embedding is not None

    @property
    def has_sandbox(self) -> bool:
        return True

    @property
    def has_search_engine(self) -> bool:
        return self._conf.search_engine is not None

    @property
    def has_image_generator(self) -> bool:
        return self._conf.image_generator is not None

    # ------------------------------------------------------------------
    # LLM (from conf.json, no DB)
    # ------------------------------------------------------------------

    async def get_llm_runtime(self):
        from giga_agent.llm.base import BaseLLMRuntime

        cached: BaseLLMRuntime | None = self._cache.get("llm")
        if cached is not None:
            return cached
        conf_llm = self._conf.llm
        if conf_llm is None:
            raise ValueError("No llm configured in giga_agent.conf.json")
        runtime = await self._build_llm_runtime(conf_llm)
        self._cache["llm"] = runtime
        return runtime

    async def get_fast_llm_runtime(self):
        from giga_agent.llm.base import BaseLLMRuntime

        cached: BaseLLMRuntime | None = self._cache.get("fast_llm")
        if cached is not None:
            return cached
        conf_llm = self._conf.fast_llm or self._conf.llm
        if conf_llm is None:
            raise ValueError("No fast_llm or llm configured in giga_agent.conf.json")
        runtime = await self._build_llm_runtime(conf_llm)
        self._cache["fast_llm"] = runtime
        return runtime

    async def get_fast_llm_parallel_calls(self) -> int:
        cached: int | None = self._cache.get("fast_llm_parallel_calls")
        if cached is not None:
            return cached
        conf_llm = self._conf.fast_llm or self._conf.llm
        if conf_llm is None:
            raise ValueError("No fast_llm or llm configured in giga_agent.conf.json")
        parallel_calls = max(3, int(conf_llm.settings.get("parallel_calls", 3)))
        self._cache["fast_llm_parallel_calls"] = parallel_calls
        return parallel_calls

    @staticmethod
    async def _build_llm_runtime(conf_llm):
        import giga_agent.connectors  # noqa: F401
        import giga_agent.llm  # noqa: F401
        from giga_agent.connectors.registry import ConnectorRegistry
        from giga_agent.llm.registry import LLMRegistry

        connector_runtime = await ConnectorRegistry.get_runtime(
            conf_llm.connector.type,
            conf_llm.connector.settings,
        )
        runtime_cls = LLMRegistry.get(conf_llm.type)
        validated_settings = await runtime_cls.validate_settings(conf_llm.settings)
        return runtime_cls(
            connector=connector_runtime,
            model_id=conf_llm.model_id,
            context_window=conf_llm.context_window,
            **validated_settings,
        )

    # ------------------------------------------------------------------
    # Embeddings (from conf.json, no DB)
    # ------------------------------------------------------------------

    async def get_embedding_runtime(self):
        from giga_agent.embeddings.base import BaseEmbeddingRuntime

        cached: BaseEmbeddingRuntime | None = self._cache.get("embedding")
        if cached is not None:
            return cached
        conf_emb = self._conf.embedding
        if conf_emb is None:
            raise ValueError("No embedding configured in giga_agent.conf.json")

        import giga_agent.connectors  # noqa: F401
        import giga_agent.embeddings  # noqa: F401
        from giga_agent.connectors.registry import ConnectorRegistry
        from giga_agent.embeddings.registry import EmbeddingRegistry

        connector_runtime = await ConnectorRegistry.get_runtime(
            conf_emb.connector.type,
            conf_emb.connector.settings,
        )
        runtime_cls = EmbeddingRegistry.get(conf_emb.type)
        validated_settings = await runtime_cls.validate_settings(conf_emb.settings)
        runtime = runtime_cls(
            connector=connector_runtime,
            model_id=conf_emb.model_id,
            vector_size=conf_emb.vector_size,
            **validated_settings,
        )
        self._cache["embedding"] = runtime
        return runtime

    # ------------------------------------------------------------------
    # Image generator (from conf.json, no DB)
    # ------------------------------------------------------------------

    async def get_image_generator(self):
        from giga_agent.generators.image.base import BaseImageGenerator

        cached: BaseImageGenerator | None = self._cache.get("image_generator")
        if cached is not None:
            return cached
        conf_gen = self._conf.image_generator
        if conf_gen is None:
            raise ValueError("No image_generator configured in giga_agent.conf.json")

        import giga_agent.connectors  # noqa: F401
        import giga_agent.generators.image  # noqa: F401
        from giga_agent.connectors.registry import ConnectorRegistry
        from giga_agent.generators.image.registry import ImageGeneratorRegistry

        connector_runtime = await ConnectorRegistry.get_runtime(
            conf_gen.connector.type,
            conf_gen.connector.settings,
        )
        runtime_cls = ImageGeneratorRegistry.get(conf_gen.type)
        generator = runtime_cls(
            **conf_gen.settings,
            connector=connector_runtime,
        )
        await generator.init()
        self._cache["image_generator"] = generator
        return generator

    # ------------------------------------------------------------------
    # Search engine (from conf.json, no DB)
    # ------------------------------------------------------------------

    async def get_search_engine(self):
        from giga_agent.search_engines.base import BaseSearchEngine

        cached: BaseSearchEngine | None = self._cache.get("search_engine")
        if cached is not None:
            return cached
        conf_se = self._conf.search_engine
        if conf_se is None:
            raise ValueError("No search_engine configured in giga_agent.conf.json")

        import giga_agent.connectors  # noqa: F401
        import giga_agent.search_engines  # noqa: F401
        from giga_agent.connectors.registry import ConnectorRegistry
        from giga_agent.search_engines.registry import SearchEngineRegistry

        connector_runtime = await ConnectorRegistry.get_runtime(
            conf_se.connector.type,
            conf_se.connector.settings,
        )
        runtime_cls = SearchEngineRegistry.get(conf_se.type)
        engine = runtime_cls(**conf_se.settings, connector=connector_runtime)
        await engine.init()
        self._cache["search_engine"] = engine
        return engine

    # ------------------------------------------------------------------
    # Sandbox (local_jupyter from conf.json, no DB)
    # ------------------------------------------------------------------

    async def get_sandbox(self):
        from giga_agent.models.sandbox import SandboxProviderSnapshot, SandboxSnapshot
        from giga_agent.sandbox.manager.types import SandboxResolved

        cached: SandboxResolved | None = self._cache.get("sandbox")
        if cached is not None:
            return cached

        provider_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        sandbox_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

        settings = get_settings()
        provider_settings = {}
        cli_cwd_raw = (settings.giga_agent_cli_cwd or "").strip()
        if self._conf.sandbox in {"local_jupyter", "local_jupyter_sandbox"}:
            if not settings.giga_agent_cli_no_sandbox:
                provider_settings["safe_execution"] = True
                if cli_cwd_raw:
                    cli_cwd = str(Path(cli_cwd_raw).expanduser().resolve())
                    provider_settings["default_cwd"] = cli_cwd
                    provider_settings["write_dirs"] = [cli_cwd]
            elif cli_cwd_raw:
                provider_settings["safe_execution"] = False
                provider_settings["default_cwd"] = str(
                    Path(cli_cwd_raw).expanduser().resolve()
                )
            else:
                provider_settings["safe_execution"] = False
        provider = SandboxProviderSnapshot(
            id=provider_id,
            owner_id=_CLI_USER_UUID,
            type=self._conf.sandbox,
            name=f"cli_{self._conf.sandbox}",
            settings=provider_settings,
            idle_timeout=3600,
            is_active=True,
        )
        sandbox = SandboxSnapshot(
            id=sandbox_id,
            owner_id=_CLI_USER_UUID,
            provider_id=provider_id,
            status="pending",
            settings={},
        )
        resolved = SandboxResolved(provider=provider, sandbox=sandbox)
        self._cache["sandbox"] = resolved
        return resolved
