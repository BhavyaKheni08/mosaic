import asyncio
from typing import Dict, AsyncGenerator, List
from app.utils.logger import logger
from app.schemas.events import AgentEvent
from app.schemas.exceptions import StreamError

class EventBus:
    """
    Decoupled Async Event Bus.
    Allows agents to emit events asynchronously without having to know about websockets.
    """
    def __init__(self):
        # Dictionary mapping session_id to a list of queues
        # Enables multiple subscribers to the same session
        self.subscribers: Dict[str, List[asyncio.Queue]] = {}

    async def emit(self, session_id: str, payload: AgentEvent):
        """
        Push an event to all subscribers of a specific session.
        This function should be called by the agents/orchestrator.
        """
        if session_id in self.subscribers:
            for queue in self.subscribers[session_id]:
                await queue.put(payload)
            logger.debug(f"EventBus emitted {payload.event_type} to {len(self.subscribers[session_id])} subscriber(s) for session {session_id}")
        else:
            logger.warning(f"EventBus dropped event {payload.event_type} for session {session_id} (No active subscribers)")

    async def subscribe(self, session_id: str) -> AsyncGenerator[AgentEvent, None]:
        """
        Subscribe to a session's events stream.
        Yields events as they are pushed to the queue.
        """
        queue = asyncio.Queue()
        if session_id not in self.subscribers:
            self.subscribers[session_id] = []
        self.subscribers[session_id].append(queue)
        
        logger.info(f"EventBus created new subscription for session {session_id}")
        
        try:
            while True:
                event = await queue.get()
                # A special teardown payload could break the loop if desired
                yield event
        except asyncio.CancelledError:
            logger.info(f"EventBus subscription cancelled for session {session_id}")
        except Exception as e:
            logger.error(f"EventBus error for session {session_id}: {str(e)}")
            raise StreamError(f"Stream error for session {session_id}: {str(e)}")
        finally:
            if session_id in self.subscribers and queue in self.subscribers[session_id]:
                self.subscribers[session_id].remove(queue)
                if not self.subscribers[session_id]:  # clean up if empty
                    del self.subscribers[session_id]
            logger.info(f"EventBus cleaned up subscription for session {session_id}")

# Global instance
event_bus = EventBus()
