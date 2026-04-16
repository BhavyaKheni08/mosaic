import asyncio
from datetime import datetime
import uuid
from app.utils.logger import trace_error, logger
from app.bus import event_bus
from app.schemas.events import AgentEvent
from app.schemas.exceptions import AgentError

async def broadcast_event(session_id: str, event_type: str, agent_id: str, data: dict):
    """
    Utility wrapper to securely cast payloads into AgentEvent and emit to the bus.
    """
    event = AgentEvent(
        session_id=session_id,
        event_type=event_type,
        agent_id=agent_id,
        data=data,
        timestamp=datetime.now()
    )
    await event_bus.emit(session_id, event)

@trace_error
async def mock_agent_node_1(session_id: str, query: str):
    """Mock first node of our agent orchestrator."""
    logger.info(f"Node 1 running for {session_id}")
    await asyncio.sleep(1)
    await broadcast_event(session_id, "agent_spawned", "researcher", {"status": "Spawned researcher agent for query: " + query})
    await asyncio.sleep(2)
    await broadcast_event(session_id, "claim_made", "researcher", {"claim": "LangGraph is a library for building stateful, multi-actor applications."})
    return {"status": "success", "research_done": True}

@trace_error
async def mock_agent_node_2(session_id: str, state: dict):
    """Mock second node of our agent orchestrator."""
    logger.info(f"Node 2 running for {session_id}")
    await broadcast_event(session_id, "agent_spawned", "auditor", {"status": "Auditing findings."})
    await asyncio.sleep(2)
    # Simulate a potential error based on state randomness just for demonstration capability
    # In reality, wrap exceptions in AgentError
    try:
        if not state.get("research_done"):
            raise ValueError("Research wasn't completed")
    except Exception as e:
        raise AgentError(f"Audit failed: {str(e)}")

    await broadcast_event(session_id, "step_completed", "orchestrator", {"status": "Workflow complete"})


@trace_error
async def run_agent_workflow(session_id: str, query: str):
    """
    Simulates a LangGraph execution. This function will be run in a background task
    and emits events to the Event Bus.
    """
    logger.info(f"Starting agent workflow for session {session_id}")
    await broadcast_event(session_id, "workflow_started", "orchestrator", {"query": query})
    
    try:
        # State machine dummy progression
        state1 = await mock_agent_node_1(session_id, query)
        await mock_agent_node_2(session_id, state1)
        
    except Exception as e:
        logger.error(f"Workflow failed for {session_id}")
        await broadcast_event(session_id, "workflow_failed", "orchestrator", {"error": str(e)})
        raise
    
    logger.info(f"Workflow {session_id} finished gracefully.")
