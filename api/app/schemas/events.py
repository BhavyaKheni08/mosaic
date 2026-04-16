from pydantic import BaseModel
from typing import Any, Dict, Optional
from datetime import datetime

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

class AgentEvent(BaseModel):
    session_id: str
    event_type: str  # e.g., 'agent_spawned', 'claim_made', 'step_completed'
    agent_id: str
    data: Dict[str, Any]
    timestamp: datetime = datetime.now()

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
