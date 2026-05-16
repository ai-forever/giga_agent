"""Finalize node — загружает принятый draft в sandbox как FileResponse.

Отделён от compose, чтобы revise-петля не плодила файлы в sandbox.
Запись в state: report (FileResponse), done.
"""
from __future__ import annotations

import uuid

from langchain_core.runnables import RunnableConfig

from giga_agent.core.logging import get_logger
from giga_agent.modules.deep_research.config import DeepResearchState
from giga_agent.modules.subagents_legacy.uploads import upload_files_for_config_user


logger = get_logger(__name__)


def _resolve_upload_prefix_from_config(config: RunnableConfig) -> str:
    configurable = (config or {}).get("configurable", {}) or {}
    thread_id = configurable.get("thread_id")
    if isinstance(thread_id, str):
        clean = thread_id.strip().strip("/")
        if clean:
            return clean
    return f"temporary/{uuid.uuid4().hex}"


async def finalize_node(state: DeepResearchState, config: RunnableConfig):
    draft = (state.get("report_draft") or "").strip()
    if not draft:
        draft = f"# Исследование: {state.get('task') or ''}\n\n_Отчёт пуст._\n"

    prefix = _resolve_upload_prefix_from_config(config)
    try:
        uploaded = await upload_files_for_config_user(
            config,
            files=[
                {
                    "file_name": f"{prefix}/deep_research_report.md",
                    "file_type": "text",
                    "content": draft.encode("utf-8"),
                }
            ],
        )
    except Exception as exc:
        logger.warning(
            "deep_research.finalize: upload failed",
            error_type=type(exc).__name__,
        )
        return {"done": "Не удалось сохранить отчёт в sandbox"}

    return {
        "report": uploaded[0].model_dump(mode="json"),
        "done": "Отчёт готов",
    }
