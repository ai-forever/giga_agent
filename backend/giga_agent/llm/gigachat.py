"""GigaChat LLM runtime."""

from __future__ import annotations

import asyncio
import mimetypes
import uuid

from langchain_gigachat import GigaChat
from langchain_core.messages import HumanMessage
from pydantic import PrivateAttr

from giga_agent.connectors.base import BaseConnector
from giga_agent.connectors.gigachat_token_cache import (
    get_gigachat_access_token_cached,
    should_skip_gigachat_token_cache,
)
from giga_agent.llm.base import (
    AvailableModel,
    BaseLLMRuntime,
    ImageInput,
    ModelFetchError,
)
from giga_agent.llm.registry import LLMRegistry


@LLMRegistry.register("gigachat")
class GigaChatRuntime(BaseLLMRuntime):
    _llm_lock: asyncio.Lock | None = PrivateAttr(default=None)

    def model_post_init(self, __context) -> None:
        self._llm_lock = asyncio.Lock()

    async def get_llm(self) -> GigaChat:
        llm = self._llm_instance
        if llm is not None:
            return llm

        if self._llm_lock is None:
            self._llm_lock = asyncio.Lock()

        async with self._llm_lock:
            llm = self._llm_instance
            if llm is None:
                llm = await self._create_llm()
                self._llm_instance = llm
            return llm

    @classmethod
    def supported_connector_types(cls) -> list[str]:
        return ["gigachat"]

    @classmethod
    async def fetch_available_models(
        cls,
        *,
        connector: BaseConnector,
    ) -> list[AvailableModel]:
        kwargs = connector.get_connection_kwargs()
        if kwargs is None:
            return []

        try:
            llm_kwargs = dict(kwargs)
            if not should_skip_gigachat_token_cache():
                llm_kwargs["access_token"] = await get_gigachat_access_token_cached(
                    connector
                )
            llm = GigaChat(**llm_kwargs)
            return [
                AvailableModel(
                    id=model.id_,
                    name=model.id_,
                    owned_by=model.owned_by,
                )
                for model in (await llm.aget_models()).data
            ]
        except Exception as e:
            raise ModelFetchError("gigachat", str(e)) from e

    async def _create_llm(self) -> GigaChat:
        connection_kwargs = self.connector.get_connection_kwargs()
        if connection_kwargs is None:
            raise ValueError(
                f"Invalid connection settings for connector {self.connector.__class__.__name__}"
            )
        llm_kwargs = dict(connection_kwargs)
        if not should_skip_gigachat_token_cache():
            llm_kwargs["access_token"] = await get_gigachat_access_token_cached(
                self.connector
            )
        llm_kwargs["streaming"] = True
        settings = self._settings_payload()
        model_kwargs = {
            "temperature": settings.get("temperature"),
            "max_tokens": settings.get("max_tokens", 1280000),
            "top_p": settings.get("top_p"),
            "profanity_check": False,
            "timeout": 60,
        }
        clean_model_kwargs = {k: v for k, v in model_kwargs.items() if v is not None}
        return GigaChat(
            model=self.model_id,
            **llm_kwargs,
            **clean_model_kwargs,
        )

    def can_analyze_images(self) -> bool:
        return True

    async def analyze_images(
        self,
        *,
        prompt: str,
        images: list[ImageInput],
    ) -> str:
        if not images:
            raise ValueError("At least one image is required for analysis.")

        llm = await self.get_llm()
        async def _upload(image: ImageInput):
            extension = mimetypes.guess_extension(image["mime_type"]) or ".jpg"
            return await llm.aupload_file(
                (f"{uuid.uuid4().hex}{extension}", image["image_bytes"]),
                purpose="general",
            )

        uploaded_files = await asyncio.gather(*(_upload(image) for image in images))
        attachment_ids = [uploaded.id_ for uploaded in uploaded_files]
        response = await llm.with_config(tags=["nostream"]).ainvoke(
            [
                HumanMessage(
                    content=[{"type": "text", "text": prompt}],
                    additional_kwargs={"attachments": attachment_ids},
                )
            ]
        )
        return response.text
