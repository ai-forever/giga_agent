from typing import TypedDict, Annotated
from langchain.messages import AnyMessage
from langgraph.graph import add_messages


class CollectionMetadata(TypedDict):
    description: str


class Collection(TypedDict):
    name: str
    uuid: str
    metadata: CollectionMetadata


class Secret(TypedDict):
    name: str
    value: str
    description: str | None


class AgentState(TypedDict):  # noqa: D101
    messages: Annotated[list[AnyMessage], add_messages]
    kernel_id: str
    tool_call_index: int
    tools: list
    collections: list[Collection]
    mcp_tools: list[dict[str, dict]]
    instructions: str
    secrets: list[Secret]


class Context(TypedDict):
    identity: str
