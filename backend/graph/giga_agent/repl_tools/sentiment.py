import os

import joblib
import numpy as np

from giga_agent.settings import settings
from giga_agent.utils.llm import load_embeddings


def probs_to_labels(probas, classes):
    """Получает матрицу вероятностей (n × k) и список классов,
    возвращает массив меток длиной n.
    """
    idx = np.argmax(probas, axis=1)  # позиция максимальной вероятности по строке
    return classes[idx]


__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

clf = joblib.load(
    os.path.join(
        __location__,
        settings.llm.giga_agent_sentiment_model,
    ),
)


async def predict_sentiments(texts: list[str]) -> list[str]:
    """Определяет настроение текста в одну из этих меток:
    ["positive", "negative", "neutral"]
    Используй в том случае, если нужно определить настроение массива текстов
    Помни, что ты должен вызывать функцию только с именованными агрументами.

    Пример: predict_sentiments(texts=['текст'])

    Args:
        texts: Список текстов на анализ

    """
    if not all([isinstance(text, str) for text in texts]):
        raise ValueError("All texts must be strings.")
    emb = load_embeddings()
    embs = await emb.aembed_documents(texts)
    X = np.vstack(embs).astype("float32")
    return list(probs_to_labels(clf.predict_proba(X), clf.classes_))


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Получает эмбединги для списка текстов
    (можно использовать для кластеризации вместе с umap и hdbscan)

    Args:
        texts: Список текстов

    """
    if not all([isinstance(text, str) for text in texts]):
        raise ValueError("All texts must be strings.")
    emb = load_embeddings()
    embs = await emb.aembed_documents(texts)
    return embs
