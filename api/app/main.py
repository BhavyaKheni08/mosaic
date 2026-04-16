import asyncio
import uuid
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.utils.logger import logger, trace_error
from app.schemas.events import QueryRequest
from app.services.agent_orchestrator import run_agent_workflow
from app.services.graph_service import fetch_graph_data
from app.bus import event_bus

app = FastAPI(title="Mosaic Multi-Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Mosaic Multi-Agent API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/query")
@trace_error
async def submit_query(request: QueryRequest, background_tasks: BackgroundTasks):
    """
    Endpoint to initiate a background LangGraph run.
    """
    session_id = request.session_id or str(uuid.uuid4())
    logger.info(f"Initiating workflow background task for session {session_id}")
    
    # Run the orchestrator completely detached from the HTTP req/res lifecycle
    background_tasks.add_task(run_agent_workflow, session_id, request.query)
    
    return {"status": "workflow_started", "session_id": session_id}

@app.get("/graph")
@trace_error
async def get_cytoscape_graph(session_id: str):
    """
    Endpoint mapping Neo4j relationships to Cytoscape.js readable format.
    """
    cytoscape_json = await fetch_graph_data(session_id)
    return cytoscape_json

@app.websocket("/ws/run/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSockets exclusively handle UI updates by listening to the EventBus.
    Implements a 30s heartbeat.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for session {session_id}")
    
    async def heartbeat():
        try:
            while True:
                await asyncio.sleep(30)
                # Send a ping to detect dangling/stale UI clients
                await websocket.send_text("ping")
        except asyncio.CancelledError:
            pass

    heartbeat_task = asyncio.create_task(heartbeat())
    
    try:
        # Subscribe to EventBus and stream any AgentEvents as JSON
        async for event in event_bus.subscribe(session_id):
            await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        logger.info(f"WebSocket cleanly disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket stream encountered error for session {session_id}: {str(e)}")
    finally:
        heartbeat_task.cancel()
        logger.info(f"WebSocket cleanup complete for session {session_id}")
