from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from langchain.tools import ToolRuntime

from giga_agent.core.logging import get_logger
from giga_agent.core.agent.runtime_resolver import RuntimeResolver
from giga_agent.embeddings.base import BaseEmbeddingRuntime

_MODELS_DIR = Path(__file__).resolve().parent / "models"
_MODEL_PREFIX = "sentiment_"
_MODEL_SUFFIX = ".joblib"

logger = get_logger(__name__)


def _validate_texts(texts: list[str]) -> None:
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        raise ValueError("All texts must be strings.")


def probs_to_labels(probas, classes):
    """Получает матрицу вероятностей (n × k) и список классов,
    возвращает массив меток длиной n.
    """
    idx = np.argmax(probas, axis=1)
    return classes[idx]


def _build_model_key(file_path: Path) -> str | None:
    stem = file_path.stem
    if not stem.startswith(_MODEL_PREFIX):
        return None
    key = stem[len(_MODEL_PREFIX) :].strip()
    return key or None


def _preload_models() -> dict[str, Any]:
    preloaded: dict[str, Any] = {}
    if not _MODELS_DIR.exists():
        return preloaded
    paths = sorted(_MODELS_DIR.glob(f"{_MODEL_PREFIX}*{_MODEL_SUFFIX}"))
    if not paths:
        return preloaded

    logger.info(
        "Preloading sentiment models",
        dir=str(_MODELS_DIR),
        total=len(paths),
    )
    for idx, model_path in enumerate(paths, start=1):
        key = _build_model_key(model_path)
        if key is None:
            continue
        started = time.monotonic()
        logger.info(
            "Loading sentiment model",
            key=key,
            path=str(model_path),
            progress=f"{idx}/{len(paths)}",
        )
        try:
            preloaded[key] = joblib.load(model_path)
        except Exception:
            logger.exception(
                "Failed to load sentiment model",
                key=key,
                path=str(model_path),
            )
            raise
        else:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "Loaded sentiment model",
                key=key,
                elapsed_ms=elapsed_ms,
                progress=f"{idx}/{len(paths)}",
            )
    return preloaded


# _PRELOADED_SENTIMENT_MODELS: dict[str, Any] = _preload_models()


async def _resolve_user_embeddings(
    tool_runtime: ToolRuntime,
) -> tuple[BaseEmbeddingRuntime, str]:
    resolver = RuntimeResolver.from_config(tool_runtime.config)
    embedding_runtime = await resolver.get_embedding_runtime()
    return embedding_runtime, embedding_runtime.model_id


async def predict_sentiments(
    texts: list[str],
    tool_runtime: ToolRuntime | None = None,
) -> list[str]:
    """Определяет настроение текста в одну из этих меток:
    ["positive", "negative", "neutral"]
    Используй в том случае, если нужно определить настроение массива текстов
    Помни, что ты должен вызывать функцию только с именованными агрументами.

    Пример: predict_sentiments(texts=['текст'])

    Args:
        texts: Список текстов на анализ
        tool_runtime: Runtime текущего вызова инструмента

    """
    _validate_texts(texts)
    if tool_runtime is None:
        raise ValueError("tool_runtime is required for predict_sentiments.")

    embedding_runtime, embedding_model_id = await _resolve_user_embeddings(tool_runtime)
    clf = _PRELOADED_SENTIMENT_MODELS.get(embedding_model_id)
    if clf is None:
        available = ", ".join(sorted(_PRELOADED_SENTIMENT_MODELS.keys())) or "нет"
        raise ValueError(
            "Для вашей embedding модели не настроена sentiment модель. "
            "Попросите администратора настроить sentiment модель под вашу embedding модель. "
            f"Текущая embedding модель: '{embedding_model_id}'. "
            f"Доступные sentiment модели: {available}."
        )

    embeddings = await embedding_runtime.get_embeddings()
    embs = await embeddings.aembed_documents(texts)
    matrix = np.vstack(embs).astype("float32")
    labels = probs_to_labels(clf.predict_proba(matrix), clf.classes_)
    return [str(label) for label in labels]


async def get_embeddings(
    texts: list[str],
    tool_runtime: ToolRuntime | None = None,
) -> list[list[float]]:
    """Получает эмбединги для списка текстов
    (можно использовать для кластеризации вместе с umap и hdbscan)

    Args:
        texts: Список текстов
        tool_runtime: Runtime текущего вызова инструмента

    """
    _validate_texts(texts)
    if tool_runtime is None:
        raise ValueError("tool_runtime is required for get_embeddings.")

    embedding_runtime, _ = await _resolve_user_embeddings(tool_runtime)
    embeddings = await embedding_runtime.get_embeddings()
    embs = await embeddings.aembed_documents(texts)
    return [list(map(float, row)) for row in embs]
