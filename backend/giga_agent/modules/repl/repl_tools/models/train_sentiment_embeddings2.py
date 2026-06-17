"""Тренировка sentiment-модели под эмбединги 'Embeddings-2'.

Читает конфиг эмбедингов из giga_agent.conf.gigachat.json, считает эмбединги
для постов из rusentiment_random_posts.csv и обучает LogisticRegression.
Результат сохраняется как models/sentiment_Embeddings-2.joblib — имя файла
должно совпадать с embedding model_id (см. sentiment.py: _build_model_key).
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from langchain_gigachat import GigaChatEmbeddings
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parents[4]  # backend/
_CONFIG = _BACKEND / "giga_agent.conf.gigachat.json"
_CSV = _BACKEND / "additional_data" / "sentiment_analysis" / "rusentiment_random_posts.csv"
_BATCH = 64
_LABELS = ["neutral", "positive", "negative"]


def build_embeddings() -> tuple[GigaChatEmbeddings, str]:
    cfg = json.loads(_CONFIG.read_text())
    emb_cfg = cfg["embedding"]
    conn = emb_cfg["connector"]
    model_id = emb_cfg["model_id"]

    api_type = str(conn.get("gigachat_api_type", "prod")).lower()
    client_kwargs = {
        "model": model_id,
        "verify_ssl_certs": False,
        "scope": conn.get("gigachat_scope"),
    }
    if api_type == "prod":
        client_kwargs["credentials"] = conn.get("gigachat_credentials")
        if conn.get("gigachat_base_url"):
            client_kwargs["base_url"] = conn["gigachat_base_url"]
        if conn.get("gigachat_auth_url"):
            client_kwargs["auth_url"] = conn["gigachat_auth_url"]
    else:
        client_kwargs["base_url"] = conn.get("gigachat_base_url")
        client_kwargs["user"] = conn.get("gigachat_username")
        client_kwargs["password"] = conn.get("gigachat_password")

    client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
    return GigaChatEmbeddings(**client_kwargs), model_id


def embed_documents(emb: GigaChatEmbeddings, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    total = len(texts)
    for start in range(0, total, _BATCH):
        chunk = texts[start : start + _BATCH]
        out.extend(emb.embed_documents(chunk))
        print(f"  embedded {min(start + _BATCH, total)}/{total}")
    return out


def load_dataset() -> tuple[list[str], np.ndarray]:
    """Все строки трёх целевых классов, без дубликатов и пустых текстов."""
    df = pd.read_csv(_CSV)
    df = df[df["label"].isin(_LABELS)].copy()
    df["text"] = df["text"].astype(str).str.strip()
    df = df[df["text"] != ""]
    df = df.drop_duplicates(subset="text", keep="first")
    df = df.sort_values("text", kind="stable").reset_index(drop=True)
    return list(df["text"]), df["label"].to_numpy()


def get_embeddings(model_id: str, texts: list[str]) -> np.ndarray:
    """Считает эмбединги с кэшем в .npz: повторные запуски не дёргают API.

    Кэш валиден, только если сохранённый список текстов точно совпадает с текущим.
    """
    cache_path = _HERE / f"_emb_cache_{model_id}.npz"
    if cache_path.exists():
        cached = np.load(cache_path, allow_pickle=True)
        if list(cached["texts"]) == texts:
            print(f"Using cached embeddings: {cache_path.name} ({len(texts)} texts)")
            return cached["embeddings"].astype("float32")
        print("Cache texts mismatch — recomputing embeddings")

    emb, _ = build_embeddings()
    print(f"Computing embeddings for {len(texts)} texts...")
    embs = embed_documents(emb, texts)
    X = np.vstack(embs).astype("float32")
    np.savez(cache_path, embeddings=X, texts=np.array(texts, dtype=object))
    print(f"Cached embeddings: {cache_path.name}")
    return X


def main() -> None:
    _, model_id = build_embeddings()
    print(f"Embedding model: {model_id}")

    texts, y = load_dataset()
    print(f"Train rows (all 3 classes, deduped): {len(texts)}")
    print(pd.Series(y).value_counts().to_string())

    X = get_embeddings(model_id, texts)

    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000)),
        ]
    )
    param_grid = {
        "clf__C": [0.0001, 0.0003, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0],
        "clf__class_weight": [None, "balanced"],
    }
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    search = GridSearchCV(
        pipe,
        param_grid,
        scoring="f1_macro",
        cv=cv,
        n_jobs=-1,
        refit=True,
    )
    print("Running grid search (5-fold CV, scoring=f1_macro)...")
    search.fit(X, y)
    print(f"Best params: {search.best_params_}")
    print(f"Best CV f1_macro: {search.best_score_:.4f}")

    # Честный отчёт по out-of-fold предсказаниям лучшей конфигурации.
    y_pred = cross_val_predict(search.best_estimator_, X, y, cv=cv, n_jobs=-1)
    print(classification_report(y, y_pred, digits=3))

    # best_estimator_ уже переобучен на всех данных (refit=True) — его и сохраняем.
    out_path = _HERE / f"sentiment_{model_id}.joblib"
    joblib.dump(search.best_estimator_, out_path, compress=3)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
