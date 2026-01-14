import os
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter

from giga_agent.core.module import BaseModule
from giga_agent.auth import models, security, api
from giga_agent.core.events import event_bus
from giga_agent.auth.events import UserCreatedEvent

logger = logging.getLogger(__name__)


class AuthModule(BaseModule):
    id: str = "auth"

    def get_api_router(self) -> APIRouter:
        return api.router

    async def on_startup(self, session: AsyncSession):
        logger.info("Checking for existing users...")
        result = await session.execute(select(models.User))
        user = result.scalars().first()

        if not user:
            logger.info("No users found. Creating admin user...")
            admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
            admin_password = os.getenv("ADMIN_PASSWORD", "admin")

            hashed_password = security.get_password_hash(admin_password)

            admin = models.User(
                email=admin_email,
                hashed_password=hashed_password,
                is_active=True,
                is_superuser=True,
            )
            session.add(admin)
            await session.commit()
            
            await event_bus.publish(UserCreatedEvent(
                user_id=admin.id,
                email=admin.email
            ))

            logger.info(f"Admin user created: {admin_email}")
        else:
            logger.info("Users exist. Skipping admin creation.")
