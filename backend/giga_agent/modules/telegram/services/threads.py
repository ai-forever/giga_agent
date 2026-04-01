"""LangGraph thread management for Telegram runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph_sdk import get_client

from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.rag import RagCollectionsRepository
from giga_agent.modules.telegram.constants import ASSISTANT_ID, THREAD_TTL_SECONDS
from giga_agent.modules.telegram.models import TelegramBot as TelegramBotModel
from giga_agent.modules.telegram.models import TelegramBotRepository
from giga_agent.modules.telegram.utils import _langgraph_url, _make_token

logger = get_logger(__name__)


class TelegramThreadService:
    def __init__(self, *, bot_row: TelegramBotModel, user_email: str):
        self.bot_row = bot_row
        self.user_email = user_email

    @property
    def assistant_id(self) -> str:
        return ASSISTANT_ID

    def create_token(self) -> str:
        return _make_token(self.bot_row.user_id, self.user_email)

    def create_client(self, token: str) -> Any:
        return get_client(
            url=_langgraph_url(),
            headers={"Authorization": f"Bearer {token}"},
        )

    async def get_or_create_thread(
        self,
        client: Any,
        repo: TelegramBotRepository,
        chat_id: int,
    ) -> str:
        thread_row = await repo.get_thread(self.bot_row.id, chat_id)
        if thread_row is not None:
            expired = False
            age = 0.0
            if thread_row.updated_at:
                age = (
                    datetime.now(timezone.utc)
                    - thread_row.updated_at.replace(tzinfo=timezone.utc)
                ).total_seconds()
                if age > THREAD_TTL_SECONDS:
                    expired = True
            if expired:
                logger.info(
                    "Thread for chat %s expired (age=%ds), creating new",
                    chat_id,
                    age,
                )
                await repo.delete_thread(thread_row)
            else:
                try:
                    await client.threads.get(thread_row.langgraph_thread_id)
                    await repo.touch_thread(thread_row)
                    return thread_row.langgraph_thread_id
                except Exception:
                    logger.info(
                        "Thread %s no longer exists in LangGraph, recreating",
                        thread_row.langgraph_thread_id,
                    )
                    await repo.delete_thread(thread_row)

        thread = await client.threads.create(metadata={"telegram_chat_id": str(chat_id)})
        thread_id = thread["thread_id"]
        await repo.create_thread(self.bot_row.id, chat_id, thread_id)
        return thread_id

    async def reset_thread(self, repo: TelegramBotRepository, chat_id: int) -> None:
        thread_row = await repo.get_thread(self.bot_row.id, chat_id)
        if thread_row is not None:
            await repo.delete_thread(thread_row)

    async def load_collections_payload(self) -> list[dict[str, Any]]:
        collections_payload: list[dict[str, Any]] = []
        try:
            async with (await get_session_factory())() as session:
                rows = await RagCollectionsRepository(session).list_by_owner(
                    self.bot_row.user_id,
                )
                collections_payload = [
                    {"uuid": str(r.id), "name": r.name, "metadata": r.metadata_ or {}}
                    for r in rows
                ]
        except Exception:
            logger.warning(
                "Failed to load RAG collections for user %s",
                self.bot_row.user_id,
            )
        return collections_payload
