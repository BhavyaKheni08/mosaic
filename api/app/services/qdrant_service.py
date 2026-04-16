from app.utils.logger import trace_error, logger
from app.schemas.exceptions import DatabaseError

@trace_error
async def search_vector_store(session_id: str, query_vector: list, limit: int = 5):
    """
    Stub for Qdrant service search.
    """
    logger.info(f"Searching Qdrant for session {session_id}")
    # Initialize Qdrant client and search
    # try:
    #     client.search(collection_name="knowledge", query_vector=query_vector, limit=limit)
    # except Exception as e:
    #     raise DatabaseError(f"Qdrant search failed: {str(e)}")
    
    return [{"id": "doc1", "score": 0.99}, {"id": "doc2", "score": 0.85}]
