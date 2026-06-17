import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.conf import get_settings
from giga_agent.core.logging import get_logger
from giga_agent.models.sandbox import (
    SandboxProvider,
    SandboxRepository,
    SandboxProviderRepository,
    SandboxProviderSnapshot,
)
from giga_agent.models.users import UserRepository
from giga_agent.sandbox.manager.errors import ProviderNotFoundError
from giga_agent.sandbox.manager.types import SandboxResolved

logger = get_logger(__name__)


def _is_cli_runtime() -> bool:
    return get_settings().giga_agent_runtime == "cli"


async def _resolve_cli_sandbox() -> SandboxResolved:
    from giga_agent.core.agent.runtime_resolver import RuntimeResolver

    resolver = await RuntimeResolver.create(
        {
            "configurable": {
                "langgraph_auth_user": {
                    "identity": "00000000-0000-0000-0000-000000000000"
                }
            }
        }
    )
    return await resolver.get_sandbox()


class SandboxResolveService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._sandbox_repo = SandboxRepository(db)
        self._provider_repo = SandboxProviderRepository(db)

    @classmethod
    async def get_cached_or_db(
        cls,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
        *,
        session: AsyncSession,
    ) -> SandboxResolved:
        if _is_cli_runtime():
            return await _resolve_cli_sandbox()

        cached = await SandboxRepository.cache_get_pair(
            owner_id=user_id,
            provider_id=provider_id,
        )
        if cached is not None:
            if cached.sandbox.owner_id == user_id:
                return SandboxResolved(
                    provider=cached.provider,
                    sandbox=cached.sandbox,
                )
            await SandboxRepository.cache_invalidate_pair(
                owner_id=user_id,
                provider_id=cached.provider.id,
            )
        return await cls(session).get_or_create_for_user(
            user_id=user_id,
            provider_id=provider_id,
            settings=settings,
            use_cache=False,
        )

    async def resolve_provider(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
    ) -> SandboxProvider | SandboxProviderSnapshot:
        if _is_cli_runtime():
            return (await _resolve_cli_sandbox()).provider

        resolved_provider_id = provider_id
        if resolved_provider_id is None:
            user = await UserRepository.get_cached_or_db(user_id, session=self.db)
            if user is None or user.sandbox_provider_id is None:
                raise ProviderNotFoundError(
                    f"User {user_id} sandbox provider is not configured"
                )
            resolved_provider_id = user.sandbox_provider_id

        provider = await self._provider_repo.get_by_id(resolved_provider_id)
        if provider is None:
            raise ProviderNotFoundError(f"Provider {resolved_provider_id} not found")
        return provider

    async def get_or_create_for_user(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        settings: dict | None = None,
        *,
        use_cache: bool = True,
    ) -> SandboxResolved:
        if _is_cli_runtime():
            return await _resolve_cli_sandbox()

        if use_cache:
            cached = await SandboxRepository.cache_get_pair(
                owner_id=user_id,
                provider_id=provider_id,
            )
            if cached is not None:
                return SandboxResolved(
                    provider=cached.provider,
                    sandbox=cached.sandbox,
                )

        provider = await self.resolve_provider(user_id, provider_id)
        sandbox = await self._sandbox_repo.get_by_owner_and_provider(user_id, provider.id)
        if sandbox is not None:
            logger.debug(
                "Found existing sandbox %s for user %s (provider %s)",
                sandbox.id,
                user_id,
                provider.id,
            )
            sandbox.provider = provider
            resolved = SandboxResolved(provider=provider, sandbox=sandbox)
            snapshot = SandboxRepository.to_pair_snapshot(provider, sandbox)
            await SandboxRepository.cache_set_pair(
                owner_id=user_id,
                provider_id=provider.id,
                snapshot=snapshot,
                is_default=(provider_id is None),
            )
            return resolved

        sandbox = await self._sandbox_repo.create(
            owner_id=user_id,
            provider_id=provider.id,
            settings=settings,
        )
        logger.info(
            "Created sandbox %s for user %s (provider %s)",
            sandbox.id,
            user_id,
            provider.id,
        )
        sandbox.provider = provider
        resolved = SandboxResolved(provider=provider, sandbox=sandbox)
        snapshot = SandboxRepository.to_pair_snapshot(provider, sandbox)
        await SandboxRepository.cache_set_pair(
            owner_id=user_id,
            provider_id=provider.id,
            snapshot=snapshot,
            is_default=(provider_id is None),
        )
        return resolved
