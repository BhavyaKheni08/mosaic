# Mosaic API Integration Guide

## 1. Connecting New Logic/Modules
To add a new agent or service:
1. **Schema First:** Define any new event types in `app/schemas/events.py`.
2. **Service Layer:** Place the logic in `app/services/`. 
3. **Event Hook:** Use the `EventBus.emit(session_id, payload)` method to ensure the UI sees the activity.

## 2. Open Nodes (Hook Points)
The system is designed with the following "Open Nodes" for expansion:
- **Graph Transformation Hook:** Located in `services/graph_service.py`. Use this to modify how Neo4j data is mapped to the frontend.
- **Agent Middleware:** Located in `services/agent_orchestrator.py`. Hook here to add pre-processing (sanitization) or post-processing (cost calculation) to every agent run.

## 3. Fallback & Debugging Protocol
- **Function Wrappers:** All functions use the `@trace_error` decorator which logs the exact line and file of failure.
- **WebSocket Heartbeat:** If the agent logic hangs, the WebSocket emits a `ping` every 30s. If no `pong` is received, the session is flagged for cleanup.
- **Mock Mode:** Set `AGENT_MOCK=True` in `.env` to bypass LLM calls and test the WebSocket/UI flow with hardcoded events.
### Pro-Tip for Debugging
In your app/utils/logger.py, use a library like Loguru. It provides much better "backtrace" information than the standard library, making it easy to see exactly where a variable went None in your agent chain.
