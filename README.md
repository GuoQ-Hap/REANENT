# PMC Inventory Supply Chain Control Agent

This repository is a first-pass framework for a PMC supply chain control agent. It is intentionally small: the deterministic core loop is separated from model providers, ERP/MES/WMS connectors, and UI layers so each part can be replaced safely. A model-driven chat loop is also available for whitelisted multi-step tool orchestration.

## What This Framework Covers

- Task classification for PMC control requests from the project proposal.
- Lightweight planning with explicit execution steps.
- Tool registry for inventory health, control tower, shortage tracing, shipment verification, purchase verification, weekly shipment plan, exception cases, and knowledge lookup.
- A deterministic inventory-control baseline for early validation.
- CLI entry point for local smoke tests.
- Optional FastAPI entry point for integration later.
- Model-driven chat orchestration with read-only tool execution boundaries.
- Runtime logging, model interaction records, and daily memory review.
- Neo4j-backed table/field metadata graph for data-map lookups.
- Online durable memory lookup from local JSONL records, with daily Milvus memory writes available.

## Architecture

```text
User / System Trigger
  -> Classifier
  -> Planner
  -> Orchestrator
  -> Tool Registry
  -> Domain Decision Engine
  -> Verifier
  -> Response
```

## Current Integration Status

- Data warehouse: the read-only STI connector can query inventory snapshots from `ads_lingxing_all_warehouse_new`. Additional warehouse, forecast, sales, FBA, and domestic-stock tables are documented for later expansion.
- Rule Excel files: stocking rules, reorder quantity, carton size, supplier data, and logistics rules are not yet wired into the calculation engine.
- Business workflows: purchase advice, weekly shipment plans, and exception cases are generated as drafts that require human confirmation. Full PMC, purchase, logistics, and operations approval workflows are still integration work.
- LLM provider: intent recognition, model routing, failure handling, and model-driven tool orchestration are implemented. Future work should focus on richer tool schemas, more real data sources, and stronger approval boundaries.
- Knowledge graph: Neo4j can store the data-warehouse schema graph, including database layers, tables, fields, business concepts, business categories, and supplemented `v1` field comments. The graph is metadata only; realtime inventory quantities remain in the data warehouse.
- Memory: daily review writes durable memories to local JSONL and optionally Milvus. Online `memory_lookup` uses Milvus vector recall first when configured, then falls back to the auditable JSONL store.

See [docs/requirements_extracted.md](docs/requirements_extracted.md) for the extracted project requirements from the rendered PDF.
See [docs/llm_working_standard.md](docs/llm_working_standard.md) for the working standard used by future LLM-assisted development.

## Startup Commands

Run commands from the repository root: `D:\R_TO_AG`.

Start the local test console, which can run module tests and business scenarios without a real model key:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.test_server
```

Then open:

```text
http://127.0.0.1:8765
```

Simple chat window:

```text
http://127.0.0.1:8765/chat.html
```

Run the CLI agent with a real model-backed intent recognizer:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.cli "检查 A100 是否有缺料风险"
```

Run the goal loop with user feedback applied to the next iteration:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.cli "验证 A100 采购建议" --feedback "请按 MOQ 和人工确认边界重新检查"
```

Model routing is handled by `pmc_agent.model_router`. You can inspect it in the test console under 模型调试 -> 模型调度.

Run all unit tests:

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests
```

Optional FastAPI entry point, after installing the `api` extra:

```powershell
$env:PYTHONPATH="src"; uvicorn pmc_agent.api:app --reload
```

## Run

The default CLI uses a model-backed intent recognizer. Copy `.env.example` to `.env`, then fill in your key and API URL:

```powershell
Copy-Item .env.example .env
```

`.env`:

