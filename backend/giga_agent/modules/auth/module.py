from typing import Any

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from giga_agent.conf import get_settings
from giga_agent.core.events import event_bus
from giga_agent.core.logging import get_logger
from giga_agent.core.module import BaseModule
from giga_agent.models.users import UserRepository
from giga_agent.modules.auth import api, security
from giga_agent.modules.auth.events import UserCreatedEvent

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

            # Безопасный дефолт: не используем известный/угадываемый пароль. Если
            # оператор не задал GIGA_AGENT_ADMIN_PASSWORD, генерируем случайный и
            # показываем его один раз — иначе инстанс, поднятый «из коробки»,
            # доступен под общеизвестным паролем.
            admin_password, generated_password = security.resolve_admin_password(
                admin_password
            )

            hashed_password = security.get_password_hash(admin_password)

            admin = await user_repo.create(
                email=admin_email,
                hashed_password=hashed_password,
                is_active=True,
                is_superuser=True,
                role="owner",  # первый пользователь инстанса — владелец команды
                first_name="Admin",
            )

            # Первый пользователь — владелец: заводим системную группу команды.
            # Существующие базы наполняет миграция backfill_all_members_group.
            from giga_agent.core.team import create_all_members_group

            await create_all_members_group(session, admin.id)

            await event_bus.publish(
                UserCreatedEvent(user_id=admin.id, email=admin.email)
            )

            # Пароль в лог не пишем: раньше сюда попадал и дефолтный, и явный
            # пароль — он уезжал туда же, куда шлются логи.
            logger.info(f"Admin user created: {admin_email}")
            if generated_password:
                logger.warning(
                    "GIGA_AGENT_ADMIN_PASSWORD не задан — сгенерирован случайный "
                    "пароль администратора (показан один раз, сохраните его): "
                    f"{admin_password}"
                )
        else:
            logger.info("Users exist. Skipping admin creation.")

        # Авто-членство новых пользователей в All Members по UserCreatedEvent.
        from giga_agent.core.team import ensure_subscribed

        await ensure_subscribed()
