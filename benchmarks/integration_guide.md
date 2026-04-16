# MOSAIC Integration Guide — Open-Port Registry

> **Version**: 1.0.0 · **Phase**: 7 (Benchmarks & Evaluation)  
> This document is the canonical reference for extending MOSAIC without
> modifying core internals. It describes every "Open Node" in the system,
> the JSON schemas agents must honour, and step-by-step instructions for
> adding new evaluation datasets.

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Hook Points — Open Nodes](#2-hook-points--open-nodes)
3. [Interface Standards — Agent Debate JSON Schema](#3-interface-standards--agent-debate-json-schema)
4. [Extensibility Guide — Adding a New Evaluation Dataset](#4-extensibility-guide--adding-a-new-evaluation-dataset)
5. [Extensibility Guide — Adding a New LLM Provider](#5-extensibility-guide--adding-a-new-llm-provider)
6. [Extensibility Guide — Adding a New Agent Role](#6-extensibility-guide--adding-a-new-agent-role)
7. [Port / Service Registry](#7-port--service-registry)
8. [Error Schema](#8-error-schema)

---

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  MOSAIC Orchestrator                 │
│   (core/orchestrator/engine.py)                     │
│                                                     │
│  ┌───────────┐   ┌────────────┐   ┌──────────────┐ │
│  │  Router   │──▶│ Agent Slot │──▶│ Recovery Node│ │
│  └───────────┘   └────────────┘   └──────────────┘ │
│        │                 │                          │
│  registry.py       lifecycle.py                     │
└─────────────────────────────────────────────────────┘
         │                  │
         ▼                  ▼
┌──────────────────┐  ┌───────────────────┐
│  Debate Engine   │  │   Auditor Agent   │
│  (core/debate/)  │  │  (core/auditor/)  │
└──────────────────┘  └───────────────────┘
         │                  │
         ▼                  ▼
┌──────────────────────────────────────────┐
│         GraphMemoryManager               │
│  Neo4j (port 7687) + Qdrant (port 6333) │
│  (core/memory/manager.py)               │
└──────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────┐
│          FastAPI Backend                 │
│  (api/app/main.py) — HTTP :8000          │
│  EventBus (WebSocket /ws/run)            │
└──────────────────────────────────────────┘
```

---

## 2. Hook Points — Open Nodes

The following locations are explicitly designed to accept new integrations
**without** editing any other file.

### 2.1 Dynamic Router — New LLM Provider

| Attribute | Value |
|---|---|
| **File** | `core/orchestrator/registry.py` |
| **Class** | `ModelRegistry` |
| **Method** | `register_model(config: ModelConfig)` |
| **Hook Condition** | Called before `build_orchestrator_engine()` |

To plug in a new provider, create a `ModelConfig` and register it:

```python
from core.orchestrator.registry import ModelConfig, ModelTier, ModelRegistry

new_model = ModelConfig(
    name="claude-3-5-sonnet",
    tier=ModelTier.HIGH,
    provider="anthropic",          # arbitrary string — used for logging
    max_tokens=8192,
    temperature=0.3,
    extra={"api_key_env": "ANTHROPIC_API_KEY"},
)
registry.register_model(new_model)
```

> **Open Node ID**: `ORCH-ROUTER-001`  
> The router's `route()` method selects the cheapest model within the
> required tier. A new model is automatically considered if its `tier`
> matches the classified complexity.

---

### 2.2 Capability Registry — New Agent Role

| Attribute | Value |
|---|---|
| **File** | `core/orchestrator/registry.py` |
| **Class** | `CapabilityRegistry` |
| **Method** | `register_agent(role: str, spec: AgentSpec)` |

```python
from core.orchestrator.registry import AgentSpec, CapabilityRegistry

spec = AgentSpec(
    role="legal_analyst",
    system_prompt="You are an expert in contract law …",
    tools=["web_search", "document_reader"],
    max_iterations=5,
)
cap_registry.register_agent("legal_analyst", spec)
```

> **Open Node ID**: `ORCH-CAPS-002`

---

### 2.3 Debate Protocol — New Participant Agent

| Attribute | Value |
|---|---|
| **File** | `core/debate/registry.py` |
| **Class** | `DebateRegistry` |
| **Method** | `register_participant(agent_id: str, handler: Callable)` |

A participant handler receives a `DebateRound` object and must return a
`DebateMessage` (see §3 for schema).

```python
from core.debate.registry import DebateRegistry
from core.debate.schema import DebateMessage, MessageRole

def my_custom_validator(round_ctx):
    # … validation logic …
    return DebateMessage(
        agent_id="custom_validator",
        role=MessageRole.CRITIC,
        content="My critique …",
        confidence=0.87,
    )

DebateRegistry.instance().register_participant("custom_validator", my_custom_validator)
```

> **Open Node ID**: `DEBATE-PART-003`

---

### 2.4 Auditor — New Claim Type

| Attribute | Value |
|---|---|
| **File** | `core/auditor/decay.py` |
| **Enum** | `ClaimType` |
| **Config** | `DecayConfig.LAMBDAS` |

Steps:
1. Add a new member to `ClaimType` (e.g. `LEGAL_PRECEDENT = "LEGAL_PRECEDENT"`).
2. Add its decay rate: `DecayConfig.LAMBDAS["LEGAL_PRECEDENT"] = 0.005`.
3. A lambda of `0.0` means the claim never decays.

> **Open Node ID**: `AUDIT-CLAIM-004`

---

### 2.5 Memory Manager — New Contradiction Relationship

| Attribute | Value |
|---|---|
| **File** | `core/memory/manager.py` |
| **Class** | `GraphMemoryManager` |
| **Hook** | `store_claim()` calls `_detect_conflicts()` before write |

To add a custom conflict-resolution strategy:

```python
class MyConflictResolver:
    def resolve(self, existing_claim, new_claim) -> str:
        """Return 'KEEP_EXISTING' | 'REPLACE' | 'MERGE'."""
        …

manager.set_conflict_resolver(MyConflictResolver())
```

> **Open Node ID**: `MEM-CONFLICT-005`

---

### 2.6 FastAPI Backend — New Endpoint

| Attribute | Value |
|---|---|
| **File** | `api/app/main.py` |
| **Router** | `api/app/routers/` (add a new file here) |
| **EventBus** | Import from `api/app/services/event_bus.py` |

No existing routes need modification. Declare a new `APIRouter`, emit events
via `event_bus.publish(event_type, payload)`, and include the router in
`main.py`.

> **Open Node ID**: `API-ROUTE-006`

---

### 2.7 Benchmarks — New Evaluation Script

> This is the primary concern of Phase 7. Details in §4.

> **Open Node ID**: `BENCH-EVAL-007`

---

## 3. Interface Standards — Agent Debate JSON Schema

Every message exchanged during an agent debate **must** conform to this schema.
The debate engine validates each message against it; non-conforming messages
are dropped and logged.

### 3.1 `DebateMessage` (inbound / outbound)

```jsonc
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DebateMessage",
  "type": "object",
  "required": ["session_id", "round_id", "agent_id", "role", "content", "confidence", "timestamp"],
  "properties": {
    "session_id":  { "type": "string", "format": "uuid",
                     "description": "Unique identifier for the debate session." },
    "round_id":    { "type": "integer", "minimum": 1,
                     "description": "Monotonically increasing round counter." },
    "agent_id":    { "type": "string", "minLength": 1,
                     "description": "Registered agent identifier (must exist in DebateRegistry)." },
    "role":        { "type": "string",
                     "enum": ["RESEARCHER", "CRITIC", "SYNTHESIZER", "OBSERVER"],
                     "description": "The functional role of this message's author." },
    "content":     { "type": "string", "minLength": 1,
                     "description": "The agent's natural-language contribution." },
    "confidence":  { "type": "number", "minimum": 0.0, "maximum": 1.0,
                     "description": "Self-reported confidence in the content (0 = uncertain, 1 = certain)." },
    "citations":   { "type": "array", "items": { "type": "string" },
                     "description": "Optional list of source node IDs or URLs supporting the claim." },
    "timestamp":   { "type": "string", "format": "date-time",
                     "description": "ISO 8601 UTC timestamp of message creation." },
    "parent_id":   { "type": ["string", "null"],
                     "description": "The round_id of the message this is responding to, or null." },
    "metadata":    { "type": "object", "additionalProperties": true,
                     "description": "Arbitrary key-value pairs for tracing / debugging." }
  },
  "additionalProperties": false
}
```

### 3.2 `DebateSession` (session envelope)

```jsonc
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DebateSession",
  "type": "object",
  "required": ["session_id", "query", "participants", "max_rounds", "status"],
  "properties": {
    "session_id":    { "type": "string", "format": "uuid" },
    "query":         { "type": "string" },
    "participants":  {
      "type": "array",
      "items": { "type": "string" },
      "description": "List of registered agent_ids participating in this session."
    },
    "max_rounds":    { "type": "integer", "minimum": 1, "maximum": 20 },
    "status":        { "type": "string",
                       "enum": ["PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"] },
    "final_answer":  { "type": ["string", "null"] },
    "messages":      { "type": "array", "items": { "$ref": "#/definitions/DebateMessage" } },
    "created_at":    { "type": "string", "format": "date-time" },
    "completed_at":  { "type": ["string", "null"], "format": "date-time" }
  }
}
```

### 3.3 Validation Example (Python)

```python
import jsonschema, json
from pathlib import Path

schema = json.loads(Path("benchmarks/schemas/debate_message.json").read_text())

def validate_message(msg: dict) -> bool:
    try:
        jsonschema.validate(instance=msg, schema=schema)
        return True
    except jsonschema.ValidationError as e:
        logger.error(f"[MOSAIC-ERR][Component: DebateValidator][Func: validate_message] "
                     f"-> Invalid message: {e.message}")
        return False
```

---

## 4. Extensibility Guide — Adding a New Evaluation Dataset

Follow these **six steps** to register a new benchmark dataset with the
MOSAIC evaluation harness.

### Step 1 — Choose or Create a Loader

Create a file `benchmarks/<dataset_name>_loader.py`:

```python
from pathlib import Path
from typing import List
# Re-use the QAPair dataclass from accuracy_eval.py
from accuracy_eval import QAPair

class MyDatasetLoader:
    def load(self, path: Path, n_samples: int) -> List[QAPair]:
        # ... parse your dataset format ...
        return [QAPair(id=..., question=..., answers=..., dataset="my_dataset")]
```

### Step 2 — Register the Loader in `accuracy_eval.py`

In `DatasetLoader.load()`, add a branch:

```python
elif dataset == "my_dataset":
    return self._load_my_dataset(n_samples)
```

Implement `_load_my_dataset()` following the pattern of `_load_triviaqa()`.

### Step 3 — Supply a Synthetic Fallback

Add at least 10 representative QA pairs to `DatasetLoader._synthetic_fallback()`
so CI can run without network access.

### Step 4 — Add CLI Support

In `accuracy_eval.py` argparse, extend `--dataset` choices:

```python
parser.add_argument("--dataset", choices=["triviaqa", "popqa", "my_dataset"], ...)
```

### Step 5 — Update `run_all_evals.sh`

Add a line to the shell script:

```bash
python benchmarks/accuracy_eval.py --dataset my_dataset --samples 200 --save
```

### Step 6 — Document the Dataset

Add a row to the table below:

| Dataset | Loader Method | Default Samples | Notes |
|---|---|---|---|
| TriviaQA | `_load_triviaqa` | 200 | HuggingFace `trivia_qa` |
| PopQA | `_load_popqa` | 100 | HuggingFace `akariasai/PopQA` |
| *(your dataset)* | `_load_my_dataset` | *(n)* | *(source / format)* |

---

## 5. Extensibility Guide — Adding a New LLM Provider

1. **Install the SDK**: Add the package to `api/requirements.txt`.
2. **Create an adapter** in `core/orchestrator/adapters/<provider>.py` implementing
   the `LLMAdapter` interface:
   ```python
   class AnthropicAdapter(LLMAdapter):
       def complete(self, prompt: str, config: ModelConfig) -> str: ...
   ```
3. **Register the model** using `ModelRegistry.register_model()` (see §2.1).
4. **Set the env variable** referenced in `ModelConfig.extra["api_key_env"]`.
5. **Add pricing** to `benchmarks/cost_analysis.py → PRICING` dict.

> **Open Node**: `ORCH-ROUTER-001`

---

## 6. Extensibility Guide — Adding a New Agent Role

1. **Define the system prompt** and tool set as an `AgentSpec`.
2. **Register** via `CapabilityRegistry.register_agent()` (see §2.2).
3. **Route traffic** by setting `required_role` in the orchestrator input state.
4. **Add debate participation** (optional) via `DebateRegistry.register_participant()` (see §2.3).
5. **Write a unit test** in `tests/test_<role>.py` verifying the agent lifecycle.

> **Open Node**: `ORCH-CAPS-002`

---

## 7. Port / Service Registry

| Service | Default Port | Protocol | Config Key |
|---|---|---|---|
| FastAPI (MOSAIC API) | 8000 | HTTP/WS | `API_PORT` in `.env` |
| Neo4j Bolt | 7687 | Bolt | `NEO4J_URI` |
| Neo4j HTTP | 7474 | HTTP | — |
| Qdrant | 6333 | HTTP gRPC | `QDRANT_HOST`, `QDRANT_PORT` |
| Ollama (Llama 3) | 11434 | HTTP | `OLLAMA_BASE_URL` |

> If any service is unreachable, all MOSAIC components emit a structured error:
> `[MOSAIC-ERR][Component: X][Func: Y] -> Failed to reach <Service>; Check local port <P>.`

---

## 8. Error Schema

All MOSAIC errors follow this human-readable log format:

```
[MOSAIC-ERR][Component: <ComponentName>][Func: <function_name>] -> <human message>; <remediation hint>. Error: <exception>
```

| Field | Description |
|---|---|
| `ComponentName` | The class or module that failed (e.g. `Auditor`, `GraphSeeder`) |
| `function_name` | The exact Python function name |
| `human message` | Plain-English description of what went wrong |
| `remediation hint` | Actionable suggestion (check port, install package, etc.) |
| `exception` | The raw Python exception string |

### Example

```
[MOSAIC-ERR][Component: Auditor][Func: validate_claim] -> Failed to reach Qdrant;
Check local port 6333 and ensure `docker-compose up qdrant` has been run.
Error: ConnectionRefusedError: [Errno 111] Connection refused
```
