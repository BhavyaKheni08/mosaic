class BaseAPIError(Exception):
    """Base exception for all Custom API errors"""
    pass

class AgentError(BaseAPIError):
    """Raised for errors inside nodes/LangGraph components."""
    pass

class DatabaseError(BaseAPIError):
    """Raised for Neo4j or Qdrant connection/query issues."""
    pass

class StreamError(BaseAPIError):
    """Raised for WebSocket or Event Bus transport issues."""
    pass
