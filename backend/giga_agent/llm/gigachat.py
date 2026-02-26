"""GigaChat LLM runtime."""

from __future__ import annotations

import mimetypes
import uuid

from langchain_gigachat import GigaChat
from langchain_core.messages import HumanMessage

from giga_agent.connectors.base import BaseConnector
from giga_agent.llm.base import AvailableModel, BaseLLMRuntime, ModelFetchError
from giga_agent.llm.registry import LLMRegistry


@LLMRegistry.register("gigachat")
class GigaChatRuntime(BaseLLMRuntime):
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
            llm = GigaChat(**kwargs)
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

    def _llm(self) -> GigaChat:
        connection_kwargs = self.connector.get_connection_kwargs()
        if connection_kwargs is None:
            raise ValueError(
                f"Invalid connection settings for connector {self.connector.__class__.__name__}"
            )
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
            **connection_kwargs,
            **clean_model_kwargs,
        )

    def can_analyze_image(self) -> bool:
        return True

    async def analyze_image(
        self,
        *,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpg",
    ) -> str:
        extension = mimetypes.guess_extension(mime_type) or ".jpg"
        uploaded = await self.llm.aupload_file(
            (f"{uuid.uuid4().hex}{extension}", image_bytes),
            purpose="general",
        )
        response = await self.llm.ainvoke(
            [
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                    ],
                    additional_kwargs={"attachments": [uploaded.id_]},
                )
            ]
        )
        return response.text
