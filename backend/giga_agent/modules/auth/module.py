from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter

from giga_agent.conf import get_settings
from giga_agent.core.module import BaseModule
from giga_agent.modules.auth import security, api
from giga_agent.core.events import event_bus
from giga_agent.modules.auth.events import UserCreatedEvent
from giga_agent.models.users import UserRepository
from giga_agent.core.logging import get_logger

logger = get_logger(__name__)


class AuthModule(BaseModule):
    id: str = "auth"

    def get_api_router(self, **kwargs: Any) -> APIRouter:
        _ = kwargs
        from giga_agent.modules.auth import invites_api

        combined = APIRouter()
        combined.include_router(api.router)
        combined.include_router(invites_api.router)
        return combined

    def get_models(self, **kwargs: Any) -> list[type]:
        _ = kwargs
        from giga_agent.models.invite import Invite
        from giga_agent.models.usage import UsageEvent

        return [Invite, UsageEvent]

    async def on_startup(self, session: AsyncSession, **kwargs: Any):
        _ = kwargs
        logger.info("Checking for existing users...")
        user_repo = UserRepository(session)

        # Проверяем есть ли пользователи
        users = await user_repo.get_all(limit=1)

        if not users:
            logger.info("No users found. Creating admin user...")
            settings = get_settings()
            admin_email = settings.giga_agent_admin_email
            admin_password = settings.giga_agent_admin_password

            hashed_password = security.get_password_hash(admin_password)

            admin = await user_repo.create(
                email=admin_email,
                hashed_password=hashed_password,
                is_active=True,
                is_superuser=True,
                role="owner",  # первый пользователь инстанса — владелец команды
                first_name="Admin",
            )

            await event_bus.publish(
                UserCreatedEvent(user_id=admin.id, email=admin.email)
            )

            logger.info(f"Admin user created: {admin_email}:{admin_password}")
        else:
            logger.info("Users exist. Skipping admin creation.")

        # Команда инстанса: системная группа All Members (создание + бэкфилл)
        # и авто-членство новых пользователей по UserCreatedEvent.
        from giga_agent.core.team import ensure_all_members_group, ensure_subscribed

        await ensure_all_members_group(session)
        await ensure_subscribed()
