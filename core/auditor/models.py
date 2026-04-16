from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ClaimType(str, Enum):
    STATIC_FACT = "static_fact"
    CURRENT_EVENT = "current_event"
    RESEARCH_CLAIM = "research_claim"
    USER_ASSERTION = "user_assertion"

class StaleNode(BaseModel):
    node_id: str = Field(..., description="Unique ID of the node in the mock graph")
    claim_type: ClaimType = Field(..., description="The type of claim represented by the node")
    claim_text: str = Field(..., description="The actual text or proposition of the node")
    stored_confidence: float = Field(..., ge=0.0, le=1.0, description="Original confidence when last updated")
    last_updated: datetime = Field(..., description="Timestamp of the last update")
    incoming_dependencies: int = Field(default=0, description="Number of other nodes depending on this one")
    current_confidence: Optional[float] = Field(default=None, description="Current confidence after applying decay")

class AuditEvent(BaseModel):
    event_id: str = Field(..., description="Unique identifier for the audit event")
    node_id: str = Field(..., description="ID of the node being audited")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    old_confidence: float = Field(..., description="Confidence prior to the audit")
    new_confidence: float = Field(..., description="Confidence after the audit validation")
    action_taken: str = Field(..., description="E.g., PROMOTED, DECAYED, VALIDATED, DEPRECATED")
    reasoning: str = Field(..., description="LLM reasoning or decay note")