```dotenv
OPENAI_API_KEY=your_api_key
PMC_AGENT_INTENT_MODEL=gpt-5.4-mini
PMC_AGENT_MODEL_DEFAULT=gpt-5.4-mini
PMC_AGENT_MODEL_INTENT_RECOGNITION=gpt-5.4-mini
PMC_AGENT_MODEL_GOAL_REPAIR=gpt-5.4
PMC_AGENT_MODEL_TOOL_ORCHESTRATION=gpt-5.4
PMC_AGENT_MODEL_CONTEXT_SELECTION=gpt-5.4-mini
PMC_AGENT_MODEL_FAILURE_HANDLING=gpt-5.4
PMC_AGENT_MODEL_BUSINESS_EXPLANATION=gpt-5.4
PMC_AGENT_MODEL_SUMMARY=gpt-5.4-mini
PMC_AGENT_MODEL_HIGH_RISK=gpt-5.4
PMC_AGENT_MODEL_LONG_CONTEXT_THRESHOLD=4000
OPENAI_BASE_URL=https://api.openai.com/v1
PMC_AGENT_HTTP_TIMEOUT=30
PMC_AGENT_LOG_LEVEL=INFO
STI_DB_ENABLED=false
STI_DB_HOST=
STI_DB_PORT=9030
STI_DB_USER=
STI_DB_PASSWORD=
STI_DB_NAME=dw_leang
STI_DB_CHARSET=utf8mb4
NEO4J_URI=bolt://10.0.10.106:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=
NEO4J_DATABASE=neo4j
```

If these model environment variables are omitted, `pmc_agent.model_router` falls back to its built-in defaults. The checked-in `.env.example` is the recommended project-level override template.

