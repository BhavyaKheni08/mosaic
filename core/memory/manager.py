import uuid
from .models import Claim
from .schema import NodeLabel, EdgeType
from .utils import get_neo4j_driver, get_qdrant_client, logger, fallback_logger, check_factual_contradiction

class GraphMemoryManager:
    def __init__(self, neo4j_creds=None, qdrant_creds=None):
        self.neo4j_driver = get_neo4j_driver()
        self.qdrant_client = get_qdrant_client()
        self.collection_name = "claims"
        
        if self.qdrant_client:
            try:
                self.qdrant_client.get_collection(self.collection_name)
            except Exception:
                logger.warning(f"Qdrant collection '{self.collection_name}' not found. Please ensure it is created with proper vector configuration.")

    def store_claim(self, content: str, source_id: str, agent_id: str) -> str:
        claim = Claim(content=content, source_id=source_id, agent_id=agent_id)
        
        try:
            # 1. Similarity search
            # Mocking embedding generated for vector databases as proper integration with
            # huggingface or gemini embedding models requires specific setup
            mock_vector = [0.1] * 768 
            contradicted_claim_id = None
            
            if self.qdrant_client:
                try:
                    search_result = self.qdrant_client.search(
                        collection_name=self.collection_name,
                        query_vector=mock_vector,
                        limit=5,
                        score_threshold=0.8
                    )
                    
                    for hit in search_result:
                        old_content = hit.payload.get("content", "")
                        old_id = hit.payload.get("id", "")
                        status_str = check_factual_contradiction(content, old_content, claim.id)
                        if status_str == 'YES':
                            contradicted_claim_id = old_id
                            logger.info(f"Contradiction found between new claim and old claim '{old_id}'.")
                            break
                        elif status_str == 'UNCERTAIN':
                            contradicted_claim_id = old_id
                            claim_status = 'Uncertain'
                            break
                except Exception as e:
                    logger.error(f"[GraphMemoryManager.store_claim] Error: Qdrant Search Failed. Details: {e}")
            
            # 2. Store in Neo4j
            if self.neo4j_driver:
                with self.neo4j_driver.session() as session:
                    # Create new claim node
                    query = f"""
                    CREATE (c:{NodeLabel.CLAIM.value} {{id: $id, content: $content, source_id: $source_id, agent_id: $agent_id, timestamp: $timestamp, status: $status}})
                    RETURN c.id
                    """
                    status_val = 'Uncertain' if 'claim_status' in locals() and claim_status == 'Uncertain' else 'Verified'
                    session.run(query, id=claim.id, content=claim.content, source_id=claim.source_id, agent_id=claim.agent_id, timestamp=claim.timestamp.isoformat(), status=status_val)
                    
                    if contradicted_claim_id:
                        # Create CONTRADICTS edge
                        edge_query = f"""
                        MATCH (c1:{NodeLabel.CLAIM.value} {{id: $new_id}})
                        MATCH (c2:{NodeLabel.CLAIM.value} {{id: $old_id}})
                        CREATE (c1)-[:{EdgeType.CONTRADICTS.value}]->(c2)
                        """
                        session.run(edge_query, new_id=claim.id, old_id=contradicted_claim_id)
            else:
                raise Exception("Neo4j Driver is unavailable.")
                
            # 3. Store in Qdrant
            if self.qdrant_client:
                from qdrant_client.models import PointStruct
                self.qdrant_client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        PointStruct(
                            id=str(uuid.uuid4()),
                            vector=mock_vector,
                            payload={"id": claim.id, "content": claim.content}
                        )
                    ]
                )
                
            return claim.id
                
        except Exception as e:
            error_msg = f"[GraphMemoryManager.store_claim] Error: Failed to store claim. Data that failed: {content}. Suggested fix: Check DB URIs and connectivity. Details: {str(e)}"
            logger.error(error_msg)
            # Use model_dump to get dict from pydantic v2
            fallback_payload = claim.model_dump() if hasattr(claim, 'model_dump') else claim.dict()
            fallback_logger("store_claim", fallback_payload, error_msg)
            return claim.id
            
    def get_entity_graph(self, entity_name: str) -> dict:
        try:
            if not self.neo4j_driver:
                raise Exception("Neo4j Driver is unavailable.")
                
            with self.neo4j_driver.session() as session:
                query = f"""
                MATCH (e:{NodeLabel.ENTITY.value} {{name: $name}})
                OPTIONAL MATCH (c:{NodeLabel.CLAIM.value})-[:{EdgeType.MENTIONS.value}]->(e)
                OPTIONAL MATCH (c)-[r]->(other)
                RETURN e, collect(c) as claims, collect(r) as relationships, collect(other) as others
                """
                result = session.run(query, name=entity_name)
                record = result.single()
                
                if record and record["e"]:
                    return {
                        "entity": dict(record["e"]),
                        "claims": [dict(c) for c in record["claims"]],
                        "others": [dict(o) for o in record["others"]]
                    }
                return {}
        except Exception as e:
            error_msg = f"[GraphMemoryManager.get_entity_graph] Error: Failed to retrieve graph for entity: {entity_name}. Suggested fix: Check Neo4j instance. Details: {str(e)}"
            logger.error(error_msg)
            fallback_logger("get_entity_graph", {"entity_name": entity_name}, error_msg)
            return {}

    def resolve_conflict(self, claim_id_a: str, claim_id_b: str, winner_id: str):
        try:
            if not self.neo4j_driver:
                raise Exception("Neo4j Driver is unavailable.")
                
            with self.neo4j_driver.session() as session:
                query = f"""
                MATCH (c1:{NodeLabel.CLAIM.value} {{id: $id_a}})-[r:{EdgeType.CONTRADICTS.value}]-(c2:{NodeLabel.CLAIM.value} {{id: $id_b}})
                DELETE r
                SET c1.resolved = true, c2.resolved = true
                WITH c1, c2
                MATCH (winner:{NodeLabel.CLAIM.value} {{id: $winner_id}})
                SET winner.is_winner = true
                """
                session.run(query, id_a=claim_id_a, id_b=claim_id_b, winner_id=winner_id)
                logger.info(f"Conflict between {claim_id_a} and {claim_id_b} resolved. Winner: {winner_id}")
        except Exception as e:
            error_msg = f"[GraphMemoryManager.resolve_conflict] Error: Failed to resolve conflict between {claim_id_a} and {claim_id_b}. Suggested fix: Verify IDs exist. Details: {str(e)}"
            logger.error(error_msg)
            fallback_logger("resolve_conflict", {"claim_id_a": claim_id_a, "claim_id_b": claim_id_b, "winner_id": winner_id}, error_msg)
            
    def get_uncertain_nodes(self) -> list:
        try:
            if not self.neo4j_driver:
                raise Exception("Neo4j Driver is unavailable.")
                
            with self.neo4j_driver.session() as session:
                query = f"""
                MATCH (c1:{NodeLabel.CLAIM.value})-[:{EdgeType.CONTRADICTS.value}]->(c2:{NodeLabel.CLAIM.value})
                WHERE NOT coalesce(c1.resolved, false) = true AND NOT coalesce(c2.resolved, false) = true
                RETURN c1, c2
                """
                result = session.run(query)
                uncertainties = []
                for record in result:
                    uncertainties.append({
                        "claim_a": dict(record["c1"]),
                        "claim_b": dict(record["c2"])
                    })
                return uncertainties
        except Exception as e:
            error_msg = f"[GraphMemoryManager.get_uncertain_nodes] Error: Failed to retrieve uncertain nodes. Details: {str(e)}"
            logger.error(error_msg)
            fallback_logger("get_uncertain_nodes", {}, error_msg)
            return []
