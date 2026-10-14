"""Shared model metadata used by the API and agent runtime."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parent / "models_config.json"
DEFAULT_CONTEXT_WINDOW = 128_000


@lru_cache(maxsize=1)
def get_models_config() -> dict[str, Any]:
    if not _CONFIG_PATH.is_file():
        return {"models": {}}
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_context_window(model_id: str, explicit: int | None = None) -> int:
    """Resolve an input context window with a conservative stable fallback."""
    if explicit is not None and explicit > 0:
        return explicit
    models = get_models_config().get("models") or {}
    model = models.get(model_id) or {}
    configured = model.get("context_window")
    if isinstance(configured, int) and configured > 0:
        return configured
    return DEFAULT_CONTEXT_WINDOW


__all__ = ["DEFAULT_CONTEXT_WINDOW", "get_models_config", "resolve_context_window"]
