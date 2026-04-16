import os
import json
import logging
from datetime import datetime
from neo4j import GraphDatabase, exceptions as neo4j_exceptions
from qdrant_client import QdrantClient
import google.generativeai as genai

def setup_logger():
    class PrefixFormatter(logging.Formatter):
        def format(self, record):
            return f"[MOSAIC-MEMORY] {super().format(record)}"
            
    logger = logging.getLogger("mosaic_memory")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(PrefixFormatter("%(levelname)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

logger = setup_logger()

def fallback_logger(action: str, payload: dict, error_msg: str):
    fallback_file = "fallback_storage.json"
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "error": error_msg,
        "payload": payload
    }
    
    try:
        data = []
        if os.path.exists(fallback_file):
            with open(fallback_file, "r") as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    pass
        data.append(entry)
        with open(fallback_file, "w") as f:
            json.dump(data, f, indent=4)
        logger.warning(f"Saved fallback payload to {fallback_file}")
    except Exception as e:
        logger.error(f"[fallback_logger] Error: Failed to write to fallback storage: {str(e)}")

def get_neo4j_driver():
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        return driver
    except neo4j_exceptions.ServiceUnavailable as e:
        logger.error(f"[get_neo4j_driver] Error: Neo4j Connection Failed. Check URI. Details: {e}")
        return None
    except Exception as e:
        logger.error(f"[get_neo4j_driver] Error: Unexpected Neo4j error: {e}")
        return None

def get_qdrant_client():
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    try:
        client = QdrantClient(url=url)
        return client
    except Exception as e:
        logger.error(f"[get_qdrant_client] Error: Qdrant Connection Failed. Check URL. Details: {e}")
        return None

def check_factual_contradiction(new_claim: str, old_claim: str, claim_id: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("[check_factual_contradiction] Error: GEMINI_API_KEY not set. Cannot run LLM judge.")
        return "NO"
        
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
        Determine if the following two claims factually contradict each other.
        A contradiction means both cannot be true at the same time in the same context.
        Return 'YES' if they contradict, and 'NO' if they do not.
        
        Claim 1: {new_claim}
        Claim 2: {old_claim}
        
        Answer (YES or NO):
        """
        response = model.generate_content(prompt)
        text = response.text.strip().upper()
        if 'YES' in text:
            return "YES"
        return "NO"
    except Exception as e:
        logger.critical(f"[ConflictDetector] LLM Judge timed out. Defaulting to 'Uncertain' status for Claim #{claim_id}.")
        return "UNCERTAIN"
