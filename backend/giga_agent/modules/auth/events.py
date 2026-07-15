from uuid import UUID
from giga_agent.core.events import BaseEvent


class UserCreatedEvent(BaseEvent):
    user_id: UUID
    email: str


class UserEmbeddingChangedEvent(BaseEvent):
    user_id: UUID
    old_embedding_id: UUID | None
    new_embedding_id: UUID | None
