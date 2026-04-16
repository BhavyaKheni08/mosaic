# Auditor Integration Blueprint

This document details how to integrate and extend the Temporal Decay + Auditor Agent in the Mosaic project.

## Open Nodes (Hooks / Entry Points)

### 1. New Claim Types
To add a new claim type to the system:
1. Update `ClaimType` enum in `models.py`.
2. Add the corresponding decay lambda constant in `DecayConfig.LAMBDAS` in `decay.py`.
**Note:** A lambda of `0.0` means the claim physically never decays.

### 2. Graph Database
Currently, `fetch_nodes_from_graph` in `agent.py` and `_write_to_graph_mock` in `logger.py` are stubs.
To integrate with the real Neo4j graph:
- Import the Neo4j session/driver from `core.memory.manager` or `core.utils`.
- Replace the mock list return logic inside `fetch_nodes_from_graph(self)` with a Cypher query fetching actual Stale Nodes based on their `last_updated` property and `claim_type`. 

### 3. Researcher Agent Swapping
The `AuditorAgent` currently relies on a single-pass Local Llama 3 query (`validate_with_llm`). 
To introduce a more complex Multi-Agent Researcher subsystem (for deeper audits):
1. Create a LangGraph based Researcher in `core.agents`.
2. Import the `research_claim(node.claim_text)` function.
3. Replace the `await self.validate_with_llm(...)` call in `agent.py` with the complex LangGraph execution.
4. Ensure the complex execution returns a float between `0.0` and `1.0`.

## Fallback Design
All critical integrations (Graph reads, LLM calls, Graph writes) use the `@with_fallback` decorator. If your custom Multi-Agent subsystem fails, the system automatically swallows the Exception, logs it with `log_telemetry`, and preserves the current decayed confidence to prevent catastrophic degradation of knowledge.
