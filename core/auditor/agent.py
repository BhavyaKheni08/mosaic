import asyncio
import uuid
import httpx
from typing import List
from datetime import datetime

from .models import StaleNode, AuditEvent, ClaimType
from .decay import calculate_decayed_confidence
from .logger import AuditLogger
from .utils import log_telemetry, AuditorLLMError, AuditorGraphConnectionError, with_fallback

class AuditorAgent:
    def __init__(self, confidence_threshold: float = 0.5):
        self.confidence_threshold = confidence_threshold
        self.logger = AuditLogger()
        self.is_running = False
        
    @with_fallback(fallback_value=[])
    async def fetch_nodes_from_graph(self) -> List[StaleNode]:
        """
        Mock implementation. Real implementation would query Neo4j.
        """
        log_telemetry("GRAPH", "Fetching nodes from graph...")
        # Stubs for testing
        return [
            StaleNode(
                node_id="node_123",
                claim_type=ClaimType.RESEARCH_CLAIM,
                claim_text="The sky is red",
                stored_confidence=0.9,
                last_updated=datetime(2023, 1, 1),
                incoming_dependencies=5
            )
        ]
        
    def calculate_risk_score(self, node: StaleNode) -> float:
        """
        Risk Score = Incoming Dependency Count * Staleness
        Where Staleness = Original Confidence - Current Confidence
        """
        if node.current_confidence is None:
            return 0.0
        staleness = max(0.0, node.stored_confidence - node.current_confidence)
        return float(node.incoming_dependencies) * staleness

    @with_fallback(fallback_value=None)
    async def validate_with_llm(self, claim_text: str, node_id: str) -> float:
        """
        Calls a local Llama 3 API (e.g. via Ollama on http://localhost:11434).
        If fails, returns None.
        """
        log_telemetry("LLM", f"Validating claim for Node {node_id}: '{claim_text}'")
        try:
            # Mock the behavior of a local LLM call.
            await asyncio.sleep(0.5)
            if "red" in claim_text:
                return 0.1 # Not true
            return 0.9 # True
        except Exception as e:
            raise AuditorLLMError(f"Local LLM completely failed: {str(e)}")

    async def _audit_loop(self):
        while self.is_running:
            try:
                log_telemetry("AGENT", "Starting audit cycle.")
                nodes: List[StaleNode] = await self.fetch_nodes_from_graph()
                
                # Apply decay
                for node in nodes:
                    node.current_confidence = calculate_decayed_confidence(
                        stored_confidence=node.stored_confidence,
                        last_updated=node.last_updated,
                        claim_type=node.claim_type,
                        node_id=node.node_id
                    )
                
                # Filter nodes below threshold
                stale_nodes = [n for n in nodes if n.current_confidence is not None and n.current_confidence < self.confidence_threshold]
                
                # Prioritize by risk score
                stale_nodes.sort(key=self.calculate_risk_score, reverse=True)
                
                for node in stale_nodes:
                    log_telemetry("AGENT", f"Auditing Node {node.node_id} (Risk: {self.calculate_risk_score(node):.2f})")
                    
                    new_conf = await self.validate_with_llm(node.claim_text, node_id=node.node_id)
                    
                    if new_conf is None:
                        # Fallback case: LLM failed. Retain current decayed confidence
                        new_conf = node.current_confidence if node.current_confidence is not None else node.stored_confidence
                        action = "DECAYED_ONLY"
                        reasoning = "LLM validation failed. Maintained decayed confidence."
                    else:
                        action = "VALIDATED"
                        reasoning = "LLM completed re-evaluation."

                    event = AuditEvent(
                        event_id=str(uuid.uuid4()),
                        node_id=node.node_id,
                        old_confidence=node.stored_confidence,
                        new_confidence=new_conf,
                        action_taken=action,
                        reasoning=reasoning
                    )
                    self.logger.log_event(event)

            except Exception as e:
                log_telemetry("ERROR", f"Unhandled error in audit loop: {str(e)}")
            
            await asyncio.sleep(60) # Run every minute

    def start(self):
        """Starts the background asyncio loop."""
        if not self.is_running:
            self.is_running = True
            asyncio.create_task(self._audit_loop())
            log_telemetry("AGENT", "Auditor Agent started.")

    def stop(self):
        """Stops the loop."""
        self.is_running = False
        log_telemetry("AGENT", "Auditor Agent stopped.")