Use the CLI commands from [Startup Commands](#startup-commands) after `.env` is configured.

The `--feedback` option turns on a lightweight goal loop. The first iteration runs the original goal; each feedback item is merged with the previous observation and executed as the next iteration.

## Database Connector

Set `STI_DB_ENABLED=true` in `.env` to use the read-only STI data warehouse connector. The current implementation reads inventory snapshots from `ads_lingxing_all_warehouse_new`.

When the database connector is enabled, query failures and empty results are treated as real failures. In the deterministic agent loop, failures can be passed to the failure-handling model and returned as a `failure_decision` artifact; demo data is used only when the database connector is disabled.

The connector only performs `SELECT` queries. Control advice and exception handling remain draft outputs inside the agent and are not written back to the database.

## Neo4j Metadata Graph

Neo4j is used as a data-map layer, not as a replacement for the warehouse. It stores:

- `Database -> DataLayer -> DataTable -> DataField`
- `DataField -> FieldConcept`, such as `FNSKU`, `MSKU`, `InventoryQuantity`, `Sales`, `Forecast`
- `DataTable -> BusinessCategory`

Import the warehouse schema metadata:

```powershell
$env:PYTHONPATH="src"; python scripts\import_schema_to_neo4j.py --clear
```

Synchronize live `v1` table fields and supplement safe field comments:

```powershell
$env:PYTHONPATH="src"; python scripts\sync_v1_schema_comments.py
```

The model can use `graph_metadata_lookup` for controlled read-only lookups:

- `describe_table`: list fields for an exact table name.
- `find_tables_by_concept`: find tables containing a concept such as `FNSKU` or `Forecast`.
- `find_fields`: search field names and Chinese comments.

The tool caps metadata results at 200 rows per call.

## Model Routing

Model names are centralized in [src/pmc_agent/model_router.py](src/pmc_agent/model_router.py). Business modules should pass an action type, content, and metadata to the router instead of hard-coding model names.

Current action routes:

- `intent_recognition`: understand the user's request and classify task type.
- `goal_repair`: revise the goal after user feedback.
- `tool_orchestration`: choose or sequence tool calls in dynamic model-driven loops.
- `context_selection`: decide whether hidden recent conversation context is needed.
- `failure_handling`: decide how to respond when a real tool or database query fails.
- `business_explanation`: produce higher-stakes business explanations.
- `summary`: compress observations and execution output.

High-risk content such as purchase confirmation, exception handling, approval, or explicit high-risk metadata is routed to `PMC_AGENT_MODEL_HIGH_RISK`.

## Model-Driven Chat Loop

The chat frontend uses two modes:

- Local demo mode: deterministic heuristic intent recognition for quick UI checks without a model key.
- Real model mode: `pmc_agent.agentic_loop.AgenticPmcLoop` sends the user request, table pool summary, and available tool list to the model first. The model chooses an action, the program executes only that whitelisted action, then returns the observation to the model. The loop continues until the model returns `final_answer` or asks the user for missing input.
- The loop runs up to 20 tool-decision iterations. If the limit is reached, the collected decisions and observations are sent back to the model once more so it must summarize directly with `final_answer`.

Current whitelisted model actions:

- `decide_context`: decide whether hidden recent conversation context is needed.
- `inspect_run_trace`: inspect compact prompts, observations, failed drafts, and action history after self-review fails.
- `run_serial_space`: execute an ordered list of subtasks; tool subtasks run serially, and model-behavior subtasks can run in parallel groups.
- `query_inventory_snapshot`: read inventory snapshots from the read-only STI connector.
- `evaluate_inventory_risk`: calculate risk from the latest returned snapshots.
- `knowledge_lookup`: search SOP, rule, and vector knowledge snippets.
- `memory_lookup`: retrieve durable user preferences, manual feedback, business rules, and failure lessons from local JSONL memory.
- `graph_metadata_lookup`: query Neo4j table/field metadata; it does not return realtime inventory quantities.
- `ask_user`: ask for missing code, scope, or confirmation.
- `final_answer`: return the final answer to the user.

This means real model mode is not "local code classifies first"; the model controls the next step while code enforces read-only tools and schema boundaries.

## Test

Use the unit-test command from [Startup Commands](#startup-commands).

## Test Frontend

The local test console runs without a real model key. It injects scenario intent results so module tests and agent scenarios can be checked quickly:

Use the test-console command from [Startup Commands](#startup-commands), then open `http://127.0.0.1:8765`.

For a simple conversation UI, open `http://127.0.0.1:8765/chat.html`.

## Runtime Records

- 状态流转会进入标准日志，事件名为 `state_transition`。
- 模型交互会按一次用户对话聚合落盘：`logs/model_interactions/conversations/<request_id>.txt`。单个文件内的每条 interaction 会记录 `interaction_type`、输入、输出和错误信息。
- `logs/` 已加入 `.gitignore`，用于本地测试和审计，不进入代码仓库。

## Daily Memory Review

Run the daily memory review from the repository root:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.memory.daily_review
```

The review uses the configured project LLM to read `logs/model_interactions/conversations`, write a
daily Markdown summary to `logs/memory_reviews/YYYY-MM-DD.md`, and append durable preference,
feedback, rule-definition, and failure-lesson records to `logs/memory/memory_records.jsonl`.
Realtime inventory quantities are intentionally kept out of long-term memory.

Online agent runs can use `memory_lookup` to retrieve durable memories. When
`PMC_AGENT_MEMORY_MILVUS_ENABLED=true` and the memory collection is reachable,
the tool searches Milvus first; if Milvus is disabled, empty, or unavailable, it
falls back to `logs/memory/memory_records.jsonl`. Realtime inventory quantities
must still stay out of long-term memory.

Durable memory can also be written to a separate Milvus database and collection:

```dotenv
PMC_AGENT_MEMORY_MILVUS_ENABLED=true
MILVUS_MEMORY_DATABASE=pmc_memory
MILVUS_MEMORY_COLLECTION_NAME=pmc_agent_memory
MILVUS_MEMORY_VECTOR_DIM=1024
PMC_AGENT_MEMORY_EMBEDDING_MODEL=text-embedding-3-large
PMC_AGENT_MEMORY_EMBEDDING_DIMENSIONS=1024
```

The normal knowledge/RAG collection continues to use `MILVUS_DATABASE` and
`MILVUS_COLLECTION_NAME`; long-term agent memory uses the `MILVUS_MEMORY_*` namespace so the two
libraries do not mix.

To run the project's own daily scheduler process:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.memory.scheduler
```

The scheduler runs once per day at `PMC_AGENT_MEMORY_REVIEW_TIME` from `.env`, defaulting to `18:00`.
For a one-shot smoke test:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.memory.scheduler --once
```
