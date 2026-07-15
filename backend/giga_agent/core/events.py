from typing import Callable, Type, Awaitable, Dict, List
from pydantic import BaseModel


class BaseEvent(BaseModel):
    """Base class for all application events."""

    pass


EventHandler = Callable[[BaseEvent], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._subscribers: Dict[Type[BaseEvent], List[EventHandler]] = {}

    def subscribe(self, event_type: Type[BaseEvent], handler: EventHandler):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    async def publish(self, event: BaseEvent):
        """
        Publishes an event to all subscribers.
        """
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])

        for handler in handlers:
            await handler(event)


# Global event bus instance
event_bus = EventBus()
