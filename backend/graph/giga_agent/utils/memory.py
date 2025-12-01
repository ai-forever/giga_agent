from mem0 import AsyncMemory
import os

from giga_agent.utils.llm import load_llm, load_embeddings


async def get_memory_from_config() -> AsyncMemory:
    llm_model = load_llm()
    embedding_model = load_embeddings()
    result = await embedding_model.aembed_query("Init") # Чтобы не хардкодить размер эмбеддинга, легче кинуть один запрос
    # Общий путь к базе данных для персистентного хранилища памяти
    config = {
        "embedder": {
            "provider": "langchain",
            "config": {
                "model": embedding_model,
                "embedding_dims": len(result)
            }
        },
        "llm": {
            "provider": "langchain",
            "config": {
                "model": llm_model
            }
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "embedding_model_dims": len(result),
                "host": "qdrant",
                "port": 6333
            }
        }

    }
    return await AsyncMemory.from_config(config)


def format_memories(memories: dict) -> str:
    if not memories.get("results"):
        return ""
    formatted = "\n".join([f"- {m['memory']}" for m in memories["results"]])
    return f"""
====
ДОЛГОСРОЧНАЯ ПАМЯТЬ
Ниже приведены воспоминания о прошлых взаимодействиях с этим пользователем. 
Используй их, чтобы поддерживать контекст и персонализировать ответы.

{formatted}
====
"""

_cached_memory = None

async def get_memory():
    global _cached_memory
    if _cached_memory is None:
        _cached_memory = await get_memory_from_config()
    return _cached_memory

