"""LangGraph thread management for Telegram runtime."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from cashews import cache
from langgraph_sdk import get_client
from langgraph_sdk.errors import NotFoundError

from giga_agent.channels.telegram.constants import ASSISTANT_ID, THREAD_TTL_SECONDS, \
    TELEGRAM_CHANNEL_TYPE
from giga_agent.channels.telegram.runtime import get_thread_external_user_id
from giga_agent.channels.telegram.utils import _langgraph_url, _make_token
from giga_agent.core.cache import setup_cache
from giga_agent.core.db import get_session_factory
from giga_agent.core.logging import get_logger
from giga_agent.models.channel import ChannelBot, ChannelBotRepository
from giga_agent.models.rag import RagCollectionsRepository

logger = get_logger(__name__)


class TelegramThreadService:
    def __init__(self, *, bot_row: ChannelBot, user_email: str):
        self.bot_row = bot_row
        self.user_email = user_email

    def _thread_lock_key(self, chat_id: int, external_user_id: str | None) -> str:
        return (
            f"channel:tg-thread:{self.bot_row.id}:{chat_id}:{external_user_id}"
        )

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

    def resolve_external_user_id(self, message: Any) -> str | None:
        return get_thread_external_user_id(message)

    async def stop_thread_runs(self, client: Any, thread_id: str) -> None:
        cancelled_run_ids: set[str] = set()
        for status in ("running", "pending"):
            try:
                runs = await client.runs.list(thread_id, limit=100, status=status)
                for run in runs or []:
                    run_id = run.get("run_id")
                    if run_id is None or run_id in cancelled_run_ids:
                        continue
                    await client.runs.cancel(
                        thread_id,
                        run_id,
                        action="interrupt",
                    )
                    cancelled_run_ids.add(run_id)
            except NotFoundError:
                pass
        if cancelled_run_ids:
            logger.info(
                "Stopped %d active runs for thread %s",
                len(cancelled_run_ids),
                thread_id,
            )

    async def _stop_thread_runs_background(self, thread_id: str) -> None:
        try:
            token = self.create_token()
            client = self.create_client(token)
            try:
                await self.stop_thread_runs(client, thread_id)
            finally:
                await client.aclose()
        except Exception:
            logger.warning(
                "Failed to stop active runs for thread %s",
                thread_id,
                exc_info=True,
            )

    async def get_or_create_thread(
        self,
        client: Any,
        repo: ChannelBotRepository,
        chat_id: int,
        external_user_id: str | None = None,
    ) -> str:
        # Distributed lock (Redis-backed in prod, in-memory locally) serializes
        # concurrent updates for the same chat — e.g. album parts arriving in
        # parallel — so they cannot each create a thread.
        setup_cache()
        lock_key = self._thread_lock_key(chat_id, external_user_id)
        async with cache.lock(lock_key, expire=30, wait=True):
            return await self._get_or_create_thread(
                client,
                repo,
                chat_id,
                external_user_id,
            )

    async def _get_or_create_thread(
        self,
        client: Any,
        repo: ChannelBotRepository,
        chat_id: int,
        external_user_id: str | None = None,
    ) -> str:
        thread_row = await repo.get_thread(
            self.bot_row.id,
            str(chat_id),
            external_user_id,
        )
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

        metadata = {"telegram_chat_id": str(chat_id)}
        if external_user_id is not None:
            metadata["telegram_user_id"] = external_user_id
        metadata["channel"] = TELEGRAM_CHANNEL_TYPE
        metadata["is_channel"] = True
        # Telegram has no approval UI — run autonomously so server-side tool calls
        # execute without an interrupt (the message tool stays an MCP action and
        # still interrupts for inline-button prompts).
        metadata["auto_approve"] = True
        thread = await client.threads.create(metadata=metadata)
        thread_id = thread["thread_id"]
        await repo.create_thread(
            bot_id=self.bot_row.id,
            external_chat_id=str(chat_id),
            external_user_id=external_user_id,
            langgraph_thread_id=thread_id,
        )
        return thread_id

    async def reset_thread(
        self,
        repo: ChannelBotRepository,
        chat_id: int,
        external_user_id: str | None = None,
        stop_thread: bool = True,
    ) -> None:
        thread_row = await repo.get_thread(
            self.bot_row.id,
            str(chat_id),
            external_user_id,
        )
        if thread_row is not None:
            if stop_thread:
                asyncio.create_task(
                    self._stop_thread_runs_background(thread_row.langgraph_thread_id)
                )
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
