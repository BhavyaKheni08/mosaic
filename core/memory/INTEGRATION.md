# MOSAIC Memory Integration Guide
How to Connect New Modules
To use the memory system in a new file, import the manager:

```python
from core.memory.manager import GraphMemoryManager
memory = GraphMemoryManager(neo4j_creds, qdrant_creds)
```

## Open Entry Points (Hooks)
**Input Hook**: `memory.store_claim()` — Use this whenever an agent generates a statement.

**Inquiry Hook**: `memory.get_entity_graph(entity_name)` — Use this to pull everything known about a subject.

**Resolution Hook**: `memory.resolve_conflict(claim_id_a, claim_id_b, winner_id)` — Use this after a debate is finished.

## Debugging & Logs
All logs are output to stdout with the prefix `[MOSAIC-MEMORY]`.

If Neo4j fails, check `fallback_storage.json` for unsaved nodes.
