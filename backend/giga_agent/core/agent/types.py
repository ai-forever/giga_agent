from typing import TypedDict, Annotated, Required
from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages


class CollectionMetadata(TypedDict):
    description: str


class Collection(TypedDict):
    name: str
    uuid: str
    metadata: CollectionMetadata


# TODO: Вернуть DeltaChannel когда исправят баг с форками в langgraph-api / langgraph-checkpoint-sqlite.
# См. https://www.langchain.com/blog/delta-channels-evolving-agent-runtime
# Баг: при форке (refresh/regenerate) API-сервер некорректно реконструирует состояние DeltaChannel —
# сообщения из всех веток накапливаются вместо показа только активной.
class AgentState(TypedDict):  # noqa: D101
    messages: Required[Annotated[list[AnyMessage], add_messages]]
    kernel_id: str
    collections: list[Collection]
    mcp_tools: list[dict[str, dict]]


class Context(TypedDict):
    identity: str
